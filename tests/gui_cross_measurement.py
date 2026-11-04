"""Native GUI regression: independent outputs, three previews and crop refresh."""
from copy import deepcopy
import json
from pathlib import Path
import platform
import tempfile
import time

import customtkinter as ctk
from stereofine import gui
from stereofine.processing import ProcessingOptions, process_source
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
            gui.load_settings = lambda: AppSettings(language=language, gray_anaglyph=True, save_cross=True)
            saved = []
            gui.save_settings = lambda value: saved.append(value.to_dict())
            app = gui.StereoFineApp()
            try:
                pump(app, lambda: app._preview_pil is not None)
                app.current = browse_source(source)
                app.sources, app.source_index = [source], 0
                app._sync_vars_from_current()
                app._refresh_preview()
                app._refresh_control_states()
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
                app._on_measure_release()
                assert app._preview_pil.width == cross_width
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
                geometry = deepcopy(app.current.state.framing)
                pump(app, lambda: app.current.state.disparity.valid and not app.current.state.disparity.stale)
                assert app.current.state.framing == geometry
                assert app.current.state.disparity.basis['rendered_pair']
                assert saved[-1]['gray_anaglyph'] and saved[-1]['save_cross']
                checks.append(dict(language=language, automatic_crop_refresh=True, framing_preserved=True))
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
