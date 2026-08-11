#include <errno.h>
#include <libgen.h>
#include <mach-o/dyld.h>
#include <Python.h>
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

static int run_python(const char *project_root) {
    char python_executable[4096];
    char virtual_env[4096];
    int n = snprintf(python_executable, sizeof(python_executable),
                     "%s/.venv/bin/python3", project_root);
    if (n < 0 || (size_t)n >= sizeof(python_executable)) {
        fprintf(stderr, "Python executable path is too long\n");
        return 6;
    }
    n = snprintf(virtual_env, sizeof(virtual_env),
                 "%s/.venv", project_root);
    if (n < 0 || (size_t)n >= sizeof(virtual_env)) {
        fprintf(stderr, "Virtual environment path is too long\n");
        return 6;
    }
    if (access(python_executable, X_OK) != 0) {
        fprintf(stderr, "%s is not executable: %s\n",
                python_executable, strerror(errno));
        return 6;
    }

    setenv("VIRTUAL_ENV", virtual_env, 1);

    PyConfig config;
    PyConfig_InitPythonConfig(&config);
    config.parse_argv = 1;

    PyStatus status = PyConfig_SetBytesString(
        &config, &config.program_name, python_executable);
    if (!PyStatus_Exception(status)) {
        char *python_argv[] = {python_executable, "main.py"};
        status = PyConfig_SetBytesArgv(&config, 2, python_argv);
    }
    if (!PyStatus_Exception(status)) {
        status = PyConfig_SetBytesString(
            &config, &config.run_filename, "main.py");
    }
    if (!PyStatus_Exception(status)) {
        status = Py_InitializeFromConfig(&config);
    }
    PyConfig_Clear(&config);

    if (PyStatus_Exception(status)) {
        fprintf(stderr, "Python initialization failed: %s\n",
                status.err_msg ? status.err_msg : "unknown error");
        return PyStatus_IsExit(status) ? status.exitcode : 6;
    }
    return Py_RunMain();
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
    if (chdir(project_root) != 0) {
        fprintf(stderr, "chdir failed: %s\n", strerror(errno));
        return 4;
    }

    return run_python(project_root);
}
