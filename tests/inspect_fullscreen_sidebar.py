"""Compare actual Windows sidebar pixels before and after fullscreen."""
import ctypes
import json
from pathlib import Path
from threading import Event, Thread
from time import perf_counter

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
                stop.wait(.003)
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


def probe_flash(app, output):
    header = app.sidebar_header
    x, y = header.winfo_rootx(), header.winfo_rooty()
    title_height = min(24, y)
    assert title_height > 5
    box = (x, y - title_height, x + header.winfo_width(), y + header.winfo_height())

    def exit_with_early_theme():
        app.toggle_fullscreen()
        restore_dark_titlebar(app)

    results = []
    for label, leave in (("baseline", app.toggle_fullscreen), ("early-theme", exit_with_early_theme),
                         ("baseline-repeat", app.toggle_fullscreen)):
        results.append(capture_transition(app, output, app.toggle_fullscreen,
                                          label + "-enter", box, title_height))
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
    results = []
    try:
        pump(app, .6)
        ctypes.windll.user32.SetCursorPos(app.winfo_rootx() + 600, app.winfo_rooty() + 220)

        def f11():
            app._release_shortcut_key("f11")
            app._on_f11()

        for scale in (1.0, 1.5):
            ctk.set_widget_scaling(scale)
            pump(app, .4)
            for state in ("normal", "zoomed"):
                app.state(state)
                pump(app, .4)
                for name, leave in (("button", app.fullscreen_button.invoke), ("f11", f11), ("escape", app._on_escape)):
                    label = f"{scale}-{state}-{name}"
                    before = capture(app, output, f"{label}-before")
                    app.fullscreen_button.invoke()
                    pump(app, .4)
                    assert app.fullscreen and app.attributes("-fullscreen")
                    leave()
                    pump(app, .4)
                    assert not app.fullscreen and not app.attributes("-fullscreen")
                    after = capture(app, output, f"{label}-after")
                    results.append({
                        "case": label, "state": app.state(),
                        "header_visible": before.getpixel((3, 3)) == (24, 24, 24)
                        and any(red > 150 for red, _, _ in before.getdata()),
                        "header_equal": before.size == after.size
                        and ImageChops.difference(before, after).getbbox() is None,
                        "dark_main_titlebar": windows_theme(app) == 1,
                    })
        app.state("normal")
        ctk.set_widget_scaling(1.0)
        pump(app, .4)
        windows_theme(app, set_light=True)
        assert windows_theme(app) == 0
        app.show_shortcuts_help()
        help_window = app._shortcut_help_window
        pump(app, .5)
        assert help_window.winfo_viewable() and help_window._reveal_job is None
        scope = dict(help_dark=windows_theme(help_window) == 1, main_still_light=windows_theme(app) == 0)
        app._close_shortcuts_help()
        pump(app, .3)
        restore_dark_titlebar(app)
        pump(app, .3)
        before = capture(app, output, "after-help-before-fullscreen")
        app.fullscreen_button.invoke()
        pump(app, .4)
        f11()
        pump(app, .4)
        after = capture(app, output, "after-help-after-fullscreen")
        report = dict(cases=results, theme_scope=scope,
                      after_help_pixels_equal=before.size == after.size
                      and ImageChops.difference(before, after).getbbox() is None)
        (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        flash = probe_flash(app, output)
        (output / "flash.json").write_text(json.dumps(flash, indent=2), encoding="utf-8")
        print(json.dumps(report))
        print(json.dumps([dict(name=item["name"], samples=item["samples"], theme=item["theme"],
                               max_title=max(frame["white"] for frame in item["title"]),
                               max_header=max(frame["white"] for frame in item["header"])) for item in flash]))
        assert all(scope.values()), scope
    finally:
        app.destroy()


if __name__ == "__main__":
    main()
