"""Check compact status typography and capture the actual native widgets."""
from __future__ import annotations

import argparse
import base64
from copy import deepcopy
import json
import os
from pathlib import Path
import platform
import tempfile
import time
from unittest.mock import patch

import customtkinter as ctk
from PIL import Image, ImageGrab

from stereofine import gui
from stereofine.session import browse_source, source_from_selected_stereo_file
from stereofine.settings import AppSettings
from tests.gui_warning_xvfb import pump, geometry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--emit-preview', action='store_true')
    args = parser.parse_args()
    output = Path('build') / f'gui-status-{platform.system()}'
    output.mkdir(parents=True, exist_ok=True)
    checks = []
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'Nachtexpeditionen_2026_bild128_DxO.jpg'
        master = Image.open(gui.asset_path('stereofine.jpg')).convert('RGB')
        master.resize((1200, round(master.height*1200/master.width))).save(path)
        source = source_from_selected_stereo_file(path)
        session = browse_source(source)
        state = session.state
        state.alignment.valid = True
        state.alignment.method = 'AKAZE'
        state.alignment.model = 'Affine + Vergence + yQuad'
        state.alignment.vertical_error_mean_px = .182
        state.alignment.correction = dict(vertical_shift_px=-2.4, rotation_deg=.0625,
            trapez_apply=dict(enabled=True, max_relative_y_correction_px_fullres=2.4))
        base_correction = deepcopy(state.alignment.correction)
        state.disparity.valid = True
        state.disparity.stale = False
        state.disparity.total_permille = 30.
        state.disparity.low_edge_permille = -33.
        state.disparity.high_edge_permille = -3.
        state.framing.auto_near_base_width_px = 600
        state.framing.auto_near_offset_x_px = 0
        state.framing.auto_near_status = 'ok'
        state.disparity.traffic = 'green'
        for language in ('de', 'en'):
            ctk.set_widget_scaling(1.); ctk.set_window_scaling(1.)
            with patch.object(gui, 'load_settings', return_value=AppSettings(language=language)), \
                    patch.object(gui, 'save_settings'), patch.object(gui, 'play_ready_sound'):
                app = gui.StereoFineApp()
                try:
                    pump(app); pump(app)
                    app.sources = [source]
                    app.source_index = 0
                    app.current = session
                    app._sync_vars_from_current()
                    app._refresh_control_states()
                    app._refresh_preview()
                    for scale in (1., 1.25, 1.5, 2.):
                        ctk.set_widget_scaling(scale)
                        ctk.set_window_scaling(scale)
                        # CTk restores scaled min/max after one second. Wait
                        # for that before recording the explicit test geometry.
                        since = time.monotonic()
                        while time.monotonic()-since < 1.15:
                            app.update(); time.sleep(.01)
                        app.geometry('1100x700+0+0')
                        pump(app)
                        app._measurement_after_id = None
                        app._measurement_job_id = None
                        state.disparity.uncertain = False
                        app._render_status(); pump(app)
                        before = geometry(app)
                        right_edges = []
                        for name, value in app._status_line_widgets.items():
                            if name in app._status_caption_widgets:
                                right_edges.append(value.winfo_rootx()+value.winfo_width())
                        assert max(right_edges)-min(right_edges) <= 1, right_edges
                        for case in ('normal', 'warning', 'calculating', 'write-error', 'long-input', 'legacy-vergence'):
                            state.alignment.correction = deepcopy(base_correction)
                            if case == 'legacy-vergence':
                                state.alignment.correction = dict(vergence_ready=True,
                                    vergence_v_px=123.4, vergence_h_px=-234.5)
                            state.disparity.uncertain = case == 'warning'
                            app._measurement_job_id = 'fixture' if case == 'calculating' else None
                            app._state_save_error = 'fixture' if case == 'write-error' else None
                            app._render_status()
                            if case == 'long-input':
                                app._status_input_full_text = ('Input: '+('very_long_filename_'*30)+'.tif')
                                app._fit_status_input()
                            pump(app)
                            assert geometry(app) == before, (language, scale, case, before, geometry(app))
                            for name, label in {**app._status_line_widgets,
                                    **{'caption:'+k:v for k,v in app._status_caption_widgets.items()}}.items():
                                inner = label._label
                                assert inner.winfo_reqheight() <= label.winfo_height(), (
                                    language, scale, case, name, 'height', inner.winfo_reqheight(), label.winfo_height())
                                assert inner.winfo_reqwidth() <= label.winfo_width(), (
                                    language, scale, case, name, 'width', inner.winfo_reqwidth(), label.winfo_width())
                            if case == 'long-input':
                                assert '…' in app._status_line_widgets['input'].cget('text')
                                assert len(app._status_line_widgets['input'].cget('text').splitlines()) == 2
                            status_height = app.status_frame.winfo_height()/scale
                            assert status_height <= 282, status_height
                            scroll = (app.sidebar_container.winfo_height()-app.sidebar_header.winfo_height()
                                      -app.sidebar_bottom.winfo_height())
                            logical_height = app.winfo_height()/app._get_window_scaling()
                            if logical_height >= 699:
                                assert scroll >= 100*scale, (language, scale, scroll)
                            checks.append(dict(language=language, scale=scale, case=case,
                                status_logical_height=status_height, scroll_height=scroll,
                                window=[app.winfo_width(),app.winfo_height()], stable=True, text_fits=True))
                            if scale == 1. and language == 'de' and case in ('normal','warning','calculating'):
                                panel = app.sidebar_bottom
                                if platform.system() == 'Windows':
                                    # Print the actual application window,
                                    # including client pixels under a taskbar.
                                    import ctypes
                                    hwnd = ctypes.windll.user32.GetAncestor(app.winfo_id(), 2)
                                    rect = (ctypes.c_long*4)()
                                    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
                                    screen = ImageGrab.grab(window=hwnd)
                                    ox, oy = rect[0], rect[1]
                                else:
                                    screen = ImageGrab.grab(xdisplay=os.environ.get('DISPLAY'))
                                    ox, oy = 0, 0
                                box = (panel.winfo_rootx()-ox,panel.winfo_rooty()-oy,
                                       panel.winfo_rootx()-ox+panel.winfo_width(),panel.winfo_rooty()-oy+panel.winfo_height())
                                image_path = output / f'StereoFine_Status_{case}_{platform.system()}.png'
                                screen.crop(box).save(image_path)
                                if args.emit_preview:
                                    print('STATUS_IMAGE '+image_path.name+' '+base64.b64encode(image_path.read_bytes()).decode(), flush=True)
                        print(json.dumps(dict(language=language, scale=scale, cases=6, text_fits=True,
                            status_logical_height=status_height, scroll_height=scroll)), flush=True)
                    app._measurement_job_id = None
                    app._state_save_error = None
                finally:
                    app.destroy()
    ctk.set_widget_scaling(1.); ctk.set_window_scaling(1.)
    (output/'checks.json').write_text(json.dumps(checks, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
