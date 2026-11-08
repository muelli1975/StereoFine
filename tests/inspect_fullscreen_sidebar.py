"""Compare actual Windows sidebar pixels before and after fullscreen."""
import ctypes
import json
from pathlib import Path
from threading import Event, Thread
from time import perf_counter
from unittest.mock import patch
from ctypes import wintypes

import customtkinter as ctk
import numpy as np
from PIL import ImageChops, ImageGrab

from stereofine import gui
from stereofine.settings import AppSettings
from stereofine.theme import restore_dark_titlebar
from tests.gui_final_update import pump, windows_theme


def capture(app, output, name):
    header = app.sidebar_header
    x, y = header.winfo_rootx(), header.winfo_rooty()
    box = (x, y, x + header.winfo_width(), y + header.winfo_height())
    pixels = ImageGrab.grab(bbox=box).convert("RGB")
    pixels.save(output / f"{name}.png")
    return pixels


def capture_transition(app, output, action, name, box, title_height):
    stop, ready = Event(), Event()
    frames, errors, attributes = [], [], []

    def capture_frames():
        try:
            while not stop.is_set():
                started = perf_counter()
                pixels = ImageGrab.grab(bbox=box).convert("RGB")
                white = (np.asarray(pixels) >= 230).all(axis=2)
                frames.append((started, pixels, float(white[:title_height].mean()),
                               float(white[title_height:].mean())))
                ready.set()
                stop.wait(.010)
        except Exception as exc:
            errors.append(str(exc))
            ready.set()

    thread = Thread(target=capture_frames, daemon=True)
    thread.start()
    assert ready.wait(2), "Screen capture did not start"
    start = perf_counter()
    try:
        action()
        def sample_theme():
            try:
                attributes.append((round(1000 * (perf_counter() - start)), windows_theme(app)))
            except AssertionError:
                attributes.append((round(1000 * (perf_counter() - start)), None))
        sample_theme()
        for delay in (10, 25, 50, 80, 110, 150, 250):
            app.after(delay, sample_theme)
        pump(app, .45)
    finally:
        stop.set()
        thread.join(2)
    assert not errors and not thread.is_alive(), errors
    result = {"name": name, "samples": len(frames), "theme": attributes}
    capture(app, output, f"{name}-settled-header")
    for index, region in ((2, "title"), (3, "header")):
        result[region] = [{"ms": round(1000 * (frame[0] - start)), "white": round(frame[index], 4)}
                          for frame in frames]
        brightest = max(frames, key=lambda frame: frame[index])
        brightest[1].save(output / f"{name}-{region}-brightest.png")
    return result


def probe_flash(app, output):
    header = app.sidebar_header
    x, y = header.winfo_rootx(), header.winfo_rooty()
    title_height = min(24, y)
    assert title_height > 5
    box = (x, y - title_height, x + header.winfo_width(), y + header.winfo_height())

    user32 = ctypes.WinDLL("user32")
    ancestor = user32.GetAncestor
    ancestor.argtypes = (wintypes.HWND, wintypes.UINT)
    ancestor.restype = wintypes.HWND
    redraw = user32.RedrawWindow
    redraw.argtypes = (wintypes.HWND, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT)
    redraw.restype = wintypes.BOOL

    def exit_with_redraw(*, flush=False):
        app.toggle_fullscreen()
        restore_dark_titlebar(app)
        flags = 0x0001 | 0x0004 | 0x0080 | 0x0100 | 0x0400
        assert redraw(ancestor(app.winfo_id(), 2), None, None, flags)
        if flush:
            app.update_idletasks()

    def exit_without_preview_resize():
        with patch.object(app, "_update_preview_display"), patch.object(app, "_refresh_preview"):
            app.toggle_fullscreen()
            pump(app, .25)

    results = []
    for label, leave in (("baseline", app.toggle_fullscreen), ("redraw", exit_with_redraw),
                         ("redraw-and-idle", lambda: exit_with_redraw(flush=True)),
                         ("preview-paused", exit_without_preview_resize), ("repeat", app.toggle_fullscreen)):
        app.toggle_fullscreen()
        pump(app, .45)
        assert app.fullscreen
        results.append(capture_transition(app, output, leave, label + "-exit", box, title_height))
        assert not app.fullscreen
    return results


def main():
    output = Path("build/fullscreen-sidebar")
    output.mkdir(parents=True, exist_ok=True)
    gui.load_settings = lambda: AppSettings(language="de")
    gui.save_settings = lambda value: None
    app = gui.StereoFineApp()
    try:
        scale = app._get_window_scaling()
        width, height = (int(app.winfo_screenwidth() / scale), int(app.winfo_screenheight() / scale))
        app.minsize(min(1100, width - 40), min(700, height - 40))
        app.maxsize(width * 2, height * 2)
        pump(app, .8)
        flash = probe_flash(app, output)
        (output / "flash.json").write_text(json.dumps(flash, indent=2), encoding="utf-8")
        print(json.dumps([dict(name=item["name"], samples=item["samples"], theme=item["theme"],
                               max_title=max(frame["white"] for frame in item["title"]),
                               max_header=max(frame["white"] for frame in item["header"])) for item in flash]))
    finally:
        app.destroy()


if __name__ == "__main__":
    main()
