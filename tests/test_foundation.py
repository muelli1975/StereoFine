from __future__ import annotations

import json
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from stereofine.anaglyph import make_anaglyph
from stereofine.inputs import load_master_image, master_to_uint8
from stereofine.i18n import Translator
from stereofine.models import AnalysisRecord, FileStamp, SourceStamp
from stereofine.reports import write_analysis_report
from stereofine.settings import AppSettings, load_settings, save_settings
from stereofine.sidecar import (
    SidecarDocument,
    SidecarStatus,
    load_sidecar,
    save_sidecar,
    source_stamp_to_dict,
)
from stereofine.state import PairState
from stereofine.worker import JobCancelled, WorkerManager, WorkerMessageKind


def _import_gui_without_customtkinter_runtime():
    """Import gui.py for logic-only tests without requiring a display/CTk install."""
    module = types.ModuleType("customtkinter")
    module.CTk = type("CTk", (object,), {})
    sys.modules["customtkinter"] = module
    sys.modules.pop("stereofine.gui", None)
    import importlib
    return importlib.import_module("stereofine.gui")


class FoundationTests(unittest.TestCase):
    def test_anaglyph_is_deterministic_uint8(self):
        left = np.zeros((4, 5, 3), dtype=np.uint8)
        right = np.zeros((4, 5, 3), dtype=np.uint8)
        left[..., 0] = 128
        right[..., 1] = 200
        a = make_anaglyph(left, right)
        b = make_anaglyph(left, right)
        self.assertEqual(a.dtype, np.uint8)
        self.assertEqual(a.shape, left.shape)
        self.assertTrue(np.array_equal(a, b))

    def test_uint16_png_master_is_not_reduced_on_load(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "sixteen.png"
            rgb = np.zeros((7, 9, 3), dtype=np.uint16)
            rgb[..., 0] = 1000
            rgb[..., 1] = 30000
            rgb[..., 2] = 65000
            bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            self.assertTrue(cv2.imwrite(str(path), bgr))
            loaded = load_master_image(path)
            self.assertEqual(loaded.dtype, np.uint16)
            self.assertEqual(loaded.shape, rgb.shape)
            self.assertTrue(np.array_equal(loaded, rgb))
            proxy = master_to_uint8(loaded)
            self.assertEqual(proxy.dtype, np.uint8)
            self.assertEqual(proxy.shape, rgb.shape)


    def test_uint16_tiff_master_is_not_reduced_on_load(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "sixteen.tif"
            rgb = np.zeros((8, 11, 3), dtype=np.uint16)
            rgb[..., 0] = 4321
            rgb[..., 1] = 32768
            rgb[..., 2] = 61234
            bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            self.assertTrue(cv2.imwrite(str(path), bgr))
            loaded = load_master_image(path)
            self.assertEqual(loaded.dtype, np.uint16)
            self.assertEqual(loaded.shape, rgb.shape)
            self.assertTrue(np.array_equal(loaded, rgb))


    def test_exif_orientation_matches_pillow_reference(self):
        from PIL import Image, ImageOps
        base = np.zeros((3, 5, 3), dtype=np.uint8)
        for y in range(3):
            for x in range(5):
                base[y, x] = [(x * 40 + 10) % 256, (y * 70 + 20) % 256, ((x + y) * 30 + 30) % 256]
        with tempfile.TemporaryDirectory() as td:
            for orientation in range(1, 9):
                path = Path(td) / f"o{orientation}.jpg"
                image = Image.fromarray(base, "RGB")
                exif = Image.Exif()
                exif[274] = orientation
                image.save(path, quality=100, subsampling=0, exif=exif)
                with Image.open(path) as opened:
                    expected = np.asarray(ImageOps.exif_transpose(opened).convert("RGB")).copy()
                loaded = load_master_image(path)
                self.assertTrue(np.array_equal(loaded, expected), f"EXIF orientation {orientation}")

    def test_settings_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "settings.json"
            settings = AppSettings(custom_output_folder="D:/Stereo", output_mode="sbs")
            save_settings(settings, path)
            loaded = load_settings(path)
            self.assertEqual(loaded.custom_output_folder, "D:/Stereo")
            # Short-lived development builds exposed this setting; 1.0 always
            # writes the established SBS + anaglyph pair.
            self.assertEqual(loaded.output_mode, "both")
            self.assertFalse(hasattr(loaded, "analysis_only"))
            self.assertFalse(hasattr(loaded, "favorites_only"))

    def test_sidecar_v3_roundtrip_and_source_validation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            left = root / "a_l.jpg"
            right = root / "a_r.jpg"
            left.write_bytes(b"left")
            right.write_bytes(b"right")
            source = SourceStamp(
                kind="pair",
                left=FileStamp.from_path(left, relative_to=root, width=100, height=50),
                right=FileStamp.from_path(right, relative_to=root, width=100, height=50),
            )
            state = PairState(favorite=True)
            doc = state.to_sidecar(source=source_stamp_to_dict(source))
            path = root / "_stereofine" / "a.sfin"
            save_sidecar(path, doc)
            result = load_sidecar(path, expected_source=source)
            self.assertEqual(result.status, SidecarStatus.VALID)
            self.assertTrue(result.document.favorite)

            right.write_bytes(b"right changed")
            changed_source = SourceStamp(
                kind="pair",
                left=FileStamp.from_path(left, relative_to=root, width=100, height=50),
                right=FileStamp.from_path(right, relative_to=root, width=100, height=50),
            )
            stale = load_sidecar(path, expected_source=changed_source)
            self.assertEqual(stale.status, SidecarStatus.STALE)

    def test_v2_migration_drops_obsolete_window_fields(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "legacy.sfin"
            path.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "favorite": True,
                        "window_position_percent": 80,
                        "window_back_permille": 7,
                        "manual_offset_x": 4,
                        "floating_left_permille": 3,
                    }
                ),
                encoding="utf-8",
            )
            result = load_sidecar(path)
            self.assertEqual(result.status, SidecarStatus.MIGRATED)
            data = result.document.to_dict()
            serialized = json.dumps(data)
            self.assertNotIn("window_position_percent", serialized)
            self.assertNotIn("window_back_permille", serialized)
            self.assertTrue(result.document.favorite)

    def test_english_analysis_report_translates_presentation_only(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "analysis_en.txt"
            write_analysis_report(
                path,
                [
                    AnalysisRecord(
                        source_name="image001",
                        model="Affine + Vergence",
                        matches=100,
                        inliers=80,
                        vertical_error_mean_px=0.12,
                        near_permille=3.0,
                        far_permille=22.0,
                        total_permille=19.0,
                        traffic="grün",
                        favorite=True,
                        status="OK",
                        rotation_deg=0.0123,
                        vergence_applied_px=0.456,
                    )
                ],
                input_description="D:/Stereo",
                language="en",
            )
            text = path.read_text(encoding="utf-8")
            self.assertIn("Traffic light", text)
            self.assertIn("Total deviation", text)
            self.assertIn("Near point", text)
            self.assertIn("image001", text)
            self.assertIn("green", text)
            self.assertIn("0.456 px", text)
            self.assertIn("0.0123°", text)
            self.assertNotIn("Matches", text)
            self.assertNotIn("Favorite", text)
            self.assertNotIn("\t", text)

    def test_english_core_errors_are_translated_only_at_presentation_boundary(self):
        tr = Translator("en")
        self.assertEqual(
            tr.message("Zu wenige Merkmale für eine zuverlässige Analyse gefunden."),
            "Too few features found for a reliable analysis.",
        )
        self.assertEqual(
            tr.message("Nicht unterstütztes Bildformat: .heic"),
            "Unsupported image format: .heic",
        )
        self.assertEqual(
            tr.message("Seitenverhältnis geändert."),
            "Aspect ratio changed.",
        )
        # Unknown technical details must never be destroyed by translation.
        self.assertEqual(tr.message("OpenCV internal code 123"), "OpenCV internal code 123")

    def test_english_report_translates_core_error_notes(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "analysis_error_en.txt"
            write_analysis_report(
                path,
                [
                    AnalysisRecord(
                        source_name="bad01",
                        model=None,
                        matches=None,
                        inliers=None,
                        vertical_error_mean_px=None,
                        near_permille=None,
                        far_permille=None,
                        total_permille=None,
                        traffic="–",
                        favorite=False,
                        status="error",
                        notes="Zu wenige Merkmale für eine zuverlässige Analyse gefunden.",
                    )
                ],
                language="en",
            )
            text = path.read_text(encoding="utf-8")
            self.assertIn("Error: Too few features found for a reliable analysis.", text)
            self.assertNotIn("Zu wenige Merkmale", text)

    def test_analysis_report_is_compact_aligned_utf8_table(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "analysis.txt"
            write_analysis_report(
                path,
                [
                    AnalysisRecord(
                        source_name="bild001",
                        model="Affine + Vergence",
                        matches=100,
                        inliers=80,
                        vertical_error_mean_px=0.12,
                        near_permille=3.0,
                        far_permille=22.0,
                        total_permille=19.0,
                        traffic="grün",
                        favorite=True,
                        status="OK",
                        rotation_deg=-0.0042,
                        vergence_applied_px=0.381,
                        uncertain=True,
                    )
                ],
                input_description="D:/Stereo",
            )
            text = path.read_text(encoding="utf-8")
            self.assertIn("Datei", text)
            self.assertIn("Ampel", text)
            self.assertIn("Gesamtdeviation", text)
            self.assertIn("Nahpunkt", text)
            self.assertIn("Fernpunkt", text)
            self.assertIn("Mittlerer Höhenfehler", text)
            self.assertIn("Vergenz", text)
            self.assertNotIn("Vergenz (Trapezkorrektur)", text)
            self.assertIn("Rotation", text)
            self.assertIn("Anmerkung", text)
            self.assertIn("bild001", text)
            self.assertIn("19.00‰", text)
            self.assertIn("0.381 px", text)
            self.assertIn("-0.0042°", text)
            self.assertIn("Einschätzung unsicher – bitte prüfen!", text)
            self.assertNotIn("Modell", text)
            self.assertNotIn("Matches", text)
            self.assertNotIn("Inlier", text)
            self.assertNotIn("Favorit", text)
            self.assertNotIn("\t", text)

    def test_worker_cancel(self):
        manager = WorkerManager()

        def work(token, progress):
            for i in range(200):
                token.raise_if_cancelled()
                if i == 2:
                    progress(i)
                time.sleep(0.001)
            return 123

        job = manager.start(work)
        time.sleep(0.01)
        manager.cancel(job.job_id)
        kinds = []
        deadline = time.time() + 2.0
        while time.time() < deadline:
            try:
                msg = manager.messages.get(timeout=0.05)
            except Exception:
                continue
            if msg.job_id != job.job_id:
                continue
            kinds.append(msg.kind)
            if msg.kind in {WorkerMessageKind.CANCELLED, WorkerMessageKind.RESULT, WorkerMessageKind.ERROR}:
                break
        self.assertIn(WorkerMessageKind.CANCELLED, kinds)


class ColorTransferTests(unittest.TestCase):
    def _quantile_gap(self, left, right):
        qs = [5, 25, 50, 75, 95]
        gaps = []
        for c in range(3):
            lq = np.percentile(left[..., c], qs)
            rq = np.percentile(right[..., c], qs)
            gaps.extend(np.abs(lq - rq))
        return float(np.mean(gaps))

    def test_symmetric_color_transfer_reduces_distribution_gap_and_moves_both_eyes(self):
        from stereofine.color_transfer import symmetric_color_match
        x = np.linspace(0, 255, 256, dtype=np.uint8)
        base = np.tile(x[None, :, None], (32, 1, 3))
        left = base.copy()
        right = base.copy()
        left[..., 0] = np.clip(left[..., 0].astype(np.int16) + 22, 0, 255).astype(np.uint8)
        left[..., 1] = np.clip(left[..., 1].astype(np.float32) * 0.82, 0, 255).astype(np.uint8)
        right[..., 0] = np.clip(right[..., 0].astype(np.float32) * 0.78, 0, 255).astype(np.uint8)
        right[..., 2] = np.clip(right[..., 2].astype(np.int16) + 28, 0, 255).astype(np.uint8)
        before = self._quantile_gap(left, right)
        l2, r2, transfer = symmetric_color_match(left, right)
        after = self._quantile_gap(l2, r2)
        self.assertLess(after, before * 0.25)
        self.assertFalse(np.array_equal(l2, left))
        self.assertFalse(np.array_equal(r2, right))
        self.assertEqual(transfer.method, "symmetric_percentile_curve_v1")

    def test_symmetric_color_transfer_preserves_uint16(self):
        from stereofine.color_transfer import symmetric_color_match
        rng = np.random.default_rng(7)
        left = rng.integers(1000, 60000, size=(30, 40, 3), dtype=np.uint16)
        right = np.clip(left.astype(np.int32) + np.array([2000, -1500, 3000]), 0, 65535).astype(np.uint16)
        l2, r2, _ = symmetric_color_match(left, right)
        self.assertEqual(l2.dtype, np.uint16)
        self.assertEqual(r2.dtype, np.uint16)
        self.assertEqual(l2.shape, left.shape)
        self.assertEqual(r2.shape, right.shape)

    def test_symmetric_color_transfer_strength_zero_is_identity(self):
        from stereofine.color_transfer import fit_symmetric_color_transfer, apply_symmetric_color_transfer
        rng = np.random.default_rng(11)
        left = rng.integers(0, 256, size=(25, 31, 3), dtype=np.uint8)
        right = rng.integers(0, 256, size=(25, 31, 3), dtype=np.uint8)
        transfer = fit_symmetric_color_transfer(left, right)
        l2, r2 = apply_symmetric_color_transfer(left, right, transfer, strength=0.0)
        self.assertTrue(np.array_equal(l2, left))
        self.assertTrue(np.array_equal(r2, right))

    def test_symmetric_color_transfer_identical_pair_is_exact_identity(self):
        from stereofine.color_transfer import symmetric_color_match
        rng = np.random.default_rng(19)
        image = rng.integers(0, 256, size=(41, 53, 3), dtype=np.uint8)
        left, right, _transfer = symmetric_color_match(image, image.copy())
        self.assertTrue(np.array_equal(left, image))
        self.assertTrue(np.array_equal(right, image))


    def test_symmetric_color_transfer_camera_like_mismatch_converges_without_one_eye_as_reference(self):
        from stereofine.color_transfer import symmetric_color_match
        rng = np.random.default_rng(23)
        base = rng.integers(12, 244, size=(96, 128, 3), dtype=np.uint8)
        f = base.astype(np.float32) / 255.0
        left = np.clip(np.power(f, 0.94) * np.array([1.06, 1.00, 0.94], dtype=np.float32), 0.0, 1.0)
        right = np.clip(np.power(f, 1.06) * np.array([0.94, 1.00, 1.06], dtype=np.float32), 0.0, 1.0)
        left = np.rint(left * 255.0).astype(np.uint8)
        right = np.rint(right * 255.0).astype(np.uint8)

        before = float(np.mean(np.abs(left.astype(np.float32) - right.astype(np.float32))))
        l2, r2, _transfer = symmetric_color_match(left, right)
        after = float(np.mean(np.abs(l2.astype(np.float32) - r2.astype(np.float32))))

        self.assertLess(after, before * 0.15)
        self.assertFalse(np.array_equal(l2, left))
        self.assertFalse(np.array_equal(r2, right))

    def test_render_refits_color_when_geometric_basis_changes(self):
        from stereofine.inputs import LoadedStereoPair
        from stereofine.render import render_final_pair
        from stereofine.state import PairState
        rng = np.random.default_rng(29)
        base = rng.integers(10, 246, size=(80, 120, 3), dtype=np.uint8)
        left = base.copy()
        right = np.clip(base.astype(np.int16) + np.array([8, -5, 6]), 0, 255).astype(np.uint8)
        loaded = LoadedStereoPair(
            left=left, right=right, left_path=Path("left.png"), right_path=Path("right.png"),
            kind="pair", source_width=120, source_height=80,
            left_source_width=120, left_source_height=80, right_source_width=120, right_source_height=80,
        )
        state = PairState()
        state.color.enabled = True
        _l1, _r1, info1 = render_final_pair(loaded, state)
        self.assertTrue(info1.color_refit)
        basis1 = dict(state.color.basis)

        state.manual.delta_x_px = 2
        _l2, _r2, info2 = render_final_pair(loaded, state)
        self.assertTrue(info2.color_refit)
        self.assertNotEqual(state.color.basis, basis1)


    def test_final_render_preserves_uint16_until_explicit_export_conversion(self):
        from stereofine.inputs import LoadedStereoPair
        from stereofine.render import render_final_pair
        from stereofine.state import PairState
        rng = np.random.default_rng(31)
        left = rng.integers(1000, 64000, size=(72, 104, 3), dtype=np.uint16)
        right = np.clip(left.astype(np.int32) + np.array([1800, -1200, 2200]), 0, 65535).astype(np.uint16)
        loaded = LoadedStereoPair(
            left=left, right=right, left_path=Path("left.tif"), right_path=Path("right.tif"),
            kind="pair", source_width=104, source_height=72,
            left_source_width=104, left_source_height=72, right_source_width=104, right_source_height=72,
        )
        state = PairState()
        state.color.enabled = True
        state.floating_window.bottom_permille = 10
        l2, r2, info = render_final_pair(loaded, state)
        self.assertEqual(l2.dtype, np.uint16)
        self.assertEqual(r2.dtype, np.uint16)
        self.assertTrue(info.color_applied)


class GeometryResamplingTests(unittest.TestCase):
    def test_identity_correction_preserves_master_pixels_without_resampling(self):
        from stereofine.alignment import warp_pair_symmetric
        rng = np.random.default_rng(41)
        left = rng.integers(0, 256, size=(64, 96, 3), dtype=np.uint8)
        right = rng.integers(0, 256, size=(64, 96, 3), dtype=np.uint8)
        correction = {
            "rotation_deg": 0.0,
            "scale": 1.0,
            "vertical_shift_px": 0.0,
            "vergence_ready": False,
        }
        l2, r2 = warp_pair_symmetric(left, right, correction)
        self.assertTrue(np.array_equal(l2, left))
        self.assertTrue(np.array_equal(r2, right))

    def test_combined_geometry_uses_one_image_resample_per_eye(self):
        from stereofine.alignment import warp_pair_symmetric
        rng = np.random.default_rng(43)
        left = rng.integers(0, 256, size=(96, 144, 3), dtype=np.uint8)
        right = rng.integers(0, 256, size=(96, 144, 3), dtype=np.uint8)
        correction = {
            "vertical_shift_px": 0.8,
            "rotation_deg": 0.04,
            "scale": 1.0007,
            "vergence_ready": True,
            "vergence_v_px": 0.7,
            "vergence_h_px": -0.3,
            "trapez_apply": {
                "enabled": True,
                "params": {"a_projective_x": 0.0012, "b_projective_y": -0.0008},
            },
            "y_residual_apply": {
                "enabled": True,
                "terms": ["constant", "x", "x2"],
                "coefficients": [
                    {"term": "constant", "coefficient_fullres_px": 0.12},
                    {"term": "x", "coefficient_fullres_px": -0.20},
                    {"term": "x2", "coefficient_fullres_px": 0.16},
                ],
                "normalization": {"x2_mean": 0.08, "y2_mean": 0.08},
                "max_abs_correction_px": 0.6,
            },
        }
        original_remap = cv2.remap
        calls = []

        def counted_remap(*args, **kwargs):
            calls.append(1)
            return original_remap(*args, **kwargs)

        cv2.remap = counted_remap
        try:
            l2, r2 = warp_pair_symmetric(left, right, correction)
        finally:
            cv2.remap = original_remap
        self.assertEqual(len(calls), 2)
        self.assertEqual(l2.shape, r2.shape)
        self.assertGreater(l2.shape[0], 80)
        self.assertGreater(l2.shape[1], 120)


class SidecarCompactnessTests(unittest.TestCase):
    def test_sidecar_keeps_reproducible_correction_but_drops_analysis_diagnostics(self):
        from stereofine.state import PairState
        state = PairState()
        state.alignment.valid = True
        state.alignment.correction = {
            "vertical_shift_px": 1.25,
            "rotation_deg": 0.02,
            "scale": 1.001,
            "zone3x3": {"huge": [1, 2, 3]},
            "pipeline_basis": {"candidate": "debug"},
            "trapez_apply": {
                "enabled": True,
                "params": {
                    "a_projective_x": 0.0002,
                    "b_projective_y": -0.0001,
                    "design_quality": {"condition": 12.0},
                },
                "metrics": {"holdout": {"mean": 0.1}},
                "max_relative_y_correction_px_fullres": 0.438,
            },
            "y_residual_apply": {
                "enabled": True,
                "model_name": "y_quad",
                "terms": ["constant", "x2"],
                "coefficients": [
                    {"term": "constant", "coefficient_fullres_px": 0.3, "debug": 99},
                    {"term": "x2", "coefficient_fullres_px": -0.2},
                ],
                "normalization": {"x2_mean": 0.08, "y2_mean": 0.09, "analysis_width": 3000},
                "max_abs_correction_px": 1.5,
                "source": "debug basis",
            },
        }
        state.disparity.diagnostics = {"low_components": [{"area": 999}], "debug": "large"}
        doc = state.to_sidecar(source={})
        correction = doc.alignment["correction"]
        self.assertEqual(set(correction), {"vertical_shift_px", "rotation_deg", "scale", "trapez_apply", "y_residual_apply"})
        self.assertEqual(set(correction["trapez_apply"]["params"]), {"a_projective_x", "b_projective_y"})
        self.assertAlmostEqual(correction["trapez_apply"]["max_relative_y_correction_px_fullres"], 0.438)
        self.assertNotIn("debug", correction["y_residual_apply"]["coefficients"][0])
        self.assertNotIn("diagnostics", doc.disparity)


    def test_sidecar_preserves_compact_vergence_status_measurements(self):
        from stereofine.state import PairState
        state = PairState()
        state.alignment.valid = True
        state.alignment.model = "Affine + Vergence"
        state.alignment.correction = {
            "vertical_shift_px": 0.4,
            "rotation_deg": 0.01,
            "scale": 1.0,
            # Compatibility placeholders in the current projective pipeline.
            "vergence_ready": False,
            "vergence_v_px": 0.0,
            "vergence_h_px": 0.0,
            "vergence_candidate_ready": True,
            "vergence_v_candidate_px": 0.4321,
            "vergence_h_candidate_px": -0.06789,
            "trapez_apply": {
                "enabled": True,
                "params": {"a_projective_x": 0.0002, "b_projective_y": -0.0001},
            },
        }
        correction = state.to_sidecar(source={}).alignment["correction"]
        self.assertNotIn("vergence_v_px", correction)
        self.assertNotIn("vergence_h_px", correction)
        self.assertTrue(correction["vergence_candidate_ready"])
        self.assertAlmostEqual(correction["vergence_v_candidate_px"], 0.4321)
        self.assertAlmostEqual(correction["vergence_h_candidate_px"], -0.06789)



    def test_new_sidecar_contains_no_localized_presentation_fields(self):
        state = PairState()
        state.alignment.valid = True
        state.alignment.model = "Affine"
        state.alignment.vertical_error_mean_px = 0.1
        state.alignment.correction = {"vertical_shift_px": 0.0, "rotation_deg": 0.0, "scale": 1.0}
        state.disparity.valid = True
        state.disparity.status = "uncertain"
        state.disparity.traffic = "gray"
        state.disparity.uncertain = True
        state.disparity.uncertain_reasons = ["low_edge_cluster_missing"]
        doc = state.to_sidecar(source={})
        payload = doc.to_dict()
        self.assertNotIn("traffic_label", payload["disparity"])
        self.assertNotIn("message", payload["disparity"])
        self.assertNotIn("auto_near_message", payload["framing"])
        self.assertNotIn("coverage_percent", payload["alignment"])
        self.assertNotIn("vertical_error_p95_px", payload["alignment"])
        self.assertEqual(payload["disparity"]["uncertain_reasons"], ["low_edge_cluster_missing"])
        self.assertEqual(payload["framing"]["aspect"], "maximum")
        self.assertEqual(payload["input_state"]["left_orientation"], "0")
        self.assertEqual(payload["input_state"]["right_orientation"], "0")

    def test_compact_sidecar_correction_renders_identically_to_full_runtime_payload(self):
        from stereofine.alignment import warp_pair_symmetric
        from stereofine.state import PairState
        rng = np.random.default_rng(37)
        left = rng.integers(0, 256, size=(90, 130, 3), dtype=np.uint8)
        right = rng.integers(0, 256, size=(90, 130, 3), dtype=np.uint8)
        state = PairState()
        state.alignment.valid = True
        state.alignment.correction = {
            "vertical_shift_px": 0.7,
            "rotation_deg": -0.03,
            "scale": 1.0008,
            "pipeline_basis": {"diagnostic": [1, 2, 3]},
            "trapez_apply": {
                "enabled": True,
                "params": {
                    "a_projective_x": 0.0007,
                    "b_projective_y": -0.0004,
                    "fit_method": "debug",
                },
                "metrics": {"ignored": True},
            },
            "y_residual_apply": {
                "enabled": True,
                "model_name": "y_quad",
                "terms": ["constant", "x", "x2"],
                "coefficients": [
                    {"term": "constant", "coefficient_fullres_px": 0.10, "debug": 1},
                    {"term": "x", "coefficient_fullres_px": -0.25},
                    {"term": "x2", "coefficient_fullres_px": 0.15},
                ],
                "normalization": {"x2_mean": 0.08, "y2_mean": 0.07, "analysis_width": 3000},
                "max_abs_correction_px": 0.5,
                "source": "runtime diagnostic",
            },
        }
        before_l, before_r = warp_pair_symmetric(left, right, state.alignment.correction)
        doc = state.to_sidecar(source={})
        restored = PairState.from_sidecar(doc)
        after_l, after_r = warp_pair_symmetric(left, right, restored.alignment.correction)
        self.assertTrue(np.array_equal(before_l, after_l))
        self.assertTrue(np.array_equal(before_r, after_r))


class SourceAndSidecarValidityTests(unittest.TestCase):
    def test_pipeline_change_does_not_discard_manual_sidecar_state(self):
        from stereofine.sidecar import SidecarDocument, load_sidecar, save_sidecar, SidecarStatus
        from stereofine.models import FileStamp, SourceStamp
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            left = root / "x_l.jpg"
            right = root / "x_r.jpg"
            left.write_bytes(b"l")
            right.write_bytes(b"r")
            stamp = SourceStamp(
                kind="pair",
                left=FileStamp.from_path(left, relative_to=root, width=10, height=10),
                right=FileStamp.from_path(right, relative_to=root, width=10, height=10),
            )
            doc = SidecarDocument(source=source_stamp_to_dict(stamp), favorite=True)
            doc.manual = {"offset_x_px": 12, "offset_y_px": -3}
            doc.pipeline["anaglyph"] = "old-anaglyph"
            path = root / "_stereofine" / "x.sfin"
            save_sidecar(path, doc)
            result = load_sidecar(path, stamp)
            self.assertEqual(result.status, SidecarStatus.VALID)
            self.assertIn("anaglyph", result.pipeline_mismatches)
            self.assertTrue(result.alignment_cache_valid)
            self.assertFalse(result.anaglyph_cache_valid)
            self.assertTrue(result.document.favorite)
            self.assertEqual(result.document.manual["offset_x_px"], 12)

    def test_alignment_pipeline_change_also_invalidates_fitted_color_cache(self):
        from stereofine.sidecar import SidecarDocument, SidecarStatus, SidecarLoadResult
        result = SidecarLoadResult(
            SidecarStatus.VALID,
            SidecarDocument(),
            pipeline_mismatches=("alignment",),
        )
        self.assertFalse(result.alignment_cache_valid)
        self.assertFalse(result.color_cache_valid)
        self.assertTrue(result.anaglyph_cache_valid)

    def test_discover_suffix_pair_source_and_sidecar_location(self):
        from stereofine.sources import discover_pair_sources
        from PIL import Image
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            arr = np.zeros((4, 5, 3), dtype=np.uint8)
            Image.fromarray(arr, "RGB").save(root / "scene_l.jpg")
            Image.fromarray(arr, "RGB").save(root / "scene_r.jpg")
            sources = discover_pair_sources(root)
            self.assertEqual(len(sources), 1)
            self.assertEqual(sources[0].base_name, "scene")
            self.assertEqual(sources[0].sidecar_path, root / "_stereofine" / "scene.sfin")


class InputFormatTests(unittest.TestCase):
    def test_real_two_frame_mpo_loads_left_and_right_frames(self):
        from PIL import Image
        from stereofine.inputs import load_mpo
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "stereo.mpo"
            left = np.zeros((24, 32, 3), dtype=np.uint8)
            right = np.zeros_like(left)
            left[..., 0] = 240
            right[..., 1] = 230
            Image.fromarray(left, "RGB").save(
                path,
                format="MPO",
                save_all=True,
                append_images=[Image.fromarray(right, "RGB")],
                quality=98,
                subsampling=0,
            )
            loaded = load_mpo(path)
            self.assertEqual(loaded.kind, "mpo")
            self.assertEqual(loaded.left.shape, (24, 32, 3))
            self.assertEqual(loaded.right.shape, (24, 32, 3))
            self.assertEqual(loaded.left.dtype, np.uint8)
            self.assertEqual(loaded.right.dtype, np.uint8)
            self.assertGreater(float(loaded.left[..., 0].mean()), 220.0)
            self.assertLess(float(loaded.left[..., 1].mean()), 20.0)
            self.assertGreater(float(loaded.right[..., 1].mean()), 210.0)
            self.assertLess(float(loaded.right[..., 0].mean()), 20.0)

    def test_full_sbs_odd_width_discards_only_center_remainder_pixel(self):
        from PIL import Image
        from stereofine.inputs import load_full_sbs
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "odd.png"
            image = np.zeros((10, 11, 3), dtype=np.uint8)
            image[:, :5, 0] = 255
            image[:, 5, 2] = 255
            image[:, 6:, 1] = 255
            Image.fromarray(image, "RGB").save(path)
            loaded = load_full_sbs(path)
            self.assertEqual(loaded.left.shape, (10, 5, 3))
            self.assertEqual(loaded.right.shape, (10, 5, 3))
            self.assertTrue(np.all(loaded.left[..., 0] == 255))
            self.assertTrue(np.all(loaded.right[..., 1] == 255))
            self.assertTrue(np.all(loaded.left[..., 2] == 0))
            self.assertTrue(np.all(loaded.right[..., 2] == 0))

    def test_heic_is_deliberately_not_an_official_input_format(self):
        from stereofine.inputs import InputError, load_master_image
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "phone.heic"
            path.write_bytes(b"not relevant")
            with self.assertRaisesRegex(InputError, "Nicht unterstütztes Bildformat"):
                load_master_image(path)


class GeometryStateConsistencyTests(unittest.TestCase):
    def test_extreme_manual_offset_is_clamped_not_silently_ignored(self):
        from stereofine.geometry import clamp_pair_offset, crop_shifted_pair_to_overlap
        left = np.zeros((10, 12, 3), dtype=np.uint8)
        right = np.zeros_like(left)
        ox, oy = clamp_pair_offset(left, right, 999, -999)
        self.assertEqual((ox, oy), (10, -8))
        l2, r2, changed = crop_shifted_pair_to_overlap(left, right, 999, -999)
        self.assertTrue(changed)
        self.assertEqual(l2.shape, (2, 2, 3))
        self.assertEqual(r2.shape, (2, 2, 3))


class AlignmentModelSelectionTests(unittest.TestCase):
    @staticmethod
    def _feature_image():
        rng = np.random.default_rng(123)
        h, w = 600, 900
        base = rng.integers(0, 256, (h, w, 3), dtype=np.uint8)
        base = cv2.GaussianBlur(base, (3, 3), 0)
        for _ in range(120):
            x = int(rng.integers(20, w - 20))
            y = int(rng.integers(20, h - 20))
            radius = int(rng.integers(3, 10))
            color = tuple(int(v) for v in rng.integers(0, 256, 3))
            cv2.circle(base, (x, y), radius, color, -1)
        return base

    def test_affine_only_pair_does_not_auto_promote_projective_model(self):
        from stereofine.alignment import analyze_pair_features
        base = self._feature_image()
        h, w = base.shape[:2]
        matrix = cv2.getRotationMatrix2D((w / 2, h / 2), 0.35, 1.0015)
        matrix[0, 2] += 18.0  # horizontal stereo disparity is not a fit target
        matrix[1, 2] += 2.2
        right = cv2.warpAffine(base, matrix, (w, h), borderMode=cv2.BORDER_REFLECT)
        result = analyze_pair_features(base, right, "AKAZE", 3000)
        self.assertEqual(result["model"], "Affine")
        self.assertFalse(result["correction"]["trapez_apply"]["enabled"])

    def test_true_projective_vertical_error_can_pass_holdout_gate(self):
        from stereofine.alignment import analyze_pair_features
        base = self._feature_image()
        h, w = base.shape[:2]
        src = np.float32([[0, 0], [w - 1, 0], [0, h - 1], [w - 1, h - 1]])
        dst = np.float32([[15, 3], [w - 1 + 15, -3], [15, h - 1 - 4], [w - 1 + 15, h - 1 + 4]])
        matrix = cv2.getPerspectiveTransform(src, dst)
        right = cv2.warpPerspective(base, matrix, (w, h), borderMode=cv2.BORDER_REFLECT)
        result = analyze_pair_features(base, right, "AKAZE", 3000)
        self.assertTrue(result["correction"]["trapez_apply"]["enabled"])
        self.assertIn("Vergence", result["model"])
        metrics = result["correction"]["trapez_apply"]["metrics"]
        self.assertTrue(metrics["holdout_better"])


class AutoFramingStateTests(unittest.TestCase):
    def test_auto_near_framing_places_near_point_at_least_three_permille_behind(self):
        from stereofine.framing import compute_auto_near_framing
        result = compute_auto_near_framing(
            high_edge_permille=12.4,
            base_width_px=3000,
            ready=True,
            back_permille=3.0,
        )
        self.assertTrue(result.available)
        self.assertLessEqual(result.near_after_permille, -3.0 + 1e-9)
        self.assertGreater(result.near_after_permille, -3.34)

    def test_ctrl_r_semantics_returns_to_auto_near_baseline(self):
        from stereofine.state import PairState
        state = PairState()
        state.framing.auto_near_offset_x_px = 45
        state.framing.auto_near_base_width_px = 3000
        state.disparity.low_edge_permille = -8.0
        state.disparity.high_edge_permille = 12.0
        state.disparity.total_permille = 20.0
        state.disparity.basis = {
            "aspect": "Maximal",
            "crop_zoom_index": 0,
            "pan_x_permille": 0,
            "pan_y_permille": 0,
        }
        state.disparity.valid = True
        state.disparity.stale = True
        state.manual.delta_x_px = 15
        state.manual.delta_y_px = -4
        state.framing.crop_zoom_index = 3
        state.framing.pan_x_permille = 12
        state.floating_window.left_permille = 7

        self.assertEqual(state.effective_offset_x_px, 60)
        state.reset_manual_to_auto()
        self.assertEqual(state.effective_offset_x_px, 45)
        self.assertEqual(state.manual.delta_x_px, 0)
        self.assertEqual(state.manual.delta_y_px, 0)
        self.assertEqual(state.framing.crop_zoom_index, 0)
        self.assertEqual(state.framing.pan_x_permille, 0)
        self.assertEqual(state.floating_window.left_permille, 0)
        near, far = state.current_scene_positions_permille()
        self.assertAlmostEqual(near, -3.0, places=6)
        self.assertAlmostEqual(far, 23.0, places=6)


    def test_ctrl_r_does_not_revalidate_disparity_after_aspect_change(self):
        from stereofine.state import PairState
        state = PairState()
        state.framing.auto_near_offset_x_px = 45
        state.framing.auto_near_base_width_px = 3000
        state.disparity.low_edge_permille = -8.0
        state.disparity.high_edge_permille = 12.0
        state.disparity.total_permille = 20.0
        state.disparity.basis = {
            "aspect": "Maximal",
            "crop_zoom_index": 0,
            "pan_x_permille": 0,
            "pan_y_permille": 0,
        }
        state.disparity.valid = False
        state.disparity.stale = True
        state.disparity.status = "stale"
        state.framing.aspect = "16:9"
        state.manual.delta_y_px = 4

        state.reset_manual_to_auto()

        self.assertEqual(state.manual.delta_y_px, 0)
        self.assertEqual(state.framing.aspect, "16:9")
        self.assertFalse(state.disparity.valid)
        self.assertTrue(state.disparity.stale)

    def test_floating_window_masks_do_not_change_deviation_or_scene_position(self):
        from stereofine.state import PairState
        state = PairState()
        state.framing.auto_near_offset_x_px = 45
        state.framing.auto_near_base_width_px = 3000
        state.disparity.low_edge_permille = -8.0
        state.disparity.high_edge_permille = 12.0
        state.disparity.total_permille = 20.0
        state.disparity.valid = True
        before = state.current_scene_positions_permille()
        total_before = state.disparity.total_permille

        state.floating_window.bottom_permille = 10
        state.floating_window.normalize()

        self.assertEqual(state.current_scene_positions_permille(), before)
        self.assertEqual(state.disparity.total_permille, total_before)
        self.assertTrue(state.disparity.valid)
        self.assertFalse(state.disparity.stale)

    def test_v2_migration_does_not_replay_legacy_geometry(self):
        from stereofine.sidecar import load_sidecar, SidecarStatus
        from stereofine.state import PairState
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "legacy.sfin"
            path.write_text(json.dumps({
                "version": 2,
                "left_orientation": "90° rechts",
                "right_orientation": "90° rechts",
                "left_mirror": True,
                "favorite": True,
                "manual_offset_x": 52,
                "manual_offset_y": -2,
                "near_framing": {"offset_x_px": 40, "base_width_px": 2000, "shift_permille": 20.0},
                "crop_zoom_index": 4,
                "crop_pan_x_permille": 500,
                "floating_bottom_permille": 10,
            }), encoding="utf-8")
            loaded = load_sidecar(path)
            self.assertEqual(loaded.status, SidecarStatus.MIGRATED)
            state = PairState.from_sidecar(loaded.document)
            # Geometry from legacy files is not safe to replay in 1.0.
            self.assertIsNone(state.framing.auto_near_offset_x_px)
            self.assertEqual(state.manual.delta_x_px, 0)
            self.assertEqual(state.manual.delta_y_px, 0)
            self.assertEqual(state.framing.crop_zoom_index, 0)
            self.assertEqual(state.framing.pan_x_permille, 0)
            self.assertFalse(state.alignment.valid)
            # Geometry-independent user intent survives.
            self.assertEqual(state.input_transform.left_orientation, "90_cw")
            self.assertEqual(state.input_transform.right_orientation, "90_cw")
            self.assertTrue(state.input_transform.left_mirror)
            self.assertTrue(state.favorite)
            self.assertEqual(state.floating_window.bottom_permille, 10)


class PreviewResponsivenessTests(unittest.TestCase):
    def test_floating_window_is_part_of_authoritative_preview_pair(self):
        from stereofine.preview_render import PreviewBasePair, render_preview_from_base
        from stereofine.state import PairState

        left = np.full((100, 200, 3), 180, dtype=np.uint8)
        right = np.full((100, 200, 3), 180, dtype=np.uint8)
        base = PreviewBasePair(left=left, right=right, scale=1.0, original_aspect=2.0)
        state = PairState()
        state.floating_window.left_permille = 20

        pair = render_preview_from_base(base, state, apply_color=False, apply_floating_window=True)
        self.assertTrue(np.all(pair.left[:, :4] == 0))
        self.assertTrue(np.all(pair.left[:, 5:] == 180))
        self.assertTrue(np.all(pair.right == 180))

        # Vertical masks replace lateral masks exactly like v41.  For a top mask
        # the extreme top corners are black while the opposite lower corners stay
        # untouched; the two eye masks are mirror images.
        state.floating_window.top_permille = 20
        state.floating_window.left_permille = 0
        pair = render_preview_from_base(base, state, apply_color=False, apply_floating_window=True)
        self.assertTrue(np.all(pair.left[0, 0] == 0))
        self.assertTrue(np.all(pair.right[0, -1] == 0))
        self.assertTrue(np.all(pair.left[-1, -1] == 180))
        self.assertTrue(np.all(pair.right[-1, 0] == 180))

    def test_color_fit_is_cached_in_preview_base_across_manual_nudges(self):
        from unittest.mock import patch
        from stereofine.inputs import LoadedStereoPair
        from stereofine.preview_render import build_preview_base, render_preview_from_base
        from stereofine.state import PairState

        rng = np.random.default_rng(7)
        left = rng.integers(0, 256, (180, 280, 3), dtype=np.uint8)
        right = np.clip(left.astype(np.int16) + 8, 0, 255).astype(np.uint8)
        loaded = LoadedStereoPair(
            left=left, right=right, left_path=Path("left.jpg"), right_path=Path("right.jpg"),
            kind="pair", source_width=280, source_height=180,
            left_source_width=280, left_source_height=180,
            right_source_width=280, right_source_height=180,
        )
        state = PairState()
        state.color.enabled = True

        import stereofine.preview_render as preview_render
        real_fit = preview_render.fit_symmetric_color_transfer
        calls = 0

        def counted_fit(*args, **kwargs):
            nonlocal calls
            calls += 1
            return real_fit(*args, **kwargs)

        with patch.object(preview_render, "fit_symmetric_color_transfer", side_effect=counted_fit):
            base = build_preview_base(loaded, state, max_width=240, max_height=160, apply_color=True)
            self.assertEqual(calls, 1)
            for dx in (1, 2, 3, -1, -2):
                state.manual.delta_x_px = dx
                render_preview_from_base(base, state, apply_color=True)
            self.assertEqual(calls, 1)
            self.assertTrue(base.color_applied)



class ProcessingIntegrationTests(unittest.TestCase):
    @staticmethod
    def _write_textured_pair(root: Path, name: str = "scene") -> None:
        rng = np.random.default_rng(42)
        h, w = 240, 360
        left = rng.integers(0, 256, (h, w, 3), dtype=np.uint8)
        left = cv2.GaussianBlur(left, (3, 3), 0)
        for _ in range(80):
            x = int(rng.integers(10, w - 10))
            y = int(rng.integers(10, h - 10))
            cv2.circle(left, (x, y), int(rng.integers(2, 6)), tuple(int(v) for v in rng.integers(0, 256, 3)), -1)
        matrix = np.float32([[1, 0, 8], [0, 1, 1]])
        right = cv2.warpAffine(left, matrix, (w, h), borderMode=cv2.BORDER_REFLECT)
        cv2.imwrite(str(root / f"{name}_l.png"), cv2.cvtColor(left, cv2.COLOR_RGB2BGR))
        cv2.imwrite(str(root / f"{name}_r.png"), cv2.cvtColor(right, cv2.COLOR_RGB2BGR))

    def test_shared_processing_core_writes_sidecar_and_reuses_valid_cache(self):
        from stereofine.processing import ProcessingOptions, process_source
        from stereofine.sources import discover_pair_sources
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write_textured_pair(root)
            source = discover_pair_sources(root)[0]
            first = process_source(source, ProcessingOptions())
            self.assertTrue(first.state.alignment.valid)
            self.assertTrue(first.state.disparity.valid)
            self.assertTrue(source.sidecar_path.is_file())
            self.assertFalse(first.alignment_from_cache)
            self.assertFalse(first.disparity_from_cache)

            second = process_source(source, ProcessingOptions())
            self.assertTrue(second.alignment_from_cache)
            self.assertTrue(second.disparity_from_cache)
            self.assertEqual(second.state.effective_offset_x_px, second.state.auto_offset_x_px)

    def test_view_or_zoom_sidecar_never_counts_as_analyzed_cache(self):
        from stereofine.processing import ProcessingOptions, process_source
        from stereofine.session import browse_source, save_browsed_state
        from stereofine.sources import discover_pair_sources
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write_textured_pair(root)
            source = discover_pair_sources(root)[0]
            browsed = browse_source(source)
            # A preview/framing-only edit may create a sidecar, but it must not
            # fabricate automatic analysis state or make a later batch skip it.
            browsed.state.framing.crop_zoom_index = 1
            save_browsed_state(browsed)
            sidecar = load_sidecar(source.sidecar_path, expected_source=browsed.source_stamp)
            self.assertEqual(sidecar.status, SidecarStatus.VALID)
            state = PairState.from_sidecar(sidecar.document)
            self.assertFalse(state.alignment.valid)
            self.assertFalse(state.disparity.valid)

            processed = process_source(source, ProcessingOptions())
            self.assertFalse(processed.alignment_from_cache)
            self.assertFalse(processed.disparity_from_cache)
            self.assertTrue(processed.state.alignment.valid)

    def test_stale_sidecar_does_not_leak_old_display_state(self):
        from stereofine.session import browse_source, save_browsed_state
        from stereofine.sources import discover_pair_sources
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write_textured_pair(root)
            source = discover_pair_sources(root)[0]
            session = browse_source(source)
            session.state.input_transform.left_orientation = "90_cw"
            session.state.input_transform.left_mirror = True
            session.state.input_transform.swap_eyes = True
            session.state.floating_window.left_permille = 7
            save_browsed_state(session)

            left = cv2.imread(str(source.left_path), cv2.IMREAD_COLOR)
            left[0, 0] = (left[0, 0].astype(np.uint16) + 3) % 256
            self.assertTrue(cv2.imwrite(str(source.left_path), left))

            reloaded = browse_source(source)
            self.assertEqual(reloaded.sidecar.status, SidecarStatus.STALE)
            self.assertEqual(reloaded.state.input_transform.left_orientation, "0")
            self.assertFalse(reloaded.state.input_transform.left_mirror)
            self.assertFalse(reloaded.state.input_transform.swap_eyes)
            self.assertEqual(reloaded.state.floating_window.left_permille, 0)
            self.assertFalse(reloaded.state.alignment.valid)
            self.assertFalse(reloaded.state.disparity.valid)

    def test_changed_input_identity_forces_real_reanalysis(self):
        from stereofine.processing import ProcessingOptions, process_source
        from stereofine.sources import discover_pair_sources
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write_textured_pair(root)
            source = discover_pair_sources(root)[0]
            first = process_source(source, ProcessingOptions())
            self.assertTrue(source.sidecar_path.is_file())

            left = cv2.imread(str(source.left_path), cv2.IMREAD_COLOR)
            left[0, 0] = (left[0, 0].astype(np.uint16) + 1) % 256
            self.assertTrue(cv2.imwrite(str(source.left_path), left))

            second = process_source(source, ProcessingOptions())
            self.assertFalse(second.alignment_from_cache)
            self.assertFalse(second.disparity_from_cache)

    def test_alignment_pipeline_mismatch_forces_reanalysis(self):
        from stereofine.processing import ProcessingOptions, process_source
        from stereofine.sources import discover_pair_sources
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write_textured_pair(root)
            source = discover_pair_sources(root)[0]
            process_source(source, ProcessingOptions())
            payload = json.loads(source.sidecar_path.read_text(encoding="utf-8"))
            payload["pipeline"]["alignment"] = "old-test-pipeline"
            source.sidecar_path.write_text(json.dumps(payload), encoding="utf-8")

            processed = process_source(source, ProcessingOptions())
            self.assertFalse(processed.alignment_from_cache)
            self.assertFalse(processed.disparity_from_cache)

    def test_batch_progress_has_lightweight_preview_and_releases_master_pair(self):
        from stereofine.batch import BatchRunOptions, run_batch
        from stereofine.processing import ProcessingOptions
        from stereofine.sources import discover_pair_sources
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write_textured_pair(root)
            progress_items = []
            result = run_batch(
                discover_pair_sources(root),
                BatchRunOptions(processing=ProcessingOptions(), analysis_only=True),
                progress=progress_items.append,
            )
            previews = [item.preview_rgb for item in progress_items if item.preview_rgb is not None]
            self.assertEqual(len(previews), 1)
            self.assertEqual(previews[0].dtype, np.uint8)
            self.assertLessEqual(previews[0].shape[1], 960)
            self.assertLessEqual(previews[0].shape[0], 640)
            self.assertIsNone(result.items[0].processed.loaded_pair)

    def test_analysis_only_batch_writes_report_and_no_image_output(self):
        from stereofine.batch import BatchRunOptions, run_batch
        from stereofine.processing import ProcessingOptions
        from stereofine.sources import discover_pair_sources
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write_textured_pair(root)
            sources = discover_pair_sources(root)
            result = run_batch(sources, BatchRunOptions(processing=ProcessingOptions(), analysis_only=True))
            self.assertEqual(len(result.items), 1)
            self.assertEqual(result.exported_count, 0)
            self.assertTrue(result.report_path.is_file())
            report = result.report_path.read_text(encoding="utf-8")
            self.assertIn("scene", report)
            self.assertIn("Gesamtdeviation", report)
            self.assertFalse((root / "sbs").exists())
            self.assertFalse((root / "anaglyph").exists())

    def test_favorites_only_batch_analyzes_nonfavorite_but_skips_export(self):
        from stereofine.batch import BatchRunOptions, run_batch
        from stereofine.processing import ProcessingOptions
        from stereofine.sources import discover_pair_sources
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = root / "out"
            self._write_textured_pair(root)
            sources = discover_pair_sources(root)
            result = run_batch(
                sources,
                BatchRunOptions(
                    processing=ProcessingOptions(),
                    analysis_only=False,
                    favorites_only=True,
                    output_folder=out,
                ),
            )
            self.assertEqual(len(result.items), 1)
            self.assertTrue(sources[0].sidecar_path.is_file())
            self.assertEqual(result.exported_count, 0)
            self.assertEqual(result.items[0].export_skipped_reason, "not_favorite")
            self.assertFalse(out.exists())

    def test_favorites_only_batch_exports_saved_favorite_state(self):
        from stereofine.batch import BatchRunOptions, run_batch
        from stereofine.processing import ProcessingOptions, process_source
        from stereofine.sidecar import save_sidecar, source_stamp_to_dict, load_sidecar
        from stereofine.sources import discover_pair_sources
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = root / "out"
            self._write_textured_pair(root)
            source = discover_pair_sources(root)[0]
            prepared = process_source(source, ProcessingOptions())
            prepared.state.favorite = True
            prepared.state.manual.delta_x_px = 1
            prepared.state.floating_window.left_permille = 4
            prepared.state.color.enabled = True
            save_sidecar(
                source.sidecar_path,
                prepared.state.to_sidecar(source=source_stamp_to_dict(prepared.source_stamp)),
            )

            result = run_batch(
                [source],
                BatchRunOptions(
                    processing=ProcessingOptions(),
                    favorites_only=True,
                    output_folder=out,
                ),
            )
            self.assertEqual(result.exported_count, 1)
            self.assertIsNone(result.items[0].processed.loaded_pair)
            self.assertIsNone(result.items[0].processed.preview_pair)
            self.assertTrue((out / "sbs" / "scene_sbs.jpg").is_file())
            self.assertTrue((out / "anaglyph" / "scene_anaglyph.jpg").is_file())
            reloaded = load_sidecar(source.sidecar_path, expected_source=prepared.source_stamp)
            state = PairState.from_sidecar(reloaded.document)
            self.assertTrue(state.favorite)
            self.assertEqual(state.manual.delta_x_px, 1)
            self.assertEqual(state.floating_window.left_permille, 4)
            self.assertTrue(state.color.enabled)
            self.assertTrue(state.color.valid)
            self.assertTrue(state.color.parameters)


class GuiIntegrationLogicTests(unittest.TestCase):
    def test_grid_keyboard_cycle_returns_to_clean_off_state_and_menu_stays_usable(self):
        gui = _import_gui_without_customtkinter_runtime()

        class Var:
            def __init__(self, value):
                self.value = value
            def get(self):
                return self.value
            def set(self, value):
                self.value = value

        class Widget:
            def __init__(self):
                self.values = {}
            def configure(self, **kwargs):
                self.values.update(kwargs)
            def cget(self, key):
                return self.values.get(key)

        app = object.__new__(gui.StereoFineApp)
        app.busy_state = "idle"
        app.grid_mode = Var("Aus")
        app.grid_spacing = Var("50 Promille")
        app.grid_spacing_display = Var("")
        app.grid_spacing_menu = Widget()
        app.grid_spacing_label = Widget()
        app.settings = types.SimpleNamespace(language="de")
        app._g_key_down = False
        app._update_preview_display = lambda: None
        normal_event = types.SimpleNamespace(state=0)

        states = []
        app._on_g(normal_event)
        first_state = (app.grid_mode.get(), app.grid_spacing.get())
        app._on_g(normal_event)  # operating-system key repeat while held
        self.assertEqual((app.grid_mode.get(), app.grid_spacing.get()), first_state)
        states.append(first_state)
        app._on_g_release()
        for _ in range(8):
            app._on_g(normal_event)
            states.append((app.grid_mode.get(), app.grid_spacing.get()))
            app._on_g_release()

        self.assertEqual(states[-1], ("Aus", "Drittel-Raster"))
        self.assertEqual(app.grid_spacing_display.get(), gui.grid_spacing_label("Drittel-Raster", "de"))
        self.assertEqual(app.grid_spacing_menu.cget("state"), "normal")
        self.assertEqual(app.grid_spacing_label.cget("text_color"), gui.TEXT_PRIMARY)

        # Shift+G is an explicit Off shortcut, not a spacing reset.
        app.grid_mode.set("Schwarz")
        app.grid_spacing.set("100 Promille")
        app._on_g(types.SimpleNamespace(state=0x0001))
        app._on_g_release()
        self.assertEqual(app.grid_mode.get(), "Aus")
        self.assertEqual(app.grid_spacing.get(), "100 Promille")
        self.assertEqual(app.grid_spacing_menu.cget("state"), "normal")






    def test_preview_bounds_reserve_dynamic_black_border_outside_image(self):
        gui = _import_gui_without_customtkinter_runtime()

        class Frame:
            def __init__(self, width, height):
                self.width = width
                self.height = height
            def winfo_width(self):
                return self.width
            def winfo_height(self):
                return self.height

        app = object.__new__(gui.StereoFineApp)
        for frame_w, frame_h in ((1400, 850), (1100, 700), (900, 600), (640, 480)):
            app.preview_frame = Frame(frame_w, frame_h)
            bound_w, bound_h = app._preview_bounds()
            border = gui.preview_border_px(bound_w)
            self.assertLessEqual(bound_w + border * 2, frame_w)
            self.assertLessEqual(bound_h + border * 2, frame_h)
            # The design-standard border always exceeds the maximum 30‰
            # Floating-Window intrusion by the documented 2 px reserve.
            self.assertGreaterEqual(border, round(bound_w * 0.030) + 2)

    def test_batch_progress_identity_advances_without_preview_frame(self):
        gui = _import_gui_without_customtkinter_runtime()
        from stereofine.processing import BatchProgress

        app = object.__new__(gui.StereoFineApp)
        app.current_job_kind = "batch"
        app.busy_state = "batch"
        app._batch_progress_index = None
        app._batch_progress_total = None
        app._batch_progress_source_name = None
        app._schedule_status_refresh = lambda *_args, **_kwargs: None
        app._preview_pil = None
        app._preview_left_current = None
        app._preview_right_current = None
        app._preview_pair_shape = None
        app._update_preview_display = lambda *_args, **_kwargs: None

        app._handle_progress(BatchProgress(17, 33, "bild017", "analysis"))
        self.assertEqual(app._batch_progress_index, 17)
        self.assertEqual(app._batch_progress_total, 33)
        self.assertEqual(app._batch_progress_source_name, "bild017")

        app.batch_mode = True
        app.current = types.SimpleNamespace(source=types.SimpleNamespace(display_name="bild001"))
        app.sources = [None] * 33
        app.source_index = 0
        app._t = lambda key, **kwargs: (
            f"Batch: {kwargs['count']} · Vorschau {kwargs['index']}/{kwargs['count']}"
            if key == "status_batch_preview" else key
        )
        status = app._input_status_text()
        self.assertIn("17/33", status)
        self.assertIn("bild017", status)

    def test_batch_success_uses_exactly_one_ready_sound_and_no_info_dialog(self):
        gui = _import_gui_without_customtkinter_runtime()

        class Var:
            def __init__(self, value):
                self.value = value
            def get(self):
                return self.value

        class Widget:
            def __init__(self):
                self.calls = []
            def configure(self, **kwargs):
                self.calls.append(kwargs)

        app = object.__new__(gui.StereoFineApp)
        app.current_job_kind = "batch"
        app.current_job_id = "synthetic"
        app.busy_state = "batch"
        app._batch_progress_index = 33
        app._batch_progress_total = 33
        app._batch_progress_source_name = "bild033"
        app._refresh_control_states = lambda: None
        app._stop_activity = lambda: None
        app._update_start_button_text = lambda: None
        app.after = lambda *_args, **_kwargs: None
        app.analysis_only = Var(True)
        app.favorites_only = Var(False)
        app.start_button = Widget()
        app.save_button = Widget()
        app.source_index = None
        app.sources = []
        app.tr = Translator("de")
        app._t = lambda key, **kwargs: app.tr.t(key, **kwargs)

        ready_calls = []
        info_calls = []
        warning_calls = []
        old_ready = gui.play_ready_sound
        old_info = gui.messagebox.showinfo
        old_warning = gui.messagebox.showwarning
        try:
            gui.play_ready_sound = lambda path: ready_calls.append(Path(path)) or True
            gui.messagebox.showinfo = lambda *args, **kwargs: info_calls.append((args, kwargs))
            gui.messagebox.showwarning = lambda *args, **kwargs: warning_calls.append((args, kwargs))
            gui.StereoFineApp._finish_worker_success(
                app, gui.BatchRunResult(report_path=Path("stereofine_analysis.txt"))
            )
        finally:
            gui.play_ready_sound = old_ready
            gui.messagebox.showinfo = old_info
            gui.messagebox.showwarning = old_warning

        self.assertEqual(len(ready_calls), 1)
        self.assertEqual(ready_calls[0].name, "ready.wav")
        self.assertEqual(info_calls, [])
        self.assertEqual(warning_calls, [])


class ReleaseStatusTests(unittest.TestCase):
    def test_vergence_status_reports_applied_projective_value_not_zero_placeholders(self):
        from stereofine.status import build_status_sections
        state = PairState()
        state.alignment.valid = True
        state.alignment.model = "Affine + Vergence"
        state.alignment.correction = {
            "vertical_shift_px": 0.0,
            "rotation_deg": 0.0,
            "scale": 1.0,
            "vergence_ready": False,
            "vergence_v_px": 0.0,
            "vergence_h_px": 0.0,
            "vergence_candidate_ready": True,
            "vergence_v_candidate_px": 0.4321,
            "vergence_h_candidate_px": -0.06789,
            "trapez_apply": {
                "enabled": True,
                "params": {"a_projective_x": 0.0002, "b_projective_y": -0.0001},
                "max_relative_y_correction_px_fullres": 0.81234,
            },
        }
        sections = build_status_sections(state, input_text="scene", language="de")
        rows = {row.label: row.value for section in sections for row in section.rows}
        self.assertEqual(rows["Vergenz (Trapezkorrektur)"], "0.8123 px")
        self.assertNotIn("V 0", rows["Vergenz (Trapezkorrektur)"])
        model_values = [row.value for section in sections for row in section.rows if row.label == "Modell"]
        self.assertEqual(model_values, ["Affine + Vergence"])

        # The same applied value must survive the compact sidecar representation.
        compact = state.to_sidecar(source={}).alignment["correction"]
        state.alignment.correction = compact
        sections = build_status_sections(state, input_text="scene", language="de")
        rows = {row.label: row.value for section in sections for row in section.rows}
        self.assertEqual(rows["Vergenz (Trapezkorrektur)"], "0.8123 px")

    def test_visible_status_hides_technical_warning_reasons(self):
        from stereofine.status import build_status_sections
        state = PairState()
        state.disparity.valid = True
        state.disparity.stale = False
        state.disparity.total_permille = 20.0
        state.disparity.low_edge_permille = -17.0
        state.disparity.high_edge_permille = 3.0
        state.disparity.warning_reasons = ["technical percentile threshold detail"]
        sections = build_status_sections(state, input_text="scene", language="de")
        visible = "\n".join(row.value for section in sections for row in section.rows)
        self.assertNotIn("technical percentile", visible)

        state.disparity.uncertain = True
        sections = build_status_sections(state, input_text="scene", language="de")
        visible = "\n".join(row.value for section in sections for row in section.rows)
        self.assertIn("Einschätzung unsicher – bitte prüfen!", visible)

        # Once a framing/manual edit invalidates the deviation, neither the old
        # traffic assessment nor its old uncertainty warning may remain visible.
        state.disparity.stale = True
        sections = build_status_sections(state, input_text="scene", language="de")
        visible = "\n".join(row.value for section in sections for row in section.rows)
        self.assertNotIn("Einschätzung unsicher – bitte prüfen!", visible)
        self.assertNotIn("grün", visible)


class ReleaseEdgeCaseTests(unittest.TestCase):
    def test_missing_exiftool_is_a_nonfatal_attempted_metadata_warning(self):
        from unittest import mock
        from stereofine.metadata import copy_metadata_without_preview_or_orientation
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "source.jpg"
            dst = root / "output.jpg"
            src.write_bytes(b"source")
            dst.write_bytes(b"output")
            with mock.patch("stereofine.metadata.find_exiftool_path", return_value=None):
                result = copy_metadata_without_preview_or_orientation(src, dst)
            self.assertTrue(result.attempted)
            self.assertFalse(result.success)
            self.assertEqual(result.message, "ExifTool nicht gefunden.")

    def test_batch_cancellation_is_not_collected_as_image_failure(self):
        from unittest import mock
        from stereofine.batch import run_batch
        from stereofine.sources import StereoSource
        source = StereoSource("full_sbs", Path("x.jpg"), Path("x.jpg"), Path("."), "x")
        with mock.patch("stereofine.batch.process_source", side_effect=JobCancelled("Job wurde abgebrochen.")):
            with self.assertRaises(JobCancelled):
                run_batch([source])

    def test_rare_core_errors_are_translatable_at_presentation_boundary(self):
        tr = Translator("en")
        self.assertEqual(tr.message("Full-SBS-Datei ist zu schmal."), "Full-SBS file is too narrow.")
        self.assertEqual(tr.message("max_samples muss mindestens 1 sein."), "max_samples must be at least 1.")
        self.assertEqual(
            tr.message("Halbbilder haben unterschiedliche Datentypen: uint8 != uint16"),
            "Half-images have different data types: uint8 != uint16",
        )
        self.assertEqual(
            tr.message("Unbekannte Stereoquelle: mystery"),
            "Unknown stereo source: mystery",
        )
        self.assertEqual(
            tr.message("Metadaten SBS: ExifTool nicht gefunden."),
            "SBS metadata: ExifTool not found.",
        )

    def test_batch_result_exposes_nonfatal_export_warnings(self):
        from types import SimpleNamespace
        from stereofine.batch import BatchRunItem, BatchRunResult
        from stereofine.export import ExportResult
        from stereofine.sources import StereoSource

        source = StereoSource("full_sbs", Path("scene.jpg"), Path("scene.jpg"), Path("."), "scene")
        processed = SimpleNamespace(source=source)
        item = BatchRunItem(
            processed=processed,
            export=ExportResult(warnings=["Metadaten SBS: ExifTool nicht gefunden."]),
        )
        result = BatchRunResult(items=[item])
        self.assertEqual(result.warnings, [(source, "Metadaten SBS: ExifTool nicht gefunden.")])

    def test_atomic_jpeg_failure_preserves_existing_output_and_cleans_temp(self):
        from unittest import mock
        from stereofine.export import _save_rgb_jpeg
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "existing.jpg"
            original = b"existing-good-output"
            target.write_bytes(original)
            image = np.full((12, 16, 3), 127, dtype=np.uint8)

            with mock.patch("stereofine.export.os.replace", side_effect=OSError("replace failed")):
                with self.assertRaises(OSError):
                    _save_rgb_jpeg(image, target, quality=95)

            self.assertEqual(target.read_bytes(), original)
            self.assertEqual(list(root.glob("existing.jpg.*.tmp")), [])

    def test_atomic_report_failure_preserves_existing_report_and_cleans_temp(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "stereofine_analysis.txt"
            original = "existing-good-report\n"
            target.write_text(original, encoding="utf-8")
            record = AnalysisRecord(
                source_name="scene",
                model="Affine",
                matches=10,
                inliers=8,
                vertical_error_mean_px=0.1,
                near_permille=-3.0,
                far_permille=17.0,
                total_permille=20.0,
                traffic="green",
                favorite=False,
                status="OK",
            )

            with mock.patch("stereofine.reports.os.replace", side_effect=OSError("replace failed")):
                with self.assertRaises(OSError):
                    write_analysis_report(target, [record])

            self.assertEqual(target.read_text(encoding="utf-8"), original)
            self.assertEqual(list(root.glob("stereofine_analysis.txt.*.tmp")), [])

    def test_cross_platform_ready_sound_uses_native_player_selection(self):
        from stereofine.notifications import _unix_sound_command

        sound = Path("/tmp/ready.wav")
        mac = _unix_sound_command(sound, platform="darwin", which=lambda name: "/usr/bin/afplay" if name == "afplay" else None)
        self.assertEqual(mac, ["/usr/bin/afplay", str(sound)])

        linux = _unix_sound_command(
            sound,
            platform="linux",
            which=lambda name: "/usr/bin/paplay" if name == "paplay" else None,
        )
        self.assertEqual(linux, ["/usr/bin/paplay", str(sound)])

        linux_pw = _unix_sound_command(
            sound,
            platform="linux",
            which=lambda name: "/usr/bin/pw-play" if name == "pw-play" else None,
        )
        self.assertEqual(linux_pw, ["/usr/bin/pw-play", str(sound)])

        self.assertIsNone(_unix_sound_command(sound, platform="freebsd", which=lambda _name: None))



if __name__ == "__main__":
    unittest.main()
