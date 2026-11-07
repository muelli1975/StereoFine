from dataclasses import asdict
import json
import os
from pathlib import Path
import tempfile
import time
import unittest

import numpy as np
from PIL import Image

from stereofine import diagnostics
from stereofine.endpoints import locate_endpoints, to_master, current_markers
from stereofine.folder_settings import apply_folder_preferences, FolderChoices
from stereofine.label_layout import place_labels
from stereofine.numbers import endpoint_values
from stereofine.processing import ProcessingDefaults
from stereofine.session import browse_source, save_browsed_state
from stereofine.sources import source_from_stereo_file
from stereofine.state import LookState, PairState
from stereofine.status import build_status_sections
from stereofine.worker import CancellationToken


class PreferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='sf-prefs-13-')
        self.root = Path(self.temp.name)
        diagnostics.configure_logging(self.root)
        self.sources = []
        for name in ('a', 'b', 'c'):
            p = self.root/(name+'.png')
            Image.fromarray(np.tile(np.arange(160, dtype=np.uint8), (60, 1))).save(p)
            self.sources.append(source_from_stereo_file(p, self.root))

    def tearDown(self):
        for handler in diagnostics._logger.handlers:
            handler.close()
        diagnostics._logger = None
        self.temp.cleanup()

    def test_partial_folder_values_keep_unselected_preferences_live(self):
        result = apply_folder_preferences(self.sources, FolderChoices(aspect='1:1'))
        self.assertEqual(len(result.updated), 3)
        first = self.sources[0]
        raw = json.loads(first.sidecar_path.read_text())
        self.assertNotIn('look', raw)
        self.assertNotIn('color', raw)
        a = browse_source(first, ProcessingDefaults(color_enabled=False, look_enabled=True, look_strength=.43))
        self.assertEqual(a.state.framing.aspect, '1:1')
        self.assertTrue(a.state.look.enabled)
        self.assertFalse(a.state.color.enabled)
        self.assertAlmostEqual(a.state.look.strength, .43)
        save_browsed_state(a)  # Passive saves must not freeze the unchecked fields.
        b = browse_source(first, ProcessingDefaults(color_enabled=True, look_enabled=False, look_strength=.7))
        self.assertTrue(b.state.color.enabled)
        self.assertFalse(b.state.look.enabled)
        self.assertAlmostEqual(b.state.look.strength, .7)
        self.assertEqual(b.state.framing.aspect, '1:1')

    def test_folder_patch_preserves_edits_and_invalidates_crop_dependents(self):
        source = self.sources[0]
        a = browse_source(source)
        s = a.state
        s.favorite = True
        s.manual.delta_x_px, s.manual.delta_y_px = 7, -2
        s.floating_window.left_permille = 12
        s.framing.crop_zoom_index, s.framing.pan_x_permille = 2, 140
        s.alignment.valid = True
        s.alignment.correction = {'scale': 1.001, 'rotation_deg': .2}
        s.disparity.valid, s.disparity.stale = True, False
        s.color.valid = True
        save_browsed_state(a)
        before = json.loads(source.sidecar_path.read_text())
        before['unrecognized_future_field'] = {'kept': 42}
        source.sidecar_path.write_text(json.dumps(before), encoding='utf-8')
        apply_folder_preferences([source], FolderChoices(aspect='16:9'))
        raw = json.loads(source.sidecar_path.read_text())
        for key in ('favorite', 'manual', 'alignment', 'floating_window', 'unrecognized_future_field'):
            self.assertEqual(raw[key], before[key])
        self.assertEqual(raw['framing']['crop_zoom_index'], 2)
        self.assertEqual(raw['framing']['pan_x_permille'], 140)
        self.assertFalse(raw['disparity']['valid'])
        self.assertTrue(raw['disparity']['stale'])
        self.assertFalse(raw['color']['valid'])

    def test_lut_and_color_can_be_applied_independently(self):
        source = self.sources[0]
        look = LookState(False, 'matrix', '', .27)
        apply_folder_preferences([source], FolderChoices(look=look, color_enabled=False))
        state = browse_source(source, ProcessingDefaults(aspect='16:9')).state
        self.assertEqual(state.look, look)
        self.assertFalse(state.color.enabled)
        self.assertEqual(state.framing.aspect, '16:9')

    def test_corrupt_or_changed_sources_are_not_overwritten(self):
        source = self.sources[0]
        source.sidecar_path.parent.mkdir()
        source.sidecar_path.write_text('{broken', encoding='utf-8')
        result = apply_folder_preferences([source], FolderChoices(color_enabled=True))
        self.assertEqual(len(result.failed), 1)
        self.assertEqual(source.sidecar_path.read_text(), '{broken')
        source.sidecar_path.unlink()
        apply_folder_preferences([source], FolderChoices(aspect='1:1'))
        before = source.sidecar_path.read_bytes()
        source.left_path.write_bytes(source.left_path.read_bytes()+b'changed')
        result = apply_folder_preferences([source], FolderChoices(color_enabled=True))
        self.assertEqual(len(result.failed), 1)
        self.assertEqual(source.sidecar_path.read_bytes(), before)

    def test_cancel_retains_completed_files_and_does_not_touch_remaining(self):
        token = CancellationToken()
        result = apply_folder_preferences(self.sources, FolderChoices(aspect='1:1'), cancellation=token,
                                          progress=lambda p: token.cancel())
        self.assertTrue(result.cancelled)
        self.assertEqual(len(result.updated), 1)
        self.assertTrue(self.sources[0].sidecar_path.exists())
        self.assertFalse(self.sources[1].sidecar_path.exists())

    def test_old_sidecar_without_lut_inherits_current_default(self):
        session = browse_source(self.sources[0])
        save_browsed_state(session)
        path = session.source.sidecar_path
        raw = json.loads(path.read_text())
        raw.pop('look'); raw.pop('preference_fields', None)
        path.write_text(json.dumps(raw), encoding='utf-8')
        changed = browse_source(self.sources[0], ProcessingDefaults(look_enabled=True, look_preset_id='matrix'))
        self.assertTrue(changed.state.look.enabled)
        self.assertEqual(changed.state.look.preset_id, 'matrix')

    def test_logs_rotate_and_age_only_their_own_files(self):
        folder = self.root/'logs'
        old = folder/'stereofine.log.2'
        old.write_text('old')
        os.utime(old, (time.time()-40*86400,)*2)
        report = folder/'keep-my-report.txt'; report.write_text('keep')
        diagnostics.configure_logging(self.root, max_bytes=512)
        self.assertFalse(old.exists())
        for i in range(40):
            diagnostics.log_event('entry '+str(i)+' '+'x'*100)
        files = list(folder.glob('stereofine.log*'))
        self.assertLessEqual(len(files), 3)
        self.assertTrue(all(p.stat().st_size <= 512 for p in files))
        self.assertEqual(report.read_text(), 'keep')


class EndpointTests(unittest.TestCase):
    def test_unconfirmed_verifier_cannot_override_closer_depth_evidence(self):
        d = np.zeros((20, 100), np.float32)
        confidence = np.zeros_like(d, bool)
        d[8, 30], d[12, 60] = -2.2, -8.4
        confidence[8, 30] = confidence[12, 60] = True
        bad_near = dict(confirmed=False, verified_points=[dict(x=60, y=12, disparity_px=-8.4)])
        bad_far = dict(confirmed=False, verified_points=[dict(x=69, y=8, disparity_px=2.2)])
        result = locate_endpoints(d, confidence, bad_near, bad_far, -84., -22.)
        self.assertAlmostEqual(result['markers']['near']['left'][0], .305)
        self.assertAlmostEqual(result['markers']['far']['left'][0], .605)

    def test_status_and_marker_values_are_identical_in_both_languages(self):
        state = PairState()
        state.disparity.valid = True
        state.disparity.low_edge_permille = -5.3
        state.disparity.high_edge_permille = -2.21
        state.disparity.total_permille = 3.09
        state.framing.auto_near_base_width_px = 600
        candidate = dict(markers={'near': dict(left=[.4,.5], right=[.4084,.5]),
                                 'far': dict(left=[.2,.5], right=[.20221,.5])})
        state.disparity.endpoints = to_master(candidate, state, (400, 600), 1.5)
        for uncertain in (False, True):
            state.disparity.uncertain = uncertain
            markers = current_markers(state)
            self.assertAlmostEqual(markers['near']['permille'], -2.21)
            self.assertAlmostEqual(markers['far']['permille'], 5.3)
            for language, near, far in (('de','-2,21‰','5,30‰'), ('en','-2.21‰','5.30‰')):
                texts = endpoint_values(state, language)
                self.assertEqual(texts, dict(near=near, far=far))
                section = build_status_sections(state, input_text='x', language=language)[2]
                self.assertEqual(section.rows[1].value, texts['near'])
                self.assertEqual(section.rows[2].value, texts['far'])

    def test_labels_stay_inside_each_eye_and_avoid_each_other(self):
        items = [(315, 8, 110, 28), (315, 12, 110, 28)]
        rects = place_labels(items, (0, 0, 320, 200))
        for rect, leader in rects:
            self.assertGreaterEqual(rect[0], 0); self.assertLessEqual(rect[2], 320)
            self.assertGreaterEqual(rect[1], 0); self.assertLessEqual(rect[3], 200)
        a, b = [x[0] for x in rects]
        self.assertTrue(a[3] <= b[1] or b[3] <= a[1] or a[2] <= b[0] or b[2] <= a[0])


if __name__ == '__main__':
    unittest.main()
