"""Resolve an installed MIME icon through GIO/GTK and decode its actual pixels."""

import ctypes as C
from pathlib import Path
import sys


def call(library, name, result, arguments):
    function = getattr(library, name)
    function.restype, function.argtypes = result, arguments
    return function


def main(mime_type, expected, size, gray):
    gtk, gio = C.CDLL("libgtk-3.so.0"), C.CDLL("libgio-2.0.so.0")
    pixels = C.CDLL("libgdk_pixbuf-2.0.so.0")
    objects = C.CDLL("libgobject-2.0.so.0")
    assert call(gtk, "gtk_init_check", C.c_int, [C.c_void_p, C.c_void_p])(None, None)
    icon = call(gio, "g_content_type_get_icon", C.c_void_p, [C.c_char_p])(mime_type.encode())
    theme = call(gtk, "gtk_icon_theme_get_default", C.c_void_p, [])()
    info = call(gtk, "gtk_icon_theme_lookup_by_gicon", C.c_void_p, [C.c_void_p, C.c_void_p, C.c_int, C.c_int])(theme, icon, size, 0)
    assert info
    image = None
    unref = call(objects, "g_object_unref", None, [C.c_void_p])
    try:
        filename = call(gtk, "gtk_icon_info_get_filename", C.c_char_p, [C.c_void_p])(info)
        assert filename and Path(filename.decode()).resolve() == expected.resolve()
        image = call(gtk, "gtk_icon_info_load_icon", C.c_void_p, [C.c_void_p, C.c_void_p])(info, None)
        assert image
        assert call(pixels, "gdk_pixbuf_get_width", C.c_int, [C.c_void_p])(image) == size
        assert call(pixels, "gdk_pixbuf_get_height", C.c_int, [C.c_void_p])(image) == size
        channels = call(pixels, "gdk_pixbuf_get_n_channels", C.c_int, [C.c_void_p])(image)
        data = call(pixels, "gdk_pixbuf_get_pixels", C.POINTER(C.c_ubyte), [C.c_void_p])(image)
        assert channels == 4 and list(data[:4]) == [gray, gray, gray, 255]
    finally:
        if image:
            unref(image)
        unref(info)
        unref(icon)
    print("DEB_MIME_ICON_OK")


if __name__ == "__main__":
    main(sys.argv[1], Path(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]))
