"""Observe actual Tk pixels and image rectangles throughout saves and held pans."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import platform
import statistics
import tempfile
import threading
import time
from unittest.mock import patch

import customtkinter as ctk
from PIL import Image, ImageTk

from stereofine import gui
from stereofine.session import browse_source
from stereofine.settings import AppSettings
from stereofine.worker import JobCancelled
from tests.gui_cross_measurement import pump
from tests.gui_tiff_detail import native_ready
from tests.test_restart_alignment import RestartAlignmentTests


def displayed(app):
    image = app._preview_ctk_image
    size = image._get_scaled_size(app.preview_label._get_widget_scaling())
    photo = (image._scaled_dark_photo_images.get(size)
             or image._scaled_light_photo_images.get(size))
    assert photo is not None, 'The image has not reached Tk'
    return photo, size


def image_rectangle(app):
    _, (w, h) = displayed(app)
    label = app.preview_label._label
    return (label.winfo_rootx()+(label.winfo_width()-w)//2,
            label.winfo_rooty()+(label.winfo_height()-h)//2, w, h)


class ViewObserver:
    def __init__(self, app):
        self.app = app
        self.before = self.raster()
        self.rectangle = image_rectangle(app)
        self.last_photo = None
        self.frames = 0
        self.samples = 0
        self.changes = []
        self.draw = app._update_preview_display
        self.detail = app._show_detail_preview

    def raster(self):
        photo, size = displayed(self.app)
        pixels = ImageTk.getimage(photo).convert('RGB')
        return size, hashlib.sha256(pixels.tobytes()).hexdigest()

    def frame(self, origin):
        photo, _ = displayed(self.app)
        if photo is not self.last_photo:
            self.last_photo = photo
            self.frames += 1
            actual = self.raster()
            if actual != self.before:
                self.changes.append(dict(kind='raster', origin=origin, size=actual[0], digest=actual[1]))

    def sample(self):
        self.frame('event-loop')
        self.samples += 1
        rect = image_rectangle(self.app)
        if rect != self.rectangle:
            self.changes.append(dict(kind='image-rectangle', rectangle=rect))

    def __enter__(self):
        def draw(*args, **kwargs):
            self.draw(*args, **kwargs)
            self.frame('fit-draw')
        def detail(*args, **kwargs):
            self.detail(*args, **kwargs)
            self.frame('detail-draw')
        self.app._update_preview_display = draw
        self.app._show_detail_preview = detail
        return self

    def __exit__(self, *args):
        self.app._update_preview_display = self.draw
        self.app._show_detail_preview = self.detail


def save_case(app, root, name, timing, mode, tiff=False, detail=False):
    pump(app, lambda: native_ready(app))
    app.preview_mode.set(mode)
    app._on_preview_mode_changed()
    app.tiff_sbs.set(tiff)
    destination = root/name
    app._effective_output_folder = lambda _root: destination
    gate = threading.Event()
    native_start = app._native_worker.start
    export = gui.run_batch

    def delayed_native(function, **kwargs):
        def work(token, progress):
            assert gate.wait(30), 'Native render was never released'
            token.raise_if_cancelled()
            return function(token, progress)
        return native_start(work, **kwargs)

    def exporting(*args, **kwargs):
        if timing == 'during':
            gate.set()
            time.sleep(.5)
        if timing == 'cancel':
            token = kwargs['cancellation']
            while not token.cancelled:
                time.sleep(.01)
            token.raise_if_cancelled()
        if timing == 'error':
            raise OSError('Injected export failure')
        return export(*args, **kwargs)

    with patch.object(app._native_worker, 'start', side_effect=delayed_native), \
            patch.object(gui, 'run_batch', side_effect=exporting), \
            patch.object(gui.messagebox, 'showinfo'), patch.object(gui.messagebox, 'showerror'), \
            patch.object(gui.messagebox, 'showwarning'):
        try:
            if timing != 'ready':
                app._adjust_crop_zoom(1)
                app._start_native_preview()
                assert app._native_job_id is not None
            if detail:
                app._on_detail_press()
                pump(app, lambda: app.detail_active and app._detail_texture_cache is not None)
            app.update_idletasks()
            app._flush_state_save(explicit=True)
            state = deepcopy(app.current.state)
            with ViewObserver(app) as observer:
                app.save_current_result()
                assert app.busy_state == 'save'
                if timing == 'cancel':
                    app.after(50, app.cancel_current_job)
                idle_since = None
                deadline = time.monotonic()+45
                while time.monotonic() < deadline:
                    app.update()
                    observer.sample()
                    if app.busy_state == 'idle':
                        if idle_since is None:
                            idle_since = time.monotonic()
                            gate.set()
                        if app._native_job_id is None and time.monotonic()-idle_since > 1.4:
                            break
                    time.sleep(.008)
                else:
                    raise TimeoutError('Saving or the delayed native render did not finish')
            if timing not in ('cancel', 'error'):
                extension = 'tif' if tiff else 'jpg'
                assert (destination/'sbs'/f'{app.current.source.base_name}_sbs.{extension}').is_file()
            assert app.current.state.alignment == state.alignment
            assert app.current.state.framing == state.framing
            assert app.current.state.manual == state.manual
            assert app.current.state.floating_window == state.floating_window
            if detail:
                assert app.detail_active
            result = dict(case=name, timing=timing, mode=mode, tiff=tiff, detail=detail,
                sampled_actual_tk_frames=observer.frames, geometry_samples=observer.samples,
                changes=observer.changes[:20], actual_pixels_and_image_rectangle_unchanged=not observer.changes)
            print(json.dumps(result), flush=True)
            return result
        finally:
            gate.set()
            if app.detail_active:
                app._end_detail_preview()


def pan_checks(app):
    pump(app, lambda: native_ready(app))
    bounds = app._preview_bounds
    app._preview_bounds = lambda: (1000, 700)
    results = []
    try:
        app._request_native_preview(immediate=True)
        pump(app, lambda: native_ready(app))
        for mode in ('Farbig', 'Graustufen', 'Kreuzblick'):
            app.preview_mode.set(mode)
            app._on_preview_mode_changed()
            app._detail_center = (app._native_cache[1].shape[1]/2, app._native_cache[1].shape[0]/2)
            app._on_detail_press()
            pump(app, lambda: app._detail_texture_cache is not None
                 and app._detail_texture_cache[0] == app._detail_texture_signature())
            mixing_calls = []
            mixer = gui.make_anaglyph
            def forbidden(*args, **kwargs):
                mixing_calls.append(True)
                return mixer(*args, **kwargs)
            durations = []
            with patch('stereofine.native_preview.make_anaglyph', side_effect=forbidden):
                for _ in range(35):
                    started = time.perf_counter()
                    app._move_detail('right', 1)
                    app.update_idletasks()
                    durations.append((time.perf_counter()-started)*1000)
            app._end_detail_preview()
            app._on_measure_press()
            measure = []
            for _ in range(35):
                started = time.perf_counter()
                app._move_measure_cross('right', 1)
                app.update_idletasks()
                measure.append((time.perf_counter()-started)*1000)
            app._on_measure_release()
            app.update_idletasks()
            z_median = statistics.median(durations)
            m_median = statistics.median(measure)
            result = dict(mode=mode, z_median_ms=z_median, m_median_ms=m_median,
                z_p95_ms=sorted(durations)[int(len(durations)*.95)],
                no_anaglyph_calculation_during_pan=not mixing_calls,
                z_within_measurement_render_budget=z_median <= m_median*1.75+4)
            results.append(result)
            print(json.dumps(result), flush=True)
    finally:
        app._preview_bounds = bounds
        app._reset_keyboard_modes()
    return results


def main():
    checks = []
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = RestartAlignmentTests().source(root)
        for path in (source.left_path, source.right_path):
            with Image.open(path) as image:
                enlarged = image.resize((2160, 1440), Image.Resampling.BICUBIC)
            enlarged.save(path)
        gui.process_source(source)
        for language in ('de', 'en'):
            with patch.object(gui, 'load_settings', return_value=AppSettings(language=language)), \
                    patch.object(gui, 'save_settings'), patch.object(gui, 'play_ready_sound'):
                app = gui.StereoFineApp()
                try:
                    app.geometry('1400x900')
                    pump(app, lambda: app._preview_pil is not None)
                    app._set_source_collection([source], 0, batch=False)
                    pump(app, lambda: app.busy_state == 'idle' and app.current is not None)
                    pump(app, lambda: native_ready(app))
                    since = time.monotonic()
                    pump(app, lambda: time.monotonic()-since > .4)
                    saves = []
                    for case, timing, mode, tiff, detail in (
                        ('settled-jpeg', 'ready', 'Farbig', False, False),
                        ('native-during-tiff', 'during', 'Graustufen', True, False),
                        ('native-after-jpeg', 'after', 'Kreuzblick', False, False),
                        ('cancelled-save', 'cancel', 'Farbig', False, False),
                        ('failed-save', 'error', 'Farbig', False, False),
                        ('save-in-native-detail', 'ready', 'Farbig', False, True)):
                        print(f'Save view check: {language} {case}', flush=True)
                        saves.append(save_case(app, root/language, case, timing, mode, tiff, detail))
                    pans = pan_checks(app)
                    checks.append(dict(language=language, saves=saves, pans=pans))
                finally:
                    app.destroy()
    Path('build').mkdir(exist_ok=True)
    output = Path('build')/f'gui-save-detail-{platform.system()}.json'
    output.write_text(json.dumps(dict(checks=checks), indent=2)+'\n', encoding='utf-8')
    assert all(c['actual_pixels_and_image_rectangle_unchanged'] for l in checks for c in l['saves'])
    assert all(c['no_anaglyph_calculation_during_pan'] and c['z_within_measurement_render_budget']
               for l in checks for c in l['pans'])
    print('Actual save frames and native pan performance passed', flush=True)


if __name__ == '__main__':
    main()
