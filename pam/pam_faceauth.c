#define PAM_SM_AUTH
#include <security/pam_modules.h>
#include <security/pam_ext.h>
#include <syslog.h>
#include <stddef.h>
#include <string.h>
#include <unistd.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <fcntl.h>
#include <errno.h>
#include <sys/pidfd.h>   /* pidfd_open (glibc 2.36+) */
#include <poll.h>        /* poll, struct pollfd */
#include <signal.h>      /* kill, SIGKILL */

#define DEFAULT_HELPER    "/opt/face-auth/face_auth"
#define HELPER_TIMEOUT_MS 8000

struct config {
    const char *user;
    const char *service;
    const char *helper;
};

/* If arg is exactly "key=value", return a pointer to value, else NULL. */
static const char *arg_value(const char *arg, const char *key)
{
    size_t n = strlen(key);
    if (strncmp(arg, key, n) == 0 && arg[n] == '=')
        return arg + n + 1;
    return NULL;
}

/* Collect options in the loop, decide (missing/default/valid) after it.
 * Returns 0 on success, -1 on any config error. */
static int parse_args(pam_handle_t *pamh, int argc, const char **argv,
                      struct config *cfg)
{
    cfg->user = NULL;
    cfg->service = NULL;
    cfg->helper = NULL;

    for (int i = 0; i < argc; i++) {
        const char *v;

        v = arg_value(argv[i], "user");
        if (v != NULL) {
            cfg->user = v;
            continue;
        }
        v = arg_value(argv[i], "service");
        if (v != NULL) {
            cfg->service = v;
            continue;
        }
        v = arg_value(argv[i], "helper");
        if (v != NULL) {
            cfg->helper = v;
            continue;
        }
        pam_syslog(pamh, LOG_ERR, "unknown option: '%s'", argv[i]);
        return -1;
    }

    if (cfg->user == NULL) {
        pam_syslog(pamh, LOG_ERR, "missing user= option");
        return -1;
    }
    if (cfg->service == NULL) {
        pam_syslog(pamh, LOG_ERR, "missing service= option");
        return -1;
    }
    if (cfg->helper == NULL) {
        cfg->helper = DEFAULT_HELPER;
        pam_syslog(pamh, LOG_INFO, "no helper= option, using default %s",
                   DEFAULT_HELPER);
    }
    if (cfg->helper[0] != '/') {
        pam_syslog(pamh, LOG_ERR, "helper must be an absolute path: '%s'",
                   cfg->helper);
        return -1;
    }
    return 0;
}

/* Run the helper with /dev/null as stdin/stdout/stderr and a deadline.
 * Returns:  0  exited normally, code in *exit_code
 *          -1  error (fork, pidfd/poll, or waitpid failed)
 *          -2  killed by a signal we did not send
 *          -3  timed out and was killed                     */
static int run_helper(const char *path, int *exit_code)
{
    /* Part 1: split into two processes */
    pid_t pid = fork();
    if (pid < 0)
        return -1;

    if (pid == 0) {
        /* Part 2: child disconnects itself. Never return from here. */
        if (setpgid(0, 0) < 0)
            _exit(127);

        int fd = open("/dev/null", O_RDWR);
        if (fd < 0)
            _exit(127);
        if (dup2(fd, 0) < 0 || dup2(fd, 1) < 0 || dup2(fd, 2) < 0)
            _exit(127);
        if (fd > 2)
            close(fd);

        /* Part 3: become the helper */
        char *const argv[] = { (char *)path, NULL };
        char *const envp[] = { "PATH=/usr/bin:/bin", NULL };
        execve(path, argv, envp);
        _exit(127);                             /* only reached if execve failed */
    }

    /* Part 4: parent watches with a deadline */
    setpgid(pid, pid);                          /* also set by parent: closes the race */
    int pfd = pidfd_open(pid, 0);
    int r = -1;                                 /* -1 = never got to watch */
    if (pfd >= 0) {
        struct pollfd p = { .fd = pfd, .events = POLLIN };
        do {
            r = poll(&p, 1, HELPER_TIMEOUT_MS); /* 1 = exited, 0 = timeout, -1 = error */
        } while (r < 0 && errno == EINTR);
        close(pfd);
    }

    /* Part 5: kill anything we don't trust */
    if (r != 1) {
        if (kill(-pid, SIGKILL) < 0)            /* whole group: helper + its children */
            kill(pid, SIGKILL);                 /* fallback: just the child */
    }

    /* Part 6: always reap, on every path */
    int status;
    pid_t w;
    do {
        w = waitpid(pid, &status, 0);
    } while (w == -1 && errno == EINTR);

    /* Part 7: one answer. r == 0 is checked before WIFSIGNALED on purpose. */
    if (w == -1)
        return -1;
    if (r == 0)
        return -3;
    if (r != 1)
        return -1;
    if (WIFEXITED(status)) {
        *exit_code = WEXITSTATUS(status);
        return 0;
    }
    if (WIFSIGNALED(status))
        return -2;
    return -1;
}

/* Default deny: only one case means "authenticated". */
static int map_result(int rc, int code)
{
    if (rc == 0 && code == 0)
        return PAM_SUCCESS;          /* helper ran and said: face matched */
    if (rc == 0 && code == 1)
        return PAM_AUTH_ERR;         /* face seen, but not this user */
    return PAM_AUTHINFO_UNAVAIL;     /* no face, missing helper, timeout, crash, error */
}

PAM_EXTERN int pam_sm_authenticate(pam_handle_t *pamh, int flags,
                                   int argc, const char **argv)
{

    struct config cfg;

    if (parse_args(pamh, argc, argv, &cfg) != 0) {
        pam_syslog(pamh, LOG_ERR, "parsing failed");
        return PAM_SERVICE_ERR;
    }

    const char *user = NULL;
    if (pam_get_user(pamh, &user, NULL) != PAM_SUCCESS || user == NULL)
        return PAM_AUTHINFO_UNAVAIL;

    const void *item = NULL;
    const char *service = "?";
    if (pam_get_item(pamh, PAM_SERVICE, &item) == PAM_SUCCESS && item != NULL)
        service = (const char *)item;

    if (strcmp(user, cfg.user) != 0) {
        pam_syslog(pamh, LOG_INFO, "user mismatch: got '%s', want '%s'",
                   user, cfg.user);
        return PAM_IGNORE;
    }
    if (strcmp(service, cfg.service) != 0) {
        pam_syslog(pamh, LOG_INFO, "service mismatch: got '%s', want '%s'",
                   service, cfg.service);
        return PAM_IGNORE;
    }

    pam_syslog(pamh, LOG_INFO, "guard passed: user=%s service=%s argc=%d flags=%#x",
               user, service, argc, (unsigned)flags);

        if (!(flags & PAM_SILENT))
        pam_info(pamh, "Face check: look at the camera...");

    int code = -999;
    int rc = run_helper(cfg.helper, &code);
    int saved_errno = errno;                    /* copy before anything else runs */
    int result = map_result(rc, code);

    pam_syslog(pamh, LOG_INFO, "helper=%s rc=%d code=%d errno=%d result=%s",
               cfg.helper, rc, code, saved_errno, pam_strerror(pamh, result));

        if (!(flags & PAM_SILENT)) {
            int ir = pam_info(pamh, "Face check: look at the camera...");
            if (ir != PAM_SUCCESS)
                pam_syslog(pamh, LOG_INFO, "pam_info failed: %s", pam_strerror(pamh, ir));
    }
    return result;
}

PAM_EXTERN int pam_sm_setcred(pam_handle_t *pamh, int flags,
                              int argc, const char **argv)
{
    (void)pamh; (void)flags; (void)argc; (void)argv;
    return PAM_SUCCESS;
}
