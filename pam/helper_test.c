#include <stdio.h>
#include <unistd.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <fcntl.h>
#include <errno.h>
#include <sys/pidfd.h>   /* pidfd_open (glibc 2.36+) */
#include <poll.h>        /* poll, struct pollfd */
#include <signal.h>      /* kill, SIGKILL */

#define HELPER_TIMEOUT_MS 8000

/* Run the helper at `path` (absolute path) with /dev/null as stdin/stdout/stderr.
 * Returns:  0  helper exited normally, exit code stored in *exit_code
 *          -1  error (fork, pidfd/poll, or waitpid failed)
 *          -2  helper was killed by a signal we did not send
 *          -3  helper took longer than HELPER_TIMEOUT_MS and was killed   */
static int run_helper(const char *path, int *exit_code)
{
    /* Part 1: split into two processes */
    pid_t pid = fork();
    if (pid < 0)
        return -1;

    if (pid == 0) {
        /* Part 2: child disconnects itself */
        if (setpgid(0, 0) < 0)                  /* own process group, pgid = my pid */
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

    /* Part 7: one answer. r == 0 is checked before WIFSIGNALED on purpose */
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

static void try_one(const char *path)
{
    int code = -999;                            /* -999 = run_helper never wrote it */
    int rc = run_helper(path, &code);
    printf("%-18s rc=%2d code=%d\n", path, rc, code);
}

int main(void)
{
    try_one("/tmp/sleep60.sh");
    try_one("/usr/bin/true");
    try_one("/usr/bin/false");
    try_one("/usr/bin/nope");
    try_one("/tmp/exit7.sh");
    try_one("/tmp/killme.sh");
    try_one("/tmp/noisy.sh");
    try_one("/tmp/fds.sh");
    return 0;
}
