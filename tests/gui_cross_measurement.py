"""Native GUI regression: independent outputs, three previews and crop refresh."""
from copy import deepcopy
import json
from pathlib import Path
import platform
import tempfile
import time
from unittest.mock import patch

import customtkinter as ctk
from stereofine import gui
from stereofine.processing import BatchProgress, ProcessingOptions, process_source
from stereofine.session import browse_source
from stereofine.settings import AppSettings
from tests.test_restart_alignment import RestartAlignmentTests


def pump(app, predicate=lambda: True, timeout=30):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        app.update()
        if predicate():
            return
        time.sleep(.01)
    raise TimeoutError('GUI crop refresh timed out')


def main():
    checks = []
    with tempfile.TemporaryDirectory() as td:
        source = RestartAlignmentTests().source(Path(td))
        process_source(source)
        for language in ('de','en'):
            gui.load_settings = lambda: AppSettings.from_dict(dict(language=language, gray_anaglyph=True,
                save_cross=True, preview_mode='Kreuzblick'))
            saved = []
            gui.save_settings = lambda value: saved.append(value.to_dict())
            app = gui.StereoFineApp()
            try:
                pump(app, lambda: app._preview_pil is not None)
                assert app.preview_mode.get() == "Farbig"
                assert app._effective_preview_mode() == "Farbig"
                app._persist_settings()
                assert "preview_mode" not in saved[-1]
                app.current = browse_source(source)
                app.sources, app.source_index = [source], 0
                app._sync_vars_from_current()
                app._refresh_preview()
                app._refresh_control_states()
                assert app.current.state.disparity.basis['rendered_pair']
                # Browsing an older pre-framing sidecar must schedule the
                # final-crop refresh through the actual load/worker handoff.
                payload = json.loads(source.sidecar_path.read_text())
                for key in ('rendered_pair', 'offset_x_px', 'offset_y_px'):
                    payload['disparity']['basis'].pop(key, None)
                source.sidecar_path.write_text(json.dumps(payload))
                app._load_source_index(0)
                pump(app, lambda: app.busy_state == 'idle')
                preserved = deepcopy(app.current.state.framing)
                pump(app, lambda: app.current.state.disparity.valid and not app.current.state.disparity.stale)
                assert app.current.state.disparity.basis['rendered_pair']
                assert app.current.state.framing == preserved
                checks.append(dict(language=language, legacy_measurement_refreshed_on_browse=True,
                                   initial_measurement_after_framing=True))
                shape = app._preview_pair_shape
                for expected in ('Graustufen','Kreuzblick','Farbig'):
                    app._on_a()
                    app._release_shortcut_key('a')
                    self_mode = app.preview_mode.get()
                    assert self_mode == expected, (self_mode, expected)
                    assert app.gray_anaglyph.get() and app.save_cross.get()
                app.preview_mode.set('Graustufen'); app._on_preview_mode_changed()
                app.preview_mode.set('Kreuzblick'); app._on_preview_mode_changed()
                cross_width = app._preview_pil.width
                app._on_measure_press()
                assert app._effective_preview_mode() == 'Graustufen'
                assert app._preview_pil.width*2 == cross_width
                reticle = app.measure_cross_x, app.measure_cross_y
                app._on_measure_release()
                app.update_idletasks()
                assert app._preview_pil.width == cross_width
                app._on_measure_press()
                assert abs(app.measure_cross_x-reticle[0]) <= 1
                assert abs(app.measure_cross_y-reticle[1]) <= 1
                app._on_measure_release()
                app.update_idletasks()
                for scale in (1.,1.25,1.5):
                    ctk.set_widget_scaling(scale); ctk.set_window_scaling(scale)
                    app.geometry('1400x900')
                    ready = ctk.BooleanVar(value=False)
                    app.after(250, lambda: ready.set(True)); app.wait_variable(ready)
                    for radio in app._radio_widgets[:3]:
                        assert radio.winfo_x()+radio.winfo_width() <= radio.master.winfo_width()+2
                    checks.append(dict(language=language, scale=scale, preview='cross-view'))
                ctk.set_widget_scaling(1.); ctk.set_window_scaling(1.)
                app._adjust_crop_zoom(1)
                hint = 'Berechne …' if language == 'de' else 'Calculating …'
                label = app._status_line_widgets['near_far']
                assert label.cget('text') == hint
                geometry = deepcopy(app.current.state.framing)
                pump(app, lambda: app._measurement_job_id is not None)
                assert label.cget('text') == hint
                pump(app, lambda: app.current.state.disparity.valid and not app.current.state.disparity.stale)
                assert hint not in label.cget('text')
                assert app.current.state.framing == geometry
                assert app.current.state.disparity.basis['rendered_pair']
                assert saved[-1]['gray_anaglyph'] and saved[-1]['save_cross']
                measured = deepcopy(app.current.state.disparity)
                before_pixels = app._preview_pil.tobytes()
                app._adjust_manual_offset(10, 1)
                ready = ctk.BooleanVar(value=False)
                app.after(650, lambda: ready.set(True)); app.wait_variable(ready)
                assert app._measurement_after_id is None and app._measurement_job_id is None
                assert app.current.state.disparity == measured
                assert hint not in label.cget('text')
                assert app._preview_pil.tobytes() != before_pixels
                app._adjust_crop_zoom(-1)
                app.output_aspect.set('1:1')
                app._on_aspect_changed()
                pump(app, lambda: app.current.state.disparity.valid and not app.current.state.disparity.stale)
                small_step = app._framing_step_permille('x')
                assert 0 < small_step < 1000
                before_pixels = app._preview_pil.tobytes()
                old_pan = app.current.state.framing.pan_x_permille
                app._on_alt_arrow('right')
                assert app.current.state.framing.pan_x_permille == min(1000, old_pan + small_step)
                assert app._preview_pil.tobytes() != before_pixels
                pump(app, lambda: app.current.state.disparity.valid and not app.current.state.disparity.stale)
                before_pixels = app._preview_pil.tobytes()
                app._on_alt_arrow('down')
                assert app.current.state.framing.pan_y_permille == 0
                assert app._preview_pil.tobytes() == before_pixels
                assert app._measurement_after_id is None
                checks.append(dict(language=language, automatic_crop_refresh=True, framing_preserved=True,
                                   calculating_hint=True, color_preview_on_restart=True,
                                   manual_nudge_without_measurement=True, crop_pan_small_steps=True,
                                   unavailable_axis_keeps_pan=True))
                current_state = app.current.state
                snapshot = deepcopy(current_state)
                snapshot.disparity.total_permille = 21.
                snapshot.disparity.uncertain = True
                app.current_job_kind = 'batch'
                app._handle_progress(BatchProgress(2, 7, 'B.jpg', 'measured', state=snapshot))
                app._render_status()
                assert '21.00' in app._status_line_widgets['deviation'].cget('text')
                assert app._status_line_widgets['warning'].cget('text')
                app._handle_progress(BatchProgress(3, 7, 'C.jpg', 'analysis'))
                app._render_status()
                assert app._status_line_widgets['warning'].cget('text') == ''
                empty_endpoints = f"{app._t('status_near')}: – · {app._t('status_far')}: –"
                assert app._status_line_widgets['near_far'].cget('text') == empty_endpoints
                app.current_job_kind = None
                assert app.current.state is current_state
                app._render_status()
                checks.append(dict(language=language, batch_status_matches_progress_image=True))
                with patch('stereofine.processing.refresh_current_disparity', side_effect=RuntimeError('Test failure')):
                    app.current.state.invalidate_disparity_for_framing()
                    app._schedule_disparity_refresh()
                    assert label.cget('text') == hint
                    pump(app, lambda: app.current.state.disparity.status == 'error')
                    assert hint not in label.cget('text')
                app._schedule_disparity_refresh()
                assert label.cget('text') == hint
                app._start_worker('load', '', lambda token, progress: None)
                assert hint not in label.cget('text')
                pump(app, lambda: app.busy_state == 'idle')
                checks.append(dict(language=language, calculating_hint_cleared_on_error_and_cancel=True))
            finally:
                app._cancel_disparity_refresh()
                app.destroy()
        ctk.set_widget_scaling(1.); ctk.set_window_scaling(1.)
    output = Path('build')/('gui-cross-measurement-'+platform.system()+'.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dict(ok=True, checks=checks),indent=2),encoding='utf-8')
    print(output.read_text())


if __name__ == '__main__':
    main()
