"""Render the full uncertainty hint without clipping or moving footer controls.

Run under a real display or Xvfb, independently of headless unit tests.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile
import time

import customtkinter as ctk
from PIL import Image, ImageGrab

import stereofine.gui as gui
from stereofine.session import browse_source, source_from_selected_stereo_file
from stereofine.settings import AppSettings


def pump(app):
    # Geometry changes are asynchronous under Tk/X11 as well as native WMs.
    for _ in range(5):
        app.update_idletasks()
        app.update()
        time.sleep(.02)


def geometry(app):
    return [(w.winfo_rootx(), w.winfo_rooty(), w.winfo_width(), w.winfo_height())
            for w in (app.status_frame, app.sidebar_bottom, app.start_button,
                      app.save_button, app.help_footer_label)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scale', type=float, default=1.)
    parser.add_argument('--screenshots', type=Path)
    args = parser.parse_args()
    ctk.set_widget_scaling(args.scale)
    ctk.set_window_scaling(args.scale)
    settings = AppSettings()
    gui.load_settings = lambda: settings
    gui.save_settings = lambda value: None
    with tempfile.TemporaryDirectory(prefix='sf-warning-layout-') as temporary:
        path = Path(temporary)/'scene.jpg'
        image = Image.open(gui.asset_path('stereofine.jpg')).convert('RGB')
        image.resize((1000, round(image.height*1000/image.width))).save(path)
        source = source_from_selected_stereo_file(path)
        session = browse_source(source)
        state = session.state
        state.disparity.valid = True
        state.disparity.stale = False
        state.disparity.total_permille = 30.
        state.disparity.low_edge_permille = -20.
        state.disparity.high_edge_permille = 10.
        state.disparity.traffic = 'gray'
        app = gui.StereoFineApp()
        try:
            # Finish startup centering before testing explicit window sizes.
            pump(app)
            pump(app)
            app.sources = [source]
            app.source_index = 0
            app.current = session
            app._sync_vars_from_current()
            app._refresh_control_states()
            app._refresh_preview()
            for language in ['de', 'en']:
                app._on_language_changed('Deutsch' if language == 'de' else 'English')
                for size in ['1100x700', '1400x850']:
                    app.geometry(size)
                    state.disparity.uncertain = False
                    app._render_status()
                    pump(app)
                    requested = [round(int(v)*args.scale) for v in size.split('x')]
                    assert [app.winfo_width(), app.winfo_height()] == requested, (size, args.scale, app.geometry(), requested)
                    before = geometry(app)
                    state.disparity.uncertain = True
                    app._render_status()
                    pump(app)
                    assert geometry(app) == before, (language, size, before, geometry(app))
                    warning = app._status_line_widgets['warning']
                    expected = ('⚠ Einschätzung unsicher – bitte mit M prüfen!' if language == 'de'
                                else '⚠ Estimate uncertain – please check with M!')
                    assert warning.cget('text') == expected
                    assert warning.cget('text_color') == gui.GOLD_LIGHT
                    assert warning.cget('font')[-1] == 'bold'
                    inner = warning._label
                    assert inner.winfo_reqwidth() <= warning.winfo_width(), (language, size, 'width')
                    assert inner.winfo_reqheight() <= warning.winfo_height(), (language, size, 'height')
                    assert warning.winfo_rooty()+warning.winfo_height() <= app._status_line_widgets['floating_title'].winfo_rooty()
                    assert app.activity_canvas.grid_info()['column'] == 1
                    assert app.traffic_label.grid_info()['column'] == 1
                    scroll_height = (app.sidebar_container.winfo_height()-app.sidebar_header.winfo_height()
                                     -app.sidebar_bottom.winfo_height())
                    assert scroll_height > 100*args.scale, (language, size, scroll_height)
                    assert app.help_footer_label.winfo_rooty()+app.help_footer_label.winfo_height() <= app.winfo_rooty()+app.winfo_height()
                    print(json.dumps(dict(language=language, size=size, scale=args.scale,
                        warning_size=[warning.winfo_width(), warning.winfo_height()],
                        window_size=[app.winfo_width(), app.winfo_height()],
                        required_size=[inner.winfo_reqwidth(), inner.winfo_reqheight()],
                        scroll_height=scroll_height, controls_stable=True)), flush=True)
                    if args.screenshots:
                        args.screenshots.mkdir(parents=True, exist_ok=True)
                        screenshot = ImageGrab.grab(xdisplay=os.environ.get('DISPLAY'))
                        box = (app.winfo_rootx(), app.winfo_rooty(),
                               app.winfo_rootx()+app.winfo_width(), app.winfo_rooty()+app.winfo_height())
                        screenshot.crop(box).save(args.screenshots/f'warning-{language}-{size}-{args.scale}.png')
                    state.disparity.stale = True
                    app._render_status()
                    pump(app)
                    assert warning.cget('text') == ''
                    # Hiding the separate traffic symbol can round its status
                    # row by one pixel at fractional scaling; footer controls
                    # and the reserved warning height must still stay fixed.
                    assert geometry(app)[-3:] == before[-3:]
                    assert warning.winfo_height() == round(32*args.scale)
                    state.disparity.stale = False
        finally:
            app.destroy()
    print('Uncertainty warning layout OK', flush=True)


if __name__ == '__main__':
    main()
