"""Compare actual Windows sidebar pixels before and after fullscreen."""
import ctypes
import json
from pathlib import Path

import customtkinter as ctk
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
        print(json.dumps(report))
        assert all(scope.values()), scope
    finally:
        app.destroy()


if __name__ == "__main__":
    main()
