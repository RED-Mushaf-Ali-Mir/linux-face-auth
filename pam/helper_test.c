#include <stdio.h>
#include <unistd.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <fcntl.h>
#include <errno.h>


static int run_helper (const char* path , int *exit_code) {

    pid_t pid = fork();
    if (pid < 0)
        return -1;
        
    if (pid == 0){
        int fd = open("/dev/null" , O_RDWR);
        
        if (fd < 0)
            _exit(127);
        if (dup2(fd , 0) < 0 || dup2(fd , 1 ) < 0 || dup2 (fd , 2) < 0)
            _exit(127);
        if (fd > 2){
            close(fd);
        }
        
        char *const argv[] = { (char *)path, NULL };
        char *const envp[] = { "PATH=/usr/bin:/bin", NULL };
        execve(path, argv, envp);
        
        _exit(127); // Process Write failed
    }
    
    int status;pid_t w;
    
    do{
    w = waitpid (pid , &status , 0);
    }while(w == -1 && errno == EINTR);
        
    if (w == -1)
        return -1;
    
    if  (WIFEXITED(status)){
        *exit_code = WEXITSTATUS(status);
        return 0;
    }    
    if (WIFSIGNALED(status))
        return -2;
        
    return -1;
}

static void try_one(const char *path)
{
    int code = -999;                        /* -999 = "run_helper never wrote it" */
    int rc = run_helper(path, &code);
    printf("%-18s rc=%2d code=%d\n", path, rc, code);
}

int main(void)
{
    try_one("/usr/bin/true");
    try_one("/usr/bin/false");
    try_one("/usr/bin/nope");
    try_one("/tmp/exit7.sh");
    try_one("/tmp/killme.sh");
    try_one("/tmp/noisy.sh");
    try_one("/tmp/fds.sh");
    return 0;
}
