"""Native reticle pixel/performance and Windows fullscreen-theme checks."""
from __future__ import annotations

import json
from pathlib import Path
import statistics
import sys
import time
from unittest.mock import patch

from PIL import Image

import stereofine.gui as gui
from stereofine.preview import draw_measure_cross_overlay
from stereofine.settings import AppSettings
from stereofine.theme import restore_dark_titlebar


def pump(app, seconds=.3):
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        app.update()
        time.sleep(.01)


def windows_theme(app, *, set_light=False):
    import ctypes
    from ctypes import wintypes
    ancestor = ctypes.WinDLL('user32').GetAncestor
    ancestor.argtypes = (wintypes.HWND, wintypes.UINT)
    ancestor.restype = wintypes.HWND
    hwnd = ancestor(app.winfo_id(), 2)
    api = ctypes.WinDLL('dwmapi')
    operation = api.DwmSetWindowAttribute if set_light else api.DwmGetWindowAttribute
    operation.argtypes = (wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD)
    operation.restype = ctypes.c_long
    for attribute in (20, 19):
        value = ctypes.c_int(0)
        if operation(hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)) == 0:
            return value.value
    raise AssertionError('No supported Windows titlebar theme attribute')


def main():
    gui.load_settings = lambda: AppSettings()
    gui.save_settings = lambda value: None
    app = gui.StereoFineApp()
    report = dict(platform=sys.platform)
    try:
        pump(app, .5)
        source = Image.effect_noise((1600, 1000), 80).convert('RGB')
        app._preview_pil = source
        app.grid_mode.set('Aus')
        app._update_preview_display()
        size = app._preview_display_size
        app._on_measure_press()
        original_pixels = source.tobytes()
        with patch.object(source, 'resize', wraps=source.resize) as resize:
            for direction, pixels in [('left', 1.), ('right', 12.5), ('up', 10000.),
                                      ('left', 10000.), ('down', 10000.), ('right', 10000.)]:
                app._move_measure_cross(direction, pixels)
                expected = draw_measure_cross_overlay(source.resize(size, Image.Resampling.LANCZOS),
                                                       app.measure_cross_x, app.measure_cross_y)
                actual = app._preview_ctk_image.cget('light_image')
                assert actual.size == expected.size and actual.tobytes() == expected.tobytes()
            # Only the six explicit fresh reference frames were rescaled.
            assert resize.call_count == 6, resize.call_count
        assert source.tobytes() == original_pixels
        report['reticle_pixel_identity_and_cached_background'] = True
        # Measure the actual display path, including overlay and CTkImage upload.
        def measure():
            samples = []
            for _ in range(20):
                start = time.perf_counter()
                app._move_measure_cross('left', 1.)
                app.update_idletasks()
                samples.append((time.perf_counter()-start)*1000)
            return statistics.median(samples)
        measure()  # warm up Tk/image allocation
        cached = measure()
        def uncached(image, dimensions, sampling):
            return image.copy() if image.size == dimensions else image.resize(dimensions, sampling)
        with patch.object(app._preview_display_cache, 'scaled', side_effect=uncached):
            uncached_ms = measure()
        report.update(display_size=size, cached_frame_median_ms=cached,
                      previous_frame_median_ms=uncached_ms)
        app._on_measure_release()
        assert app._preview_ctk_image.cget('light_image').tobytes() == source.resize(size, Image.Resampling.LANCZOS).tobytes()

        def f11():
            app._release_shortcut_key('f11')
            app._on_f11()

        routes = [('button', app.fullscreen_button.invoke), ('f11', f11), ('escape', app._on_escape)]
        titlebar_checks = []
        for name, leave in routes:
            if sys.platform == 'win32':
                windows_theme(app, set_light=True)
                assert windows_theme(app) == 0
            app.fullscreen_button.invoke()
            pump(app)
            assert app.fullscreen
            leave()
            pump(app)
            assert not app.fullscreen and not app.attributes('-fullscreen')
            if sys.platform == 'win32':
                assert windows_theme(app) == 1, name
            titlebar_checks.append(name)
        # A scheduled restore must not pull a rapid re-entry out of fullscreen.
        app.toggle_fullscreen()
        app.toggle_fullscreen()
        app.toggle_fullscreen()
        pump(app)
        assert app.fullscreen
        if sys.platform == 'win32':
            assert app.attributes('-fullscreen')
        app._on_escape()
        pump(app)
        if sys.platform == 'win32':
            assert windows_theme(app) == 1
            for state in ('normal', 'zoomed'):
                app.state(state)
                pump(app)
                before = app.state()
                assert restore_dark_titlebar(app)
                assert app.state() == before
        report.update(fullscreen_exit_routes=titlebar_checks,
                      rapid_fullscreen_toggle=True,
                      windows_dark_titlebar_verified=sys.platform == 'win32', ok=True)
        target = Path('build/gui-final-update-'+sys.platform+'.json')
        target.parent.mkdir(exist_ok=True)
        target.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(report))
    finally:
        app.destroy()


if __name__ == '__main__':
    main()
