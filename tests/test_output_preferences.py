"""Persistent export choices, portable suffixes and independent previews."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from stereofine.batch import BatchRunOptions, run_batch
from stereofine.export import save_pair_outputs
from stereofine.output_naming import SBS_SUFFIXES, suffix_label, suffix_labels, suffix_value, validate_sbs_suffix
from stereofine.processing import ProcessingOptions
from stereofine.settings import AppSettings, load_settings, save_settings
from stereofine.sidecar import SidecarLoadResult, SidecarStatus
from stereofine.state import PairState
from stereofine.status import sidecar_status_text
from tests.test_foundation import _import_gui_without_customtkinter_runtime


class OutputPreferencesTests(unittest.TestCase):
    def test_defaults_and_old_preferences_keep_established_outputs(self):
        old = AppSettings.from_dict({'language': 'en', 'gray_anaglyph': True, 'save_cross': True})
        self.assertTrue(old.save_anaglyph)
        self.assertFalse(old.use_custom_sbs_suffix)
        self.assertEqual(old.sbs_suffix, '_cs')
        self.assertTrue(old.gray_anaglyph and old.save_cross)
        old.save_anaglyph, old.use_custom_sbs_suffix, old.sbs_suffix = False, True, '_cs'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'settings.json'
            save_settings(old, path)
            restored = load_settings(path)
        self.assertFalse(restored.save_anaglyph)
        self.assertTrue(restored.use_custom_sbs_suffix and restored.gray_anaglyph)
        self.assertEqual(restored.sbs_suffix, '_cs')

    def test_cosima_default_replaces_only_the_old_inactive_standard(self):
        self.assertEqual(AppSettings().sbs_suffix, '_cs')
        self.assertFalse(AppSettings().use_custom_sbs_suffix)
        for enabled, suffix, expected in ((False, '_sbs', '_cs'), (True, '_sbs', '_sbs'),
                (False, '_s', '_s'), (True, '-lr', '-lr'), (False, '', ''),
                (False, '_my_stereo', '_my_stereo')):
            settings = AppSettings.from_dict({'use_custom_sbs_suffix': enabled, 'sbs_suffix': suffix})
            self.assertEqual(settings.sbs_suffix, expected)
            self.assertEqual(settings.use_custom_sbs_suffix, enabled)
        # Once upgraded, every later explicit text choice survives a restart,
        # including typing _sbs and subsequently disabling the custom suffix.
        chosen = AppSettings(use_custom_sbs_suffix=False, sbs_suffix='_sbs')
        restored = AppSettings.from_dict(chosen.to_dict())
        self.assertEqual(restored.sbs_suffix, '_sbs')
        upgraded = AppSettings.from_dict({'sbs_suffix': '_sbs', 'use_custom_sbs_suffix': False})
        upgraded.sbs_suffix = '_sbs'
        self.assertEqual(AppSettings.from_dict(upgraded.to_dict()).sbs_suffix, '_sbs')

    def test_preset_labels_and_custom_text_roundtrip_in_both_languages(self):
        for language in ('de', 'en'):
            self.assertEqual(suffix_labels(language), ['_s (m.objects)', '_cs (COSIMA)', '-lr (Bino)',
                'Ohne Zusatz' if language == 'de' else 'No suffix'])
            for value in [suffix for suffix, _ in SBS_SUFFIXES]+['', '_sbs', '_meine Variante']:
                self.assertEqual(suffix_value(suffix_label(value, language), language), value)
            self.assertEqual(suffix_label('_sbs', language), '_sbs')
            self.assertEqual(suffix_value('literal (custom)', language), 'literal (custom)')

    def test_suffixes_change_only_names_for_jpeg_and_full_depth_tiff(self):
        rng = np.random.default_rng(8)
        for tiff, dtype in ((False, np.uint8), (True, np.uint16)):
            left = rng.integers(0, np.iinfo(dtype).max, (12, 18, 3), dtype=dtype)
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                reference = save_pair_outputs(left, left, root/'reference', 'photo', tiff_sbs=tiff,
                                              filename_deviation_permille=30, save_cross=True)
                for index, suffix in enumerate([s for s, _ in SBS_SUFFIXES]+['', '_custom']):
                    actual = save_pair_outputs(left, left, root/str(index), 'photo', tiff_sbs=tiff,
                        filename_deviation_permille=30, save_cross=True, sbs_suffix=suffix)
                    extension = 'tif' if tiff else 'jpg'
                    self.assertEqual(actual.sbs_path.name, f'photo_030{suffix}.{extension}')
                    for kind in ('sbs_path', 'anaglyph_path', 'cross_path'):
                        self.assertEqual(getattr(actual, kind).read_bytes(), getattr(reference, kind).read_bytes())

    def test_invalid_suffix_is_rejected_before_writing_any_output(self):
        eye = np.zeros((4, 5, 3), np.uint8)
        for suffix in ('/bad', '\\bad', '..', 'bad?', 'space ', 'dot.', 'x'*81, '\x00'):
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as directory:
                target = Path(directory)/'output'
                with self.assertRaises(ValueError):
                    save_pair_outputs(eye, eye, target, 'photo', sbs_suffix=suffix)
                self.assertFalse(target.exists())
        self.assertEqual(validate_sbs_suffix(''), '')

    def test_batch_skip_anaglyph_still_writes_sbs_and_cross_and_keeps_preview(self):
        source = SimpleNamespace(base_name='photo', display_name='photo', metadata_source=None,
                                 left_path=Path('source_l.jpg'), right_path=Path('source_r.jpg'))
        image = np.full((12, 18, 3), 120, np.uint8)
        for enabled in (False, True):
            with tempfile.TemporaryDirectory() as directory:
                source.input_root = Path(directory)
                source.sidecar_path = source.input_root / '_stereofine' / 'photo.sfin'
                state = PairState()
                processed = SimpleNamespace(state=state, analysis_record=object(), preview_pair=None,
                                            loaded_pair=SimpleNamespace(icc_profile=None))
                progress = []
                options = BatchRunOptions(processing=ProcessingOptions(save_sidecar=False),
                    output_folder=Path(directory), save_anaglyph=enabled, gray_anaglyph=True,
                    sbs_suffix='_cs', save_cross=True)
                with patch('stereofine.batch.validate_source_names'), \
                        patch('stereofine.batch.process_source', return_value=processed), \
                        patch('stereofine.batch.render_final_pair', return_value=(image, image, None)):
                    result = run_batch([source], options, progress=progress.append)
                self.assertEqual(result.failed, [])
                output = result.items[0].export
                self.assertEqual(output.sbs_path.name, 'photo_cs.jpg')
                self.assertTrue(output.sbs_path.is_file() and output.cross_path.is_file())
                self.assertEqual(output.anaglyph_path is not None, enabled)
                self.assertEqual((Path(directory)/'anaglyph').exists(), enabled)
                self.assertTrue(any(p.preview_rgb is not None for p in progress))

    def test_text_entry_shortcuts_do_not_call_image_actions(self):
        gui = _import_gui_without_customtkinter_runtime()
        app = object.__new__(gui.StereoFineApp)
        calls = []
        guarded = app._shortcut_handler(lambda event: calls.append(event))
        for kind in ('Entry', 'TEntry', 'TCombobox', 'Text', 'Spinbox'):
            self.assertIsNone(guarded(SimpleNamespace(widget=SimpleNamespace(
                winfo_class=lambda: kind, cget=lambda key: 'normal'))))
        self.assertFalse(calls)
        guarded(SimpleNamespace(widget=SimpleNamespace(winfo_class=lambda: 'Entry',
                                                      cget=lambda key: 'disabled')))
        self.assertEqual(len(calls), 1)
        guarded(SimpleNamespace(widget=SimpleNamespace(winfo_class=lambda: 'Label')))
        self.assertEqual(len(calls), 2)

    def test_suffix_confirmation_and_selection_return_to_image_controls(self):
        gui = _import_gui_without_customtkinter_runtime()
        app = object.__new__(gui.StereoFineApp)
        focus = []
        app.focus_set = lambda: focus.append('image')
        app._commit_sbs_suffix = lambda **kw: True
        self.assertEqual(app._on_sbs_suffix_return(), 'break')
        app._on_sbs_suffix_selected()
        self.assertEqual(focus, ['image', 'image'])
        app._commit_sbs_suffix = lambda **kw: False
        app._on_sbs_suffix_return()
        self.assertEqual(focus, ['image', 'image'])

    def test_other_actions_release_editor_before_running_their_command(self):
        gui = _import_gui_without_customtkinter_runtime()
        app = object.__new__(gui.StereoFineApp)
        entry, other = object(), object()
        app.sbs_suffix_menu = SimpleNamespace(_entry=entry)
        focused = [entry]
        app.focus_get = lambda: focused[0]
        app.focus_set = lambda: focused.__setitem__(0, app)
        calls = []
        command = app._image_control_command(lambda value: calls.append((focused[0], value)) or 42)
        self.assertEqual(command('selection'), 42)
        self.assertEqual(calls, [(app, 'selection')])
        focused[0] = other
        command('unchanged')
        self.assertIs(focused[0], other)
        self.assertIsNone(app._image_control_command(None))

    def test_pointer_keeps_typing_only_inside_the_suffix_entry(self):
        gui = _import_gui_without_customtkinter_runtime()
        app = object.__new__(gui.StereoFineApp)
        entry = object()
        app.sbs_suffix_menu = SimpleNamespace(_entry=entry)
        focused = [entry]
        app.focus_get = lambda: focused[0]
        app.focus_set = lambda: focused.__setitem__(0, app)
        app._on_control_pointer(SimpleNamespace(widget=entry))
        self.assertIs(focused[0], entry)
        app._on_control_pointer(SimpleNamespace(widget=object()))
        self.assertIs(focused[0], app)

    def test_partial_cache_status_does_not_expose_internal_version_mismatches(self):
        for language, expected in (('de', 'Einstellungen: Geladen'), ('en', 'Settings: Loaded')):
            for mismatch in ((), ('color',), ('input', 'alignment', 'disparity')):
                sidecar = SidecarLoadResult(SidecarStatus.VALID, pipeline_mismatches=mismatch)
                before = deepcopy(sidecar)
                self.assertEqual(sidecar_status_text(sidecar, language), expected)
                self.assertEqual(sidecar, before)
                self.assertEqual(sidecar.alignment_cache_valid, not {'input', 'alignment'}.intersection(mismatch))
                self.assertEqual(sidecar.disparity_cache_valid, not {'input', 'alignment', 'disparity'}.intersection(mismatch))
                self.assertEqual(sidecar.color_cache_valid, 'color' not in mismatch and 'input' not in mismatch)
            migrated = SidecarLoadResult(SidecarStatus.MIGRATED)
            self.assertEqual(sidecar_status_text(migrated, language), expected)
            self.assertFalse(migrated.alignment_cache_valid)
