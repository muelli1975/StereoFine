from __future__ import annotations

import unittest
from pathlib import Path

from PIL import Image

from stereofine.config import APP_VERSION
from stereofine.sidecar import SidecarDocument


ROOT = Path(__file__).resolve().parents[1]


class ReleaseHygieneTests(unittest.TestCase):
    def test_public_version_is_final(self):
        self.assertEqual(APP_VERSION, "1.0")

    def test_release_files_exist(self):
        required = [
            "LICENSE.txt",
            "README.md",
            "README_DE.md",
            "README_EN.md",
            "THIRD_PARTY_NOTICES.md",
            "BUILD_WINDOWS.md",
            "RELEASE_CHECKLIST.md",
            "StereoFine.spec",
            "version_info.txt",
            "build_windows.ps1",
            "assets/stereofine.ico",
            "assets/stereofine.jpg",
            "assets/ready.wav",
            "licenses/Tcl-8.6-LICENSE.txt",
            "licenses/Tk-8.6-LICENSE.txt",
        ]
        for relative in required:
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_source_snapshot_contains_no_user_settings(self):
        # Runtime settings and per-image sidecars are created during real use; a
        # release source snapshot must not ship local state accidentally created
        # while validating the bundled start/reference image.
        self.assertFalse((ROOT / "settings.json").exists())
        self.assertFalse((ROOT / "assets" / "_stereofine").exists())
        self.assertEqual(list((ROOT / "assets").rglob("*.sfin")), [])

    def test_release_master_is_expected_asset(self):
        with Image.open(ROOT / "assets/stereofine.jpg") as image:
            self.assertEqual(image.size, (6314, 2160))

    def test_new_sidecar_does_not_write_obsolete_window_fields(self):
        payload = SidecarDocument().to_dict()
        text = repr(payload)
        self.assertNotIn("window_position_percent", text)
        self.assertNotIn("window_back_permille", text)

    def test_runtime_contains_no_release_todos_or_dev_version(self):
        runtime_files = [ROOT / "StereoFine.py", *sorted((ROOT / "stereofine").glob("*.py"))]
        for path in runtime_files:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("1.0-dev", text, path.name)
            self.assertNotIn("TODO", text, path.name)
            self.assertNotIn("FIXME", text, path.name)

    def test_build_script_tcl_tk_license_fallback_is_nonfatal(self):
        build_script = (ROOT / "build_windows.ps1").read_text(encoding="utf-8")
        self.assertIn("using the bundled official", build_script.lower())
        self.assertNotIn('throw "Required runtime license file not found:', build_script)

    def test_build_tool_is_pinned(self):
        build_requirements = (ROOT / "requirements-build.txt").read_text(encoding="utf-8")
        self.assertIn("pyinstaller==6.22.2", build_requirements.lower())

    def test_ci_prepares_platform_exiftool_packages(self):
        workflow = (ROOT / ".github" / "workflows" / "build-release.yml").read_text(encoding="utf-8")
        self.assertIn("EXIFTOOL_VERSION:", workflow)
        self.assertIn("sourceforge.net/projects/exiftool/files/exiftool-${version}_64.zip/download", workflow)
        self.assertIn("Image-ExifTool-${VERSION}.tar.gz", workflow)
        self.assertIn("portable-tools/exiftool", workflow)
        self.assertIn("portable-tools/lib", workflow)

    def test_public_gui_keeps_established_fixed_output(self):
        gui_source = (ROOT / "stereofine" / "gui.py").read_text(encoding="utf-8")
        batch_source = (ROOT / "stereofine" / "batch.py").read_text(encoding="utf-8")
        self.assertNotIn("self.output_mode =", gui_source)
        self.assertNotIn("output_mode:", batch_source)
        self.assertIn('output_mode="both"', batch_source)
        for readme in ("README.md", "README_DE.md", "README_EN.md"):
            text = (ROOT / readme).read_text(encoding="utf-8")
            self.assertNotIn("selected output mode", text.lower(), readme)
            self.assertNotIn("je nach einstellung entstehen", text.lower(), readme)
            self.assertNotIn("- SBS + anaglyph", text, readme)
            self.assertNotIn("- SBS + Anaglyphe", text, readme)
        build_text = (ROOT / "BUILD_WINDOWS.md").read_text(encoding="utf-8").lower()
        self.assertNotIn("selected sbs/anaglyph", build_text)
        self.assertIn("always produces both an sbs jpeg and an anaglyph jpeg", build_text)

    def test_gui_contains_recovered_responsiveness_and_scroll_contract(self):
        gui_source = (ROOT / "stereofine" / "gui.py").read_text(encoding="utf-8")
        self.assertNotIn('_bind_sidebar_mousewheel', gui_source)
        self.assertNotIn('_on_sidebar_mousewheel', gui_source)
        metadata_source = (ROOT / 'stereofine' / 'metadata.py').read_text(encoding='utf-8')
        self.assertIn('("exiftool.exe", "exiftool")', metadata_source)
        self.assertIn("_navigation_defaults", gui_source)
        self.assertIn("_schedule_status_refresh", gui_source)
        self.assertIn("PREVIEW_RESIZE_DEBOUNCE_MS = 150", gui_source)
        self.assertIn("self._refresh_preview(rebuild_base=True)", gui_source)
        self.assertIn('self.current_job_kind == "batch" and self._preview_left_current is None', gui_source)
        self.assertIn("ACTIVITY_SPINNER_SIZE = 36", gui_source)
        self.assertIn("ACTIVITY_SPINNER_PERIOD_SEC = 1.0", gui_source)
        self.assertIn("ACTIVITY_MIN_VISIBLE_MS = 200", gui_source)
        self.assertIn("_ensure_status_widgets", gui_source)
        self.assertIn("border_reserve = preview_border_px(width)", gui_source)
        self.assertIn("width - border_reserve * 2", gui_source)
        self.assertIn('help_w = min(960', gui_source)
        self.assertIn('help_h = min(640', gui_source)
        self.assertNotIn("CTkScrollableFrame(window", gui_source)

    def test_f_shortcut_toggles_existing_favorite_action(self):
        gui_source = (ROOT / "stereofine" / "gui.py").read_text(encoding="utf-8")
        i18n_source = (ROOT / "stereofine" / "i18n.py").read_text(encoding="utf-8")
        self.assertIn('self.bind_all("<f>", self._on_f)', gui_source)
        self.assertIn('self.bind_all("<F>", self._on_f)', gui_source)
        self.assertIn('self.bind_all("<KeyRelease-f>", lambda e: self._release_shortcut_key("f"))', gui_source)
        self.assertIn('def _on_f(self, event=None):', gui_source)
        self.assertIn('_claim_shortcut_key("f", event)', gui_source)
        self.assertIn('return self._on_favorite_clicked(event)', gui_source)
        self.assertIn('F                       Favorit setzen/entfernen', i18n_source)
        self.assertIn('F                       Toggle favorite', i18n_source)
        self.assertIn('`F` – toggle favorite', (ROOT / "README_EN.md").read_text(encoding="utf-8"))
        self.assertIn('`F` – Favorit setzen/entfernen', (ROOT / "README_DE.md").read_text(encoding="utf-8"))

    def test_release_ui_regressions_are_explicitly_guarded(self):
        gui_source = (ROOT / "stereofine" / "gui.py").read_text(encoding="utf-8")
        i18n_source = (ROOT / "stereofine" / "i18n.py").read_text(encoding="utf-8")
        batch_source = (ROOT / "stereofine" / "batch.py").read_text(encoding="utf-8")
        self.assertIn('"start_batch": "Alle justieren"', i18n_source)
        self.assertIn('"start_batch": "Align all"', i18n_source)
        # StereoFine deliberately uses one compact primary-action slot: start in
        # idle, cancel while a worker is active. No second cancel row may return.
        self.assertNotIn("cancel_button", gui_source)
        self.assertIn("def _on_primary_action", gui_source)
        self.assertIn('text=self._t("cancel")', gui_source)
        self.assertIn("_set_start_button_cancel", gui_source)
        self.assertIn("_shortcut_keys_down", gui_source)
        self.assertIn('self.bind_all("<KeyRelease-F1>"', gui_source)
        self.assertIn('_claim_shortcut_key("ctrl-r"', gui_source)
        self.assertIn("_render_activity_spinner_frame", gui_source)
        self.assertIn("_update_grid_control_state", gui_source)
        self.assertIn("BATCH_PREVIEW_MAX_WIDTH = 960", batch_source)
        self.assertIn("processed.loaded_pair = None", batch_source)

    def test_theme_matches_splattricia_family_reference(self):
        theme = (ROOT / "stereofine" / "theme.py").read_text(encoding="utf-8")
        expected = {
            'APP_BG = "#111111"',
            'SECONDARY_BG = "#181818"',
            'PANEL_BG = "#202020"',
            'HOVER_BG = "#282828"',
            'BORDER = "#333333"',
            'TEXT_PRIMARY = "#f2f2f2"',
            'TEXT_SECONDARY = "#b8b8b8"',
            'TEXT_DISABLED = "#727272"',
            'GOLD_DARK = "#9c7c38"',
            'GOLD_LIGHT = "#c6a95e"',
            'DANGER = "#7f3939"',
            'DANGER_HOVER = "#944545"',
            'CONTROL_RADIUS = 8',
            'PANEL_RADIUS = 12',
        }
        for line in expected:
            self.assertIn(line, theme)


if __name__ == "__main__":
    unittest.main()
