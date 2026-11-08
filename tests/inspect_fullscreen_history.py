"""Compare released StereoFine versions on one Windows desktop."""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import sys
from threading import Event, Thread
from time import perf_counter, sleep

import numpy as np
from PIL import ImageChops, ImageGrab

sys.path.insert(0, str(Path(sys.argv[1]).resolve()))

from stereofine import gui
from stereofine.settings import AppSettings


def pump(app, seconds):
    deadline = perf_counter() + seconds
    while perf_counter() < deadline:
        app.update()
        sleep(.01)


def windows_theme(window):
    ancestor = ctypes.WinDLL("user32").GetAncestor
    ancestor.argtypes = (wintypes.HWND, wintypes.UINT)
    ancestor.restype = wintypes.HWND
    hwnd = ancestor(window.winfo_id(), 2)
    operation = ctypes.WinDLL("dwmapi").DwmGetWindowAttribute
    operation.argtypes = (wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD)
    operation.restype = ctypes.c_long
    for attribute in (20, 19):
        value = ctypes.c_int()
        if operation(hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)) == 0:
            return value.value
    raise AssertionError("No supported Windows titlebar theme attribute")


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
    for index, region in ((2, "title"), (3, "header")):
        result[region] = [{"ms": round(1000 * (frame[0] - start)), "white": round(frame[index], 4)}
                          for frame in frames]
        brightest = max(frames, key=lambda frame: frame[index])
        brightest[1].save(output / f"{name}-{region}-brightest.png")
    return result


def main():
    label = sys.argv[2]
    output = Path("build/fullscreen-history") / label
    output.mkdir(parents=True, exist_ok=True)
    gui.load_settings = lambda: AppSettings(language="de")
    gui.save_settings = lambda value: None
    app = gui.StereoFineApp()
    try:
        scale = app._get_window_scaling()
        width = int(app.winfo_screenwidth() / scale)
        height = int(app.winfo_screenheight() / scale)
        app.minsize(min(1100, width - 40), min(700, height - 40))
        app.maxsize(width * 2, height * 2)
        pump(app, .8)
        header = app.sidebar_header
        x, y = header.winfo_rootx(), header.winfo_rooty()
        title_height = min(24, y)
        assert title_height > 5
        box = (x, y - title_height, x + header.winfo_width(), y + header.winfo_height())
        ctypes.windll.user32.SetCursorPos(x + header.winfo_width() + 45, y + 180)
        before = capture(app, output, "startup-header")
        start_theme = windows_theme(app)
        results = []
        for index in range(2):
            app.toggle_fullscreen()
            pump(app, .5)
            assert app.fullscreen and app.attributes("-fullscreen")
            case = capture_transition(app, output, app.toggle_fullscreen, f"exit-{index}", box, title_height)
            assert not app.fullscreen and not app.attributes("-fullscreen")
            pump(app, .6)
            after = capture(app, output, f"exit-{index}-settled-header")
            case["header_restored"] = before.size == after.size and ImageChops.difference(before, after).getbbox() is None
            case["final_main_theme"] = windows_theme(app)
            results.append(case)
        app.show_shortcuts_help()
        help_window = app._shortcut_help_window
        pump(app, .6)
        assert help_window.winfo_viewable()
        help_theme = windows_theme(help_window)
        hx, hy = help_window.winfo_rootx(), help_window.winfo_rooty()
        help_strip = ImageGrab.grab(bbox=(hx, max(hy - 24, 0), hx + 300, hy)).convert("RGB")
        help_strip.save(output / "help-title.png")
        report = dict(version=label, startup_main_theme=start_theme, help_theme=help_theme, cases=results)
        (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(dict(version=label, startup_main_theme=start_theme, help_theme=help_theme,
                              cases=[dict(samples=a["samples"], header_restored=a["header_restored"],
                                          final_main_theme=a["final_main_theme"],
                                          max_title=max(f["white"] for f in a["title"] if f["ms"] >= 0),
                                          max_header=max(f["white"] for f in a["header"] if f["ms"] >= 0))
                                     for a in results])))
    finally:
        app.destroy()


if __name__ == "__main__":
    main()
