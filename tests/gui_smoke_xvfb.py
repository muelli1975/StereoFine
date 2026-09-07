from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageChops, ImageEnhance, ImageGrab, ImageStat

import stereofine.gui as gui
from stereofine.settings import AppSettings
from stereofine.sources import discover_stereo_file_sources, source_from_pair, source_from_stereo_file
from stereofine.processing import BatchProgress


def pump(app: gui.StereoFineApp, predicate, timeout: float = 45.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.update_idletasks()
        app.update()
        if predicate():
            return
        time.sleep(0.01)
    raise TimeoutError(f"GUI smoke timeout; busy={app.busy_state!r}, job={app.current_job_kind!r}")


def main() -> None:
    messages: list[tuple[str, str]] = []
    test_language = os.environ.get("STEREOFINE_TEST_LANGUAGE", "de").strip().lower() or "de"
    settings = AppSettings(
        language=test_language,
        use_input_output_subfolder=True,
        output_mode="both",
        analysis_method="AKAZE",
        color_match_enabled=False,
    )

    # Keep the live source tree untouched by GUI smoke-test preferences.
    gui.load_settings = lambda: settings
    gui.save_settings = lambda value: Path("/dev/null")
    gui.messagebox.showinfo = lambda _title, text: messages.append(("info", str(text)))
    gui.messagebox.showwarning = lambda _title, text: messages.append(("warning", str(text)))
    gui.messagebox.showerror = lambda _title, text: messages.append(("error", str(text)))
    gui.messagebox.askyesno = lambda *_args, **_kwargs: True

    with tempfile.TemporaryDirectory(prefix="stereofine_gui_smoke_") as td:
        root = Path(td)
        master = Image.open(gui.asset_path("stereofine.jpg")).convert("RGB")
        # Small enough for a quick real OpenCV/SGBM pass, still a genuine SBS image.
        target_w = 520
        target_h = max(2, round(master.height * target_w / master.width))
        small = master.resize((target_w, target_h), Image.Resampling.LANCZOS)
        small.save(root / "scene01.jpg", quality=95, subsampling=0)
        # Five real batch items are deliberate: the final handoff requires a
        # multi-image production path rather than a two-file navigation smoke.
        ImageEnhance.Brightness(small).enhance(0.97).save(root / "scene02.jpg", quality=95, subsampling=0)
        ImageEnhance.Contrast(small).enhance(0.96).save(root / "scene03.jpg", quality=95, subsampling=0)
        ImageEnhance.Color(small).enhance(0.94).save(root / "scene04.jpg", quality=95, subsampling=0)
        ImageEnhance.Sharpness(small).enhance(0.92).save(root / "scene05.jpg", quality=95, subsampling=0)

        sources = discover_stereo_file_sources(root)
        assert len(sources) == 5, sources

        # Build genuine MPO and suffix L/R inputs from the same stereo master
        # so the GUI loading path covers every mandatory input form.
        half_w = small.width // 2
        left_half = small.crop((0, 0, half_w, small.height))
        right_half = small.crop((small.width - half_w, 0, small.width, small.height))
        pair_root = root / "pair_input"
        pair_root.mkdir()
        left_path = pair_root / "sample_l.jpg"
        right_path = pair_root / "sample_r.jpg"
        left_half.save(left_path, quality=95, subsampling=0)
        right_half.save(right_path, quality=95, subsampling=0)
        pair_source = source_from_pair(left_path, right_path, pair_root)

        mpo_root = root / "mpo_input"
        mpo_root.mkdir()
        mpo_path = mpo_root / "sample.mpo"
        left_half.save(
            mpo_path, format="MPO", save_all=True, append_images=[right_half], quality=95, subsampling=0
        )
        mpo_source = source_from_stereo_file(mpo_path, mpo_root)

        app = gui.StereoFineApp()
        try:
            app.withdraw()

            # Mandatory single-input loading smoke: Full-SBS, MPO and L/R pair
            # all travel through the real asynchronous GUI load worker.
            for format_source, expected_kind in (
                (sources[0], "full_sbs"), (mpo_source, "mpo"), (pair_source, "pair")
            ):
                app._set_source_collection([format_source], 0, batch=False)
                pump(app, lambda: app.busy_state == "idle" and app.current is not None)
                assert app.current.source.kind == expected_kind
                assert app._preview_pil is not None

            app._set_source_collection(sources, 0, batch=True)
            pump(app, lambda: app.busy_state == "idle" and app.current is not None)
            assert app.batch_mode is True
            assert app.current is not None
            assert app.current.source.base_name == "scene01"

            # Viewing plus orientation-only edits must not create a fresh .sfin.
            assert not app.current.source.sidecar_path.exists()
            app.left_orientation.set("180")
            app.right_orientation.set("180")
            app.left_mirror.set(True)
            app.swap_eyes.set(True)
            app._on_input_transform_changed()
            app._flush_state_save()
            assert not app.current.source.sidecar_path.exists()

            # Camera-series orientation is session state: selecting another
            # image from the same folder (not only PageUp/PageDown) inherits it
            # when that target has no sidecar of its own.
            app._set_source_collection(sources, 1, batch=True)
            pump(app, lambda: app.busy_state == "idle" and app.current is not None and app.source_index == 1)
            assert app.left_orientation.get() == "180"
            assert app.right_orientation.get() == "180"
            assert app.left_mirror.get() is True
            assert app.swap_eyes.get() is True
            assert not app.current.source.sidecar_path.exists()

            # Page navigation has the same v41 inheritance semantics.
            app.previous_source()
            pump(app, lambda: app.busy_state == "idle" and app.current is not None and app.source_index == 0)
            assert app.left_orientation.get() == "180"
            assert app.right_orientation.get() == "180"
            assert app.left_mirror.get() is True
            assert app.swap_eyes.get() is True

            # The actual batch job must seed new/no-sidecar items with the same
            # camera-series transform. Non-geometric defaults still come from
            # global preferences rather than leaking from one image sidecar.
            batch_defaults = app._processing_options(use_batch_defaults=True).defaults
            assert batch_defaults.left_orientation == "180"
            assert batch_defaults.right_orientation == "180"
            assert batch_defaults.left_mirror is True
            assert batch_defaults.swap_eyes is True
            assert batch_defaults.aspect == app.settings.default_aspect
            assert batch_defaults.color_enabled == app.settings.color_match_enabled

            app.left_orientation.set("0")
            app.right_orientation.set("0")
            app.left_mirror.set(False)
            app.swap_eyes.set(False)
            app._on_input_transform_changed()
            app._flush_state_save()
            assert not app.current.source.sidecar_path.exists()

            # 1) Analysis-only through the real GUI -> worker -> batch -> report path.
            app.analysis_only.set(True)
            app.favorites_only.set(False)
            app._on_batch_mode_option_changed()
            observed_batch_progress = []
            original_handle_progress = app._handle_progress
            def recording_handle_progress(progress):
                if isinstance(progress, BatchProgress):
                    observed_batch_progress.append((progress.index, progress.total, progress.source_name, progress.stage))
                return original_handle_progress(progress)
            app._handle_progress = recording_handle_progress
            app.start_processing()
            pump(app, lambda: app.busy_state == "idle" and app.current is not None, timeout=120.0)
            app._handle_progress = original_handle_progress
            report = root / "stereofine_analysis.txt"
            assert report.is_file(), report
            report_text = report.read_text(encoding="utf-8")
            assert all(f"scene{i:02d}" in report_text for i in range(1, 6)), report_text
            assert not (root / "output").exists(), "analysis-only unexpectedly created image output"
            for i in range(1, 6):
                assert (root / "_stereofine" / f"scene{i:02d}.sfin").is_file()
            seen_indexes = {index for index, total, _name, _stage in observed_batch_progress if total == 5}
            assert seen_indexes == {1, 2, 3, 4, 5}, observed_batch_progress

            # Per-image sidecar values must not leak into global defaults for a
            # later source without a sidecar.
            app.settings.default_aspect = "16:9"
            app.settings.color_match_enabled = True
            app.settings.analysis_method = "SIFT"
            app._load_source_index(0)
            pump(app, lambda: app.busy_state == "idle" and app.current is not None and app.source_index == 0)
            assert app.output_aspect.get() == "maximum"  # from scene01 sidecar
            assert app.color_match_enabled.get() is False  # from scene01 sidecar
            assert app.analysis_method.get() == "SIFT"  # remains global processing preference
            scene02_sidecar_path = root / "_stereofine" / "scene02.sfin"
            scene02_sidecar_bytes = scene02_sidecar_path.read_bytes()
            scene02_sidecar_path.unlink()
            app._load_source_index(1)
            pump(app, lambda: app.busy_state == "idle" and app.current is not None and app.source_index == 1)
            assert app.current.state.framing.aspect == "16:9"
            assert app.current.state.color.enabled is True
            # Restore the previously analysed sidecar so the remaining GUI
            # smoke test exercises cache reuse instead of repeating OpenCV.
            scene02_sidecar_path.write_bytes(scene02_sidecar_bytes)
            app._load_source_index(0)
            pump(app, lambda: app.busy_state == "idle" and app.current is not None and app.source_index == 0)

            # Keep the remainder of this smoke test on the quick AKAZE/no-color
            # path; the default-leak assertions above already exercised the GUI.
            app.settings.analysis_method = "AKAZE"
            app.settings.default_aspect = "maximum"
            app.settings.color_match_enabled = False
            app.analysis_method.set("AKAZE")

            # Key-repeat regression: physical hold must toggle each mode only once.
            class _KeyEvent:
                state = 0

            key_event = _KeyEvent()

            original_preview_mode = app.preview_mode.get()
            app._on_a(key_event)
            first_preview_mode = app.preview_mode.get()
            assert first_preview_mode != original_preview_mode
            app._on_a(key_event)
            assert app.preview_mode.get() == first_preview_mode
            app._release_shortcut_key("a")
            app._on_a(key_event)
            assert app.preview_mode.get() == original_preview_mode
            app._release_shortcut_key("a")

            fw = app.current.state.floating_window
            floating_before = (
                fw.left_permille, fw.right_permille, fw.top_permille, fw.bottom_permille
            )
            coupling_before = bool(app.float_lr_symmetric.get())
            app._on_s(key_event)
            coupling_once = bool(app.float_lr_symmetric.get())
            assert coupling_once != coupling_before
            app._on_s(key_event)
            assert bool(app.float_lr_symmetric.get()) == coupling_once
            assert (fw.left_permille, fw.right_permille, fw.top_permille, fw.bottom_permille) == floating_before
            app._release_shortcut_key("s")
            app._on_s(key_event)
            assert bool(app.float_lr_symmetric.get()) == coupling_before
            assert (fw.left_permille, fw.right_permille, fw.top_permille, fw.bottom_permille) == floating_before
            app._release_shortcut_key("s")

            app._on_f1(key_event)
            app.update_idletasks(); app.update()
            help_window = app._shortcut_help_window
            assert help_window is not None and help_window.winfo_exists()
            app._on_f1(key_event)
            assert app._shortcut_help_window is help_window and help_window.winfo_exists()
            app._release_shortcut_key("f1")
            app._on_f1(key_event)
            assert app._shortcut_help_window is None
            app._release_shortcut_key("f1")

            # Ctrl+R must also be one physical action even when Windows repeats
            # the keypress. R shares a binding with the Floating Window, so its
            # release path is tested explicitly as well.
            class _CtrlKeyEvent:
                state = 0x0004

            ctrl_event = _CtrlKeyEvent()
            reset_calls = []
            original_reset = app.reset_manual_to_auto
            app.reset_manual_to_auto = lambda: reset_calls.append(1)
            app._on_ctrl_r(ctrl_event)
            app._on_ctrl_r(ctrl_event)
            assert len(reset_calls) == 1
            app._clear_floating_key("right")
            app._on_ctrl_r(ctrl_event)
            assert len(reset_calls) == 2
            app._clear_floating_key("right")
            app.reset_manual_to_auto = original_reset

            # Fullscreen button text follows the actual state and F11 is
            # repeat-safe.
            app._on_f11(key_event)
            assert app.fullscreen is True
            expected_windowed = "Fensteransicht" if test_language == "de" else "Windowed"
            expected_fullscreen = "Vollbild" if test_language == "de" else "Fullscreen"
            assert app.fullscreen_button.cget("text") == expected_windowed
            app._on_f11(key_event)
            assert app.fullscreen is True
            app._release_shortcut_key("f11")
            app._on_f11(key_event)
            assert app.fullscreen is False
            assert app.fullscreen_button.cget("text") == expected_fullscreen
            app._release_shortcut_key("f11")

            # Walk the complete G cycle with a physical release between presses.
            # After black rule-of-thirds the mode is Off, and the visible mode
            # controls make it immediately possible to reactivate the grid.
            app.grid_mode.set("Aus")
            app.grid_spacing.set("50 Promille")
            app._update_grid_control_state()
            cycle_states = []
            for _ in range(9):
                app._on_g(key_event)
                cycle_states.append((app.grid_mode.get(), app.grid_spacing.get()))
                app._on_g_release()
            assert cycle_states[-1] == ("Aus", "Drittel-Raster"), cycle_states
            assert app.grid_spacing_menu.cget("state") == "normal"

            # Shift+G only switches the overlay off; it must not overwrite a
            # spacing selected explicitly through the menu.
            app.grid_mode.set("Weiß")
            app.grid_spacing.set("100 Promille")
            app.grid_spacing_display.set(gui.grid_spacing_label("100 Promille", app.settings.language))
            shift_event = type("ShiftKey", (), {"state": 0x0001})()
            app._on_g(shift_event)
            app._on_g_release()
            assert app.grid_mode.get() == "Aus"
            assert app.grid_spacing.get() == "100 Promille"
            assert app.grid_spacing_menu.cget("state") == "normal"

            # Floating Window regression: every L/R/T/B keyboard path must
            # immediately change the rendered preview. Switching axis also
            # clears the competing mask just like v41; S remains coupling-only.
            app.float_lr_symmetric.set(False)
            fw.reset()
            app._refresh_preview()
            unmasked_preview = app._preview_pil.tobytes()
            for edge, attr in (("left", "left_permille"), ("right", "right_permille"), ("top", "top_permille"), ("bottom", "bottom_permille")):
                fw.reset()
                app._refresh_preview()
                app._set_floating_key(edge, key_event)
                for _ in range(10):
                    app._on_arrow("right", key_event)
                app._clear_floating_key(edge)
                assert getattr(fw, attr) == 10, (edge, fw)
                assert app._preview_pil.tobytes() != unmasked_preview, edge

            # Do not bypass Tk for the Windows-facing regression: send a real
            # L + Right key sequence through a focused child widget. The mask
            # must change both state and the final anaglyph image immediately.
            fw.reset()
            app._refresh_preview()
            event_before = app._preview_pil.copy()
            status_widgets_before = dict(app._status_line_widgets)
            help_footer_before = app.help_footer_label
            app.deiconify()
            app.update_idletasks(); app.update()
            px0 = app.preview_frame.winfo_rootx()
            py0 = app.preview_frame.winfo_rooty()
            px1 = px0 + app.preview_frame.winfo_width()
            py1 = py0 + app.preview_frame.winfo_height()
            screen_before = ImageGrab.grab().crop((px0, py0, px1, py1))
            app.save_button.focus_force()
            app.update_idletasks(); app.update()
            target = app.focus_get()
            assert target is not None
            target.event_generate("<KeyPress-l>")
            for _ in range(12):
                target.event_generate("<KeyPress-Right>")
                target.event_generate("<KeyRelease-Right>")
                app.update_idletasks(); app.update()
            target.event_generate("<KeyRelease-l>")
            app.update_idletasks(); app.update()
            assert fw.left_permille == 12, fw
            # v41 contract: the authoritative current preview pair itself is
            # masked; the anaglyph must not rely on a separate hidden late layer.
            assert app._preview_left_current is not None
            left_mask_px = max(1, round(app._preview_left_current.shape[1] * 0.012))
            assert int(app._preview_left_current[:, :left_mask_px].max()) == 0
            assert app._preview_pil.tobytes() != event_before.tobytes()
            # The final anaglyph edge itself must visibly change, not merely some
            # unrelated preview byte.
            before_arr = __import__("numpy").asarray(event_before)
            after_arr = __import__("numpy").asarray(app._preview_pil)
            edge_width = max(2, round(after_arr.shape[1] * 0.012))
            edge_delta = __import__("numpy").abs(
                after_arr[:, :edge_width].astype(__import__("numpy").int16)
                - before_arr[:, :edge_width].astype(__import__("numpy").int16)
            )
            assert float(edge_delta.mean()) > 2.0, float(edge_delta.mean())
            # The authoritative pair is already masked before the normal
            # StereoFine preview anaglyph is built. No second hidden mask layer.
            from stereofine.anaglyph import make_anaglyph
            expected_preview = make_anaglyph(
                app._preview_left_current,
                app._preview_right_current,
                gray=app.preview_mode.get() == "Graustufen",
            )
            assert __import__("numpy").array_equal(after_arr, expected_preview)
            screen_after_full = ImageGrab.grab()
            screen_after = screen_after_full.crop((px0, py0, px1, py1))
            screen_delta = ImageChops.difference(screen_before.convert("RGB"), screen_after.convert("RGB"))
            assert screen_delta.getbbox() is not None
            assert sum(ImageStat.Stat(screen_delta).mean) > 0.05, ImageStat.Stat(screen_delta).mean

            # More importantly, prove that the *displayed image edge* changes.
            # A status/layout redraw elsewhere in the window must not satisfy this.
            display_w, display_h = app._preview_display_size
            border = gui.preview_border_px(display_w)
            frame_w = app.preview_frame.winfo_width()
            frame_h = app.preview_frame.winfo_height()
            assert display_w + border * 2 <= frame_w, (display_w, border, frame_w)
            assert display_h + border * 2 <= frame_h, (display_h, border, frame_h)
            assert border >= round(display_w * 0.030) + 2
            label_x = app.preview_label.winfo_rootx()
            label_y = app.preview_label.winfo_rooty()
            image_x = label_x + max(0, (app.preview_label.winfo_width() - display_w) // 2)
            image_y = label_y + max(0, (app.preview_label.winfo_height() - display_h) // 2)
            visible_edge_w = max(3, round(display_w * 0.012))
            before_full = ImageGrab.grab()
            # Reconstruct the unmasked state, capture it, then restore 12‰ and capture again.
            fw.reset(); app._refresh_preview(); app.update_idletasks(); app.update()
            visible_before = ImageGrab.grab().crop((image_x, image_y, image_x + visible_edge_w, image_y + display_h))
            fw.left_permille = 12; app._refresh_preview(); app.update_idletasks(); app.update()
            visible_after = ImageGrab.grab().crop((image_x, image_y, image_x + visible_edge_w, image_y + display_h))
            visible_delta = ImageChops.difference(visible_before.convert("RGB"), visible_after.convert("RGB"))
            assert visible_delta.getbbox() is not None
            assert sum(ImageStat.Stat(visible_delta).mean) > 0.5, ImageStat.Stat(visible_delta).mean

            # Neither the immediate status refresh nor the debounced sidecar write
            # may destroy/recreate the status/F1 widgets (the Windows flicker bug).
            app._render_status()
            app._flush_state_save()
            app.update_idletasks(); app.update()
            assert app.help_footer_label is help_footer_before
            assert set(app._status_line_widgets) == set(status_widgets_before)
            assert all(app._status_line_widgets[name] is widget for name, widget in status_widgets_before.items())
            app.withdraw()
            app.update_idletasks(); app.update()

            # Explicitly reproduce the reported failure: an existing top mask
            # must not erase a new lateral mask during normalization.
            fw.reset()
            fw.top_permille = 10
            app._refresh_preview()
            top_preview = app._preview_pil.tobytes()
            app._set_floating_key("left", key_event)
            for _ in range(10):
                app._on_arrow("right", key_event)
            app._clear_floating_key("left")
            assert fw.left_permille == 10
            assert fw.top_permille == 0
            assert fw.bottom_permille == 0
            assert app._preview_pil.tobytes() != top_preview
            fw.reset()
            app._refresh_preview()
            app._flush_state_save()

            # 2) A browsed favorite persists and favorites-only exports exactly that source.
            assert app.current is not None
            if not app.current.state.favorite:
                app._on_favorite_clicked()
            assert app.current.state.favorite is True
            app.analysis_only.set(False)
            app.favorites_only.set(True)
            app._on_batch_mode_option_changed()
            app.start_processing()
            pump(app, lambda: app.busy_state == "idle" and app.current is not None, timeout=120.0)
            output = root / "output"
            sbs_files = sorted((output / "sbs").glob("*.jpg"))
            anaglyph_files = sorted((output / "anaglyph").glob("*.jpg"))
            assert [p.name for p in sbs_files] == ["scene01_sbs.jpg"], sbs_files
            assert [p.name for p in anaglyph_files] == ["scene01_anaglyph.jpg"], anaglyph_files

            # 3) App-level cancellation restores the idle/control state.
            def cancellable(token, _progress):
                for _ in range(500):
                    token.raise_if_cancelled()
                    time.sleep(0.002)
                return "unexpected"

            app._start_worker("analysis", "Justage läuft…", cancellable)
            pump(app, lambda: app.busy_state != "idle", timeout=2.0)
            expected_cancel = "Abbrechen" if test_language == "de" else "Cancel"
            assert app.start_button.cget("text") == expected_cancel
            assert app.start_button.cget("state") == "normal"
            assert app.start_button.cget("border_color") == gui.DANGER
            assert app.save_button.cget("state") == "disabled"
            # The same primary slot performs the cancellation.
            app._on_primary_action()
            assert app.start_button.cget("state") == "disabled"
            pump(app, lambda: app.busy_state == "idle", timeout=5.0)
            assert app.current_job_id is None
            assert app.start_button.cget("state") == "normal"
            expected_start = "Favoriten ausgeben" if test_language == "de" else "Export favorites"
            assert app.start_button.cget("text") == expected_start
            assert app.start_button.cget("border_color") == gui.GOLD_DARK

            # A normal Save completion must use only assets/ready.wav and must
            # not open a native Windows info box (which would add a second
            # system notification sound).
            saved_message_count = len(messages)
            ready_calls = []
            original_ready_sound = gui.play_ready_sound
            gui.play_ready_sound = lambda path: ready_calls.append(Path(path)) or True
            saved_source_index = app.source_index
            app.source_index = None  # avoid starting a reload worker in this focused completion test
            app.current_job_id = "synthetic-save"
            app.current_job_kind = "save"
            app.busy_state = "save"
            app._finish_worker_success(gui.BatchRunResult())
            assert ready_calls and ready_calls[-1].name == "ready.wav"
            assert len(messages) == saved_message_count, messages[saved_message_count:]
            expected_saved = "Gespeichert" if test_language == "de" else "Saved"
            assert app.save_button.cget("text") == expected_saved
            app.source_index = saved_source_index
            gui.play_ready_sound = original_ready_sound

            # Batch progress identity must advance even when a particular event
            # has no preview frame. This reproduces the real 33-image regression
            # where processing continued but status stayed on Vorschau 1/33.
            app.current_job_kind = "batch"
            app.busy_state = "batch"
            app._batch_progress_index = None
            app._batch_progress_total = None
            app._batch_progress_source_name = None
            app._handle_progress(BatchProgress(1, 33, "bild001", "analysis"))
            app.update_idletasks(); app.update()
            first_status = app._input_status_text()
            assert "1/33" in first_status and "bild001" in first_status, first_status
            app._handle_progress(BatchProgress(17, 33, "bild017", "analysis"))
            app.update_idletasks(); app.update()
            middle_status = app._input_status_text()
            assert "17/33" in middle_status and "bild017" in middle_status, middle_status
            app._handle_progress(BatchProgress(33, 33, "bild033", "export"))
            app.update_idletasks(); app.update()
            final_status = app._input_status_text()
            assert "33/33" in final_status and "bild033" in final_status, final_status
            app.current_job_kind = None
            app.busy_state = "idle"
            app._batch_progress_index = None
            app._batch_progress_total = None
            app._batch_progress_source_name = None

            # Successful analysis/batch completion must emit exactly one custom
            # ready.wav and no native info box/system chime.
            batch_message_count = len(messages)
            batch_ready_calls = []
            original_ready_sound = gui.play_ready_sound
            gui.play_ready_sound = lambda path: batch_ready_calls.append(Path(path)) or True
            saved_source_index = app.source_index
            saved_analysis_only = bool(app.analysis_only.get())
            saved_favorites_only = bool(app.favorites_only.get())
            app.source_index = None  # focused completion test; avoid async reload
            app.analysis_only.set(True)
            app.favorites_only.set(False)
            app.current_job_id = "synthetic-batch"
            app.current_job_kind = "batch"
            app.busy_state = "batch"
            app._finish_worker_success(gui.BatchRunResult(report_path=root / "stereofine_analysis.txt"))
            assert len(batch_ready_calls) == 1, batch_ready_calls
            assert batch_ready_calls[0].name == "ready.wav"
            assert len(messages) == batch_message_count, messages[batch_message_count:]
            app.source_index = saved_source_index
            app.analysis_only.set(saved_analysis_only)
            app.favorites_only.set(saved_favorites_only)
            gui.play_ready_sound = original_ready_sound

            # 4) Cancelling a source load is transactional. The source list,
            # index, batch flag and input-dialog memory must return to the
            # previously visible collection instead of leaving navigation and
            # preview out of sync.
            rollback_sources = list(app.sources)
            rollback_index = app.source_index
            rollback_batch = app.batch_mode
            rollback_input = str(app.settings.last_input_location or "")
            app._load_rollback_context = (
                rollback_sources, rollback_index, rollback_batch, rollback_input
            )
            app.sources = list(reversed(app.sources))
            app.source_index = 1 if len(app.sources) > 1 else 0
            app.batch_mode = not rollback_batch
            app.settings.last_input_location = str(root / "synthetic_cancelled_load")
            app.current_job_id = "synthetic-load"
            app.current_job_kind = "load"
            app.busy_state = "busy"
            app._finish_worker_cancelled()
            assert app.sources == rollback_sources
            assert app.source_index == rollback_index
            assert app.batch_mode == rollback_batch
            assert app.settings.last_input_location == rollback_input
            assert app.current is not None
            assert app.current.source == rollback_sources[rollback_index]

            # A cancelled batch must also restore the browsed image after a
            # temporary progress preview occupied the stage.
            app._refresh_preview()
            expected_preview = app._preview_pil.tobytes()
            app._preview_pil = Image.new("RGB", app._preview_pil.size, (1, 2, 3))
            assert app._preview_pil.tobytes() != expected_preview
            app.current_job_id = "synthetic-batch"
            app.current_job_kind = "batch"
            app.busy_state = "busy"
            app._finish_worker_cancelled()
            assert app._preview_pil.tobytes() == expected_preview

            errors = [text for kind, text in messages if kind == "error"]
            assert not errors, errors
            print(f"GUI smoke OK ({test_language})")
            print(f"report={report}")
            print(f"messages={messages}")
        finally:
            app.worker.cancel_all()
            app.destroy()


if __name__ == "__main__":
    main()
