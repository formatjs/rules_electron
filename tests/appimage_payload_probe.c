#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv) {
    const char *image = getenv("APPIMAGE");
    const char *directory = getenv("APPDIR");
    if (!image || !directory || argc != 2 || strcmp(argv[1], "payload-check")) {
        return 31;
    }
    puts("APPIMAGE_PAYLOAD_OK");
    return 0;
}
