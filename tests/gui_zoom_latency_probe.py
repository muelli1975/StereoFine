"""Measure native and visible refresh for one arrow press on a 24 MP eye."""
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

import stereofine.gui as gui
import stereofine.native_preview as native
from stereofine.settings import AppSettings
from stereofine.sources import source_from_pair
from tests.gui_controls_13 import pump


def main():
    with TemporaryDirectory(prefix="stereofine-zoom-") as tmp:
        folder = Path(tmp)
        width, height = 6000, 4000
        rng = np.random.default_rng(313)
        coarse = rng.integers(0, 256, (560, 840, 3), np.uint8)
        left = cv2.resize(coarse, (width, height), interpolation=cv2.INTER_CUBIC)
        right = cv2.warpAffine(left, np.float32([[1, 0, 42], [0, 1, 0]]), (width, height),
                               borderMode=cv2.BORDER_REFLECT)
        for name, eye in (("scene_l.jpg", left), ("scene_r.jpg", right)):
            Image.fromarray(eye).save(folder / name, quality=94)
        del left, right
        source = source_from_pair(folder / "scene_l.jpg", folder / "scene_r.jpg", folder)
        timestamps = []

        def timed(name, call):
            def wrap(*args, **kwargs):
                start = perf_counter()
                try:
                    return call(*args, **kwargs)
                finally:
                    timestamps.append((name, perf_counter() - start))
            return wrap

        with patch.object(gui, "load_settings", return_value=AppSettings()), \
             patch.object(gui, "save_settings"), \
             patch.object(gui.StereoFineApp, "_load_start_image"), \
             patch.object(native, "prepare_native_preview", timed("native pair", native.prepare_native_preview)), \
             patch.object(native, "prepare_detail_texture", timed("detail view", native.prepare_detail_texture)):
            app = gui.StereoFineApp()
            try:
                app._set_source_collection([source], 0, batch=False)
                pump(app, lambda: app.current is not None and app.busy_state == "idle", timeout=120)
                app.deiconify()
                app.preview_frame.focus_force()
                pump(app, lambda: app.focus_get() is app.preview_frame)
                app._zoom_inspection(2)
                def ready():
                    return (app._inspection_view.active and app._detail_texture_cache is not None
                            and app._detail_texture_cache[0] == app._detail_texture_signature())
                pump(app, ready, timeout=120)
                times = []
                for key, step in (("Up", -1), ("Down", 1), ("Up", -1)):
                    offset = app.current.state.manual.delta_y_px
                    old_image = app._preview_ctk_image
                    timestamps.clear()
                    start = perf_counter()
                    app.preview_frame.event_generate(f"<KeyPress-{key}>")
                    changed = perf_counter()
                    app.preview_frame.event_generate(f"<KeyRelease-{key}>")
                    assert app.current.state.manual.delta_y_px == offset + step
                    pump(app, lambda: ready() and app._preview_ctk_image is not old_image, timeout=120)
                    elapsed = perf_counter() - start
                    times.append(elapsed)
                    print(f"Arrow to state {changed - start:.3f}s; arrow to pixels {elapsed:.3f}s; stages {timestamps}", flush=True)
                print(f"{width}x{height} per eye; median arrow to pixels {median(times):.3f}s", flush=True)
            finally:
                app.worker.cancel_all()
                app.measurement_worker.cancel_all()
                app.destroy()


if __name__ == "__main__":
    main()
