"""Verify the application's native dark appearance on macOS."""
import ctypes
import tkinter as tk

from stereofine.titlebar import install_tk_titlebars


def appearance_name():
    objc = ctypes.CDLL("/usr/lib/libobjc.A.dylib")
    pointer = ctypes.c_void_p
    objc.objc_getClass.argtypes = (ctypes.c_char_p,)
    objc.objc_getClass.restype = pointer
    objc.sel_registerName.argtypes = (ctypes.c_char_p,)
    objc.sel_registerName.restype = pointer
    send = ctypes.CFUNCTYPE(pointer, pointer, pointer)(("objc_msgSend", objc))
    send_string = ctypes.CFUNCTYPE(ctypes.c_char_p, pointer, pointer)(("objc_msgSend", objc))
    select = objc.sel_registerName
    application = send(objc.objc_getClass(b"NSApplication"), select(b"sharedApplication"))
    appearance = send(application, select(b"appearance"))
    assert appearance, "Missing per-app appearance"
    name = send(appearance, select(b"name"))
    return send_string(name, select(b"UTF8String")).decode("utf-8")


def main():
    root = tk.Tk()
    try:
        root.withdraw()
        install_tk_titlebars(root)
        root.update_idletasks()
        name = appearance_name()
        assert name == "NSAppearanceNameDarkAqua", name
        print("AppKit accepted the app-specific Dark Aqua appearance.")
    finally:
        root.destroy()


if __name__ == "__main__":
    main()
