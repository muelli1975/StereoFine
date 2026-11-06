"""Counterexamples from the audit, expressed as required user-visible behavior."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from stereofine import batch, native_preview
from stereofine.batch import BatchRunOptions, run_batch
from stereofine.color_transfer import fit_symmetric_color_transfer
from stereofine.export import deviation_filename_suffix
from stereofine.inputs import InputError
from stereofine.native_preview import native_key, prepare_native_preview, fit_display_pair
from stereofine.output_paths import OutputPathGuard
from stereofine.preview_render import build_preview_base, render_preview_from_base
from stereofine.processing import ProcessingOptions, process_source
from stereofine.render import render_final_pair
from stereofine.session import browse_source, save_browsed_state
from stereofine.settings import AppSettings
from stereofine.sidecar import load_sidecar, SidecarLoadResult, SidecarStatus
from stereofine.sources import SourceDirectoryIndex, load_source, source_from_stereo_file
from stereofine.state import PairState
from stereofine.worker import CancellationToken, JobCancelled, WorkerMessage, WorkerMessageKind
from tests import test_preview_stability, test_restart_alignment
from tests.test_final_corrections import loaded_pair


def app_for(session, bounds=(240, 180)):
    app = test_preview_stability.PreviewStabilityTests().app()
    app.current = session
    app._preview_bounds = lambda: bounds
    app._sync_vars_from_current = app._render_status = lambda: None
    app._request_native_preview = lambda **kwargs: None
    app._build_preview_anaglyph = lambda: setattr(app, '_preview_pil', Image.fromarray(app._preview_left_current))
    prepared = app._prepare_session_preview(session, bounds, CancellationToken())
    app._install_session_preview(prepared)
    app._render_session_preview(session)
    return app


def colored_source(root):
    source = test_restart_alignment.RestartAlignmentTests().source(root)
    with Image.open(source.right_path) as image:
        pixels = np.asarray(image.convert('RGB')).copy()
    pixels[:, pixels.shape[1]//2:] = np.clip(pixels[:, pixels.shape[1]//2:].astype(np.int16)+70, 0, 255)
    Image.fromarray(pixels).save(source.right_path)
    process_source(source)
    session = browse_source(source)
    session.state.color.enabled = True
    return session


class ReliabilityUpdateTests(unittest.TestCase):
    def test_input_files_survive_both_empty_and_normal_suffix_collisions(self):
        for suffix in ('', '_sbs'):
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                fixture = root/'fixture'; fixture.mkdir()
                pair = test_restart_alignment.RestartAlignmentTests().source(fixture)
                eyes = [np.asarray(Image.open(path).convert('RGB')) for path in (pair.left_path, pair.right_path)]
                inputs = root/'sbs'; inputs.mkdir()
                names = ['image.jpg'] if not suffix else ['image.jpg', 'image_sbs.jpg']
                sources = []
                for name in names:
                    path = inputs/name
                    Image.fromarray(np.concatenate(eyes, axis=1)).save(path, quality=98, subsampling=0)
                    sources.append(source_from_stereo_file(path, inputs))
                before = {source.left_path: source.left_path.read_bytes() for source in sources}
                result = run_batch(sources, BatchRunOptions(output_folder=root, sbs_suffix=suffix,
                                                           save_anaglyph=False))
                self.assertTrue(result.failed)
                for path, data in before.items(): self.assertEqual(path.read_bytes(), data)

    def test_existing_export_remains_replaceable_without_a_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = test_restart_alignment.RestartAlignmentTests().source(root)
            options = BatchRunOptions(output_folder=root/'output', save_anaglyph=False)
            first = run_batch([source], options)
            output = first.items[0].export.sbs_path
            output.write_bytes(b'previous export')
            second = run_batch([source], options)
            self.assertFalse(second.failed)
            self.assertNotEqual(output.read_bytes(), b'previous export')

    def test_guard_detects_aliases_and_claims_complete_plan_before_any_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/'source.jpg'; source.write_bytes(b'original')
            alias = root/'alias.jpg'
            try: alias.hardlink_to(source)
            except OSError: self.skipTest('Hard links unavailable')
            guard = OutputPathGuard([source])
            with self.assertRaises(ValueError): guard.claim([root/'safe.jpg', alias], 'one')
            # A rejected plan did not reserve its otherwise safe first path.
            guard.claim([root/'safe.jpg'], 'two')
            with self.assertRaises(ValueError): guard.claim([root/'safe.jpg'], 'three')
            self.assertEqual(source.read_bytes(), b'original')

    def test_deviation_suffix_collision_is_reported_instead_of_replacing_another_image(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); fixture = root/'fixture'; fixture.mkdir()
            pair = test_restart_alignment.RestartAlignmentTests().source(fixture)
            arrays = [np.asarray(Image.open(p).convert('RGB')) for p in (pair.left_path, pair.right_path)]
            first_path = root/'photo.jpg'
            Image.fromarray(np.concatenate(arrays, axis=1)).save(first_path, quality=98, subsampling=0)
            first = source_from_stereo_file(first_path, root)
            measured = process_source(first)
            suffix = deviation_filename_suffix(measured.state.disparity.total_permille)
            self.assertTrue(suffix)
            texture = arrays[0].copy(); texture[40:200, 75:285] = 128
            second_path = root/f'photo{suffix}.jpg'
            Image.fromarray(np.concatenate([texture, texture], axis=1)).save(second_path, quality=98, subsampling=0)
            second = source_from_stereo_file(second_path, root)
            session = browse_source(second); session.state.framing.crop_zoom_index = 8
            save_browsed_state(session)
            self.assertFalse(process_source(second).state.disparity.valid)
            result = run_batch([first, second], BatchRunOptions(output_folder=root/'output',
                               append_deviation_to_filename=True, save_anaglyph=False))
            self.assertEqual(result.exported_count, 1)
            self.assertEqual(len(result.failed), 1)
            self.assertIn('dieselbe Ausgabedatei', result.failed[0][1])

    def test_cancellation_after_render_writes_no_images(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = test_restart_alignment.RestartAlignmentTests().source(root)
            token = CancellationToken(); render = batch.render_final_pair
            def cancel(*args, **kwargs):
                pair = render(*args, **kwargs); token.cancel(); return pair
            with patch.object(batch, 'render_final_pair', side_effect=cancel):
                with self.assertRaises(JobCancelled):
                    run_batch([source], BatchRunOptions(output_folder=root/'output'), cancellation=token)
            self.assertFalse(list((root/'output').rglob('*.jpg')))

    def test_changed_source_is_rejected_before_old_edits_are_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = test_restart_alignment.RestartAlignmentTests().source(root)
            process_source(source); current = browse_source(source)
            current.state.manual.delta_x_px = 13; save_browsed_state(current)
            before = source.sidecar_path.read_bytes()
            for path in (source.left_path, source.right_path):
                with Image.open(path) as image: pixels = np.asarray(image.convert('RGB'))
                Image.fromarray(np.clip(pixels.astype(np.int16)+25,0,255).astype(np.uint8)).save(path)
            result = run_batch([source], BatchRunOptions(output_folder=root/'output',
                processing=ProcessingOptions(expected_source_stamp=current.source_stamp)))
            self.assertEqual(len(result.failed),1)
            self.assertFalse(result.items)
            self.assertEqual(source.sidecar_path.read_bytes(),before)
            self.assertFalse((root/'output').exists())

    def test_late_cancelled_alignment_preserves_saved_and_visible_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            source = test_restart_alignment.RestartAlignmentTests().source(Path(directory))
            current = test_restart_alignment.RestartAlignmentTests().edited(source)
            app = app_for(current)
            app.batch_mode = False
            app._processing_options = lambda **kwargs: ProcessingOptions(keep_loaded_pair=True, restart_alignment=True)
            app._t = lambda key, **kwargs: key
            jobs = []; app._start_worker = lambda kind, text, job: jobs.append(job)
            app._flush_state_save()
            before = source.sidecar_path.read_bytes()
            app.start_processing()
            def cancel(session, bounds, token, mode):
                token.cancel(); token.raise_if_cancelled()
            with patch.object(app, '_prepare_session_preview', side_effect=cancel):
                with self.assertRaises(JobCancelled): jobs[0](CancellationToken(),lambda _:None)
            self.assertEqual(source.sidecar_path.read_bytes(),before)
            self.assertIs(app.current,current)
            self.assertEqual(current.state.manual.delta_x_px,15)

    def test_completed_analysis_is_persisted_at_gui_adoption_and_write_error_keeps_old_session(self):
        with tempfile.TemporaryDirectory() as directory:
            source = test_restart_alignment.RestartAlignmentTests().source(Path(directory))
            old = test_restart_alignment.RestartAlignmentTests().edited(source)
            processed = process_source(source, ProcessingOptions(save_sidecar=False, keep_loaded_pair=True,
                                                                  restart_alignment=True))
            session = replace(old, state=processed.state)
            app = app_for(old); app._finish_busy_common = lambda: 'analysis'
            app._t = lambda key, **kw:key
            app._refresh_control_states = app._release_sbs_suffix_focus = lambda:None
            prepared = app._prepare_session_preview(session, (240,180), CancellationToken())
            with patch('stereofine.gui.save_browsed_state', side_effect=PermissionError('denied')), \
                 patch('stereofine.gui.messagebox.showerror'):
                app._finish_worker_success(prepared)
            self.assertIs(app.current,old)
            self.assertEqual(load_sidecar(source.sidecar_path).document.manual['delta_x_px'],15)
            with patch('stereofine.gui.play_ready_sound'): app._finish_worker_success(prepared)
            self.assertIs(app.current,session)
            self.assertEqual(load_sidecar(source.sidecar_path).document.manual['delta_x_px'],0)

    def test_proxy_and_master_share_rectangle_through_crop_pan_and_offsets(self):
        loaded = loaded_pair(); bounds=(320,230)
        for correction in ({'rotation_deg':2.4,'scale':1.002,'vertical_shift_px':2.4},
                           {'rotation_deg':-.7,'scale':.998,'vertical_shift_px':-1.3,
                            'vergence_ready':True,'vergence_v_px':1.2,'vergence_h_px':.8,
                            'trapez_apply':{'enabled':True,'params':{'a_projective_x':.001,'b_projective_y':.002}}}):
            state=PairState(); state.color.enabled=False
            state.alignment.valid=True; state.alignment.correction=correction
            base=build_preview_base(loaded,state,max_width=320,max_height=230,apply_color=False)
            for aspect in ('original','maximum','1:1','16:9'):
                for zoom in (0,2,4):
                    for dx,dy,pan in ((3,1,0),(-7,-2,1000)):
                        with self.subTest(correction=correction,aspect=aspect,zoom=zoom,dx=dx,pan=pan):
                            state.framing.aspect=aspect; state.framing.crop_zoom_index=zoom
                            state.framing.pan_x_permille=pan; state.framing.pan_y_permille=-pan
                            state.manual.delta_x_px=dx; state.manual.delta_y_px=dy
                            proxy=render_preview_from_base(base,state,apply_color=False)
                            final=render_final_pair(loaded,deepcopy(state),apply_color=False)
                            fitted=fit_display_pair(*final[:2],bounds)
                            self.assertEqual(proxy.left.shape,fitted[0].shape)
                            self.assertEqual(proxy.right.shape,fitted[1].shape)

    def test_completed_colour_after_save_is_applied_and_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            session=colored_source(Path(directory)); app=app_for(session)
            session.state.framing.crop_zoom_index=8; session.state.framing.pan_x_permille=1000
            session.state.invalidate_disparity_for_framing()
            app._render_session_preview(session)
            before=app._preview_left_current.copy()
            save_browsed_state(session)
            result=run_batch([session.source],BatchRunOptions(output_folder=Path(directory)/'output'))
            self.assertFalse(result.failed); self.assertTrue(app._adopt_saved_result(result))
            native=prepare_native_preview(session.loaded_pair,deepcopy(session.state),native_key(session),
                                          app._preview_bounds(),CancellationToken())
            app._native_job_id='late'
            app._native_worker.messages.put(WorkerMessage('late',WorkerMessageKind.RESULT,native))
            app._poll_native_preview()
            self.assertEqual(before.shape,app._preview_left_current.shape)
            np.testing.assert_array_equal(app._preview_left_current,native[4][2][True][0])
            self.assertFalse(np.array_equal(before,app._preview_left_current))

    def test_background_colour_adoption_updates_existing_sidecar_but_pure_load_creates_none(self):
        with tempfile.TemporaryDirectory() as directory:
            session=colored_source(Path(directory)); app=app_for(session)
            session.state.framing.crop_zoom_index=2; session.state.invalidate_disparity_for_framing()
            save_browsed_state(session); app._state_dirty=False
            result=prepare_native_preview(session.loaded_pair,deepcopy(session.state),native_key(session),
                                          app._preview_bounds(),CancellationToken())
            app._native_cache,app._native_views=result[:3],result[4]
            app._apply_native_preview(); self.assertTrue(app._state_dirty)
            self.assertTrue(app._flush_state_save(explicit=True))
            saved=load_sidecar(session.source.sidecar_path).document.color
            self.assertTrue(saved['valid']); self.assertEqual(saved['basis'],session.state.color.basis)
        with tempfile.TemporaryDirectory() as directory:
            source=test_restart_alignment.RestartAlignmentTests().source(Path(directory))
            app=app_for(browse_source(source)); app._flush_state_save()
            self.assertFalse(source.sidecar_path.exists())

    def test_first_reverse_step_at_offset_boundary_moves_and_state_matches_render(self):
        session=SimpleNamespace(state=PairState(),loaded_pair=loaded_pair(),
                                sidecar=SidecarLoadResult(SidecarStatus.MISSING))
        session.state.color.enabled=False; session.state.manual.delta_x_px=1000
        app=app_for(session)
        self.assertEqual(session.state.effective_offset_x_px,718)
        first=render_final_pair(session.loaded_pair,deepcopy(session.state),apply_color=False)[0]
        app._schedule_status_refresh=lambda:None
        app._adjust_manual_offset(-1,0)
        self.assertEqual(session.state.effective_offset_x_px,717)
        second=render_final_pair(session.loaded_pair,deepcopy(session.state),apply_color=False)[0]
        self.assertNotEqual(first.shape,second.shape)

    def test_function_keys_work_in_suffix_editor_without_interfering_with_typing(self):
        app=test_preview_stability.PreviewStabilityTests().app(); calls=[]
        editor=SimpleNamespace(winfo_class=lambda:'Entry',cget=lambda key:'normal')
        handler=app._shortcut_handler(lambda event:calls.append(event.keysym))
        for key in ('F1','F11','a','Left'): handler(SimpleNamespace(widget=editor,keysym=key))
        self.assertEqual(calls,['F1','F11'])

    def test_settings_write_failure_keeps_checkbox_and_image_in_sync(self):
        app=test_preview_stability.PreviewStabilityTests().app(); app.settings=AppSettings()
        values=dict(analysis_method='AKAZE',color_match_enabled=False,output_aspect='original',
                    use_input_subfolder=True,append_deviation_to_filename=False,gray_anaglyph=False,
                    save_cross=False,tiff_sbs=False,save_anaglyph=True,use_custom_sbs_suffix=False)
        for key,value in values.items(): setattr(app,key,SimpleNamespace(get=lambda value=value:value))
        app._schedule_state_save=lambda **kw:None; app._refresh_preview=lambda:None
        app._t=lambda key,**kw:key
        with patch('stereofine.gui.save_settings',side_effect=PermissionError('denied')), \
             patch('stereofine.gui.messagebox.showerror') as error:
            app._on_color_match_changed()
        self.assertFalse(app.current.state.color.enabled); error.assert_called_once()

    def test_failed_sidecar_save_allows_explicit_discard_on_close(self):
        app=test_preview_stability.PreviewStabilityTests().app(); destroyed=[]
        app._commit_sbs_suffix=lambda **kw:True; app._flush_state_save=lambda **kw:False
        app._state_save_error='denied'; app._t=lambda key,**kw:key
        app._cancel_disparity_refresh=app._persist_settings=lambda:None
        app.worker=SimpleNamespace(cancel_all=lambda:None); app.destroy=lambda:destroyed.append(True)
        with patch('stereofine.gui.messagebox.askyesno',return_value=False): app._on_close()
        self.assertFalse(destroyed)
        with patch('stereofine.gui.messagebox.askyesno',return_value=True): app._on_close()
        self.assertEqual(destroyed,[True])

    def test_export_failure_has_one_final_report_record(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); source=test_restart_alignment.RestartAlignmentTests().source(root)
            records=[]; writer=batch.write_analysis_report
            def capture(path,rows,**kw): records.extend(rows); return writer(path,rows,**kw)
            with patch.object(batch,'save_pair_outputs',side_effect=OSError('denied')), \
                 patch.object(batch,'write_analysis_report',side_effect=capture):
                result=run_batch([source],BatchRunOptions(output_folder=root/'output',report_path=root/'report.txt'))
            self.assertEqual(len(result.failed),1); self.assertEqual(len(records),1)
            self.assertEqual(records[0].status,'error')

    def test_sample_first_fit_is_identical_to_full_float_reference(self):
        rng=np.random.default_rng(65); budget=5000
        for dtype in (np.uint8,np.uint16,np.float32):
            a=rng.random((90,110,3),dtype=np.float32)
            if dtype != np.float32: a=(a*np.iinfo(dtype).max).astype(dtype)
            b=np.roll(a,11,axis=1)
            def reference(image):
                peak=1 if dtype==np.float32 else np.iinfo(dtype).max
                full=np.clip(image.astype(np.float32)/np.float32(peak),0,1).reshape(-1,3)
                return full[np.linspace(0,len(full)-1,budget,dtype=np.intp)].reshape(-1,1,3)
            expected=fit_symmetric_color_transfer(reference(a),reference(b),max_samples=budget)
            self.assertEqual(fit_symmetric_color_transfer(a,b,max_samples=budget),expected)

    def test_viewport_resize_reuses_native_pixels_without_rendering_master(self):
        app=test_preview_stability.PreviewStabilityTests().app(); app.current.loaded_pair=loaded_pair()
        result=prepare_native_preview(app.current.loaded_pair,deepcopy(app.current.state),native_key(app.current),
                                      (300,200),CancellationToken())
        app._native_cache,app._native_views=result[:3],result[4]
        app.current.state.color=deepcopy(result[3]); app._preview_bounds=lambda:(600,400)
        results=[]
        def start(fn,**kw): results.append(fn(CancellationToken(),lambda _:None)); return SimpleNamespace(job_id='fit')
        app._native_worker=SimpleNamespace(start=start)
        with patch.object(native_preview,'render_final_pair',side_effect=AssertionError('master render on resize')):
            app._start_native_preview()
        self.assertEqual(results[0][4][4],(600,400))
        for actual,wanted in zip(results[0][4][2][app.current.state.color.enabled],fit_display_pair(*result[1:3],(600,400))):
            np.testing.assert_array_equal(actual,wanted)

    def test_job_directory_index_scans_once_and_detects_later_duplicate(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            sources=[]
            for i in range(20):
                path=root/f'{i:02d}.jpg'; Image.new('RGB',(24,8)).save(path)
                sources.append(source_from_stereo_file(path,root))
            index=SourceDirectoryIndex(); real=Path.iterdir; visits=[]
            def count(folder):
                for entry in real(folder): visits.append(entry); yield entry
            with patch.object(Path,'iterdir',count):
                for source in sources: load_source(source,directory_index=index)
            self.assertEqual(len(visits),20)
            Image.new('RGB',(24,8)).save(root/'00.png')
            with self.assertRaises(InputError): load_source(sources[0],directory_index=index)
