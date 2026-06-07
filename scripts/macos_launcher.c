#include <errno.h>
#include <libgen.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static int read_project_root(const char *exe_path, char *out, size_t out_size) {
    char path[4096];
    strncpy(path, exe_path, sizeof(path) - 1);
    path[sizeof(path) - 1] = '\0';

    char *macos_dir = dirname(path);
    char resource_path[4096];
    snprintf(resource_path, sizeof(resource_path),
             "%s/../Resources/project-root.txt", macos_dir);

    FILE *f = fopen(resource_path, "r");
    if (!f) {
        return -1;
    }
    if (!fgets(out, (int)out_size, f)) {
        fclose(f);
        return -1;
    }
    fclose(f);

    size_t len = strlen(out);
    while (len > 0 && (out[len - 1] == '\n' || out[len - 1] == '\r')) {
        out[--len] = '\0';
    }
    return len > 0 ? 0 : -1;
}

int main(void) {
    char exe_path[4096];
    uint32_t size = sizeof(exe_path);
    if (_NSGetExecutablePath(exe_path, &size) != 0) {
        return 2;
    }

    char project_root[4096];
    if (read_project_root(exe_path, project_root, sizeof(project_root)) != 0) {
        return 3;
    }

    FILE *log = fopen("/tmp/doio-kb03-app.log", "a");
    if (log) {
        dup2(fileno(log), STDOUT_FILENO);
        dup2(fileno(log), STDERR_FILENO);
        setvbuf(stdout, NULL, _IOLBF, 0);
        setvbuf(stderr, NULL, _IOLBF, 0);
    }

    printf("=== launching DOIO KB03-01 from %s ===\n", project_root);
    setenv("PATH", "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin", 1);
    if (chdir(project_root) != 0) {
        fprintf(stderr, "chdir failed: %s\n", strerror(errno));
        return 4;
    }

    execl("/opt/homebrew/bin/uv", "uv", "run", "python", "main.py", NULL);
    fprintf(stderr, "exec uv failed: %s\n", strerror(errno));
    return 5;
}
