#define _GNU_SOURCE
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char **argv) {
    (void)argc;
    const char *exit_after_install = getenv("APPIMAGE_EXIT_AFTER_INSTALL");
    if (exit_after_install && strcmp(exit_after_install, "true") == 0) return 0;
    char directory[PATH_MAX], path[PATH_MAX], name[NAME_MAX + 2];
    const char *appdir = getenv("APPDIR");
    if (!appdir || !*appdir) {
        ssize_t size = readlink("/proc/self/exe", directory, sizeof(directory) - 1);
        if (size <= 0 || size >= (ssize_t)sizeof(directory) - 1) return 126;
        directory[size] = '\0';
        char *slash = strrchr(directory, '/');
        if (!slash) return 126;
        *slash = '\0';
        appdir = directory;
    }
    if (snprintf(path, sizeof(path), "%s/.electron-executable", appdir) >= (int)sizeof(path)) return 126;
    FILE *metadata = fopen(path, "r");
    if (!metadata) return 126;
    char *read = fgets(name, sizeof(name), metadata);
    int extra = fgetc(metadata);
    fclose(metadata);
    if (!read || extra != EOF) return 126;
    name[strcspn(name, "\n")] = '\0';
    if (!*name || !strcmp(name, ".") || !strcmp(name, "..") || strpbrk(name, "/\\\r")) return 126;
    if (snprintf(path, sizeof(path), "%s/%s", appdir, name) >= (int)sizeof(path)) return 126;
    argv[0] = path;
    execv(path, argv);
    int error = errno;
    perror("AppRun execv");
    return error == ENOENT ? 127 : 126;
}
