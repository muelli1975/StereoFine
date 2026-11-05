"""Native GUI checks for momentary 100% inspection, DPI and colour refresh."""
from copy import deepcopy
import json
from pathlib import Path
import platform
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

import customtkinter as ctk
import numpy as np
from PIL import ImageGrab

from stereofine import gui
from stereofine.inputs import LoadedStereoPair
from stereofine.native_preview import detail_box, native_key, native_geometry_key
from stereofine.render import render_final_pair
from stereofine.session import browse_source
from stereofine.processing import process_source
from stereofine.settings import AppSettings
from tests.gui_cross_measurement import pump
from tests.test_restart_alignment import RestartAlignmentTests


def final_correction_checks(app, checks, language):
    # Non-trivial geometry exposed the old colour-toggle crop change.
    app.current.state.alignment.valid = True
    app.current.state.alignment.correction = {'rotation_deg': .6, 'scale': 1.002, 'vertical_shift_px': 2.4}
    for aspect in ('original', 'maximum', '1:1', '16:9'):
        app.current.state.framing.aspect = aspect
        app.current.state.framing.crop_zoom_index = 1
        app.current.state.color.enabled = False
        app._sync_vars_from_current(); app._refresh_preview(rebuild_base=True)
        pump(app, lambda: app._native_cache is not None and app._native_cache[0] == native_key(app.current)
             and app._native_job_id is None and not app._native_views_need_resize())
        geometry = native_geometry_key(app.current)
        for mode in ('Farbig', 'Graustufen', 'Kreuzblick'):
            app.preview_mode.set(mode); app._on_preview_mode_changed()
            off = app._preview_pil.copy()
            for enabled in (True, False):
                app.color_match_enabled.set(enabled); app._on_color_match_changed()
                shape = app._preview_pair_shape
                expected = app._native_views[2][enabled]
                masked = app._mask_preview_pair(*expected)
                np.testing.assert_array_equal(app._preview_left_current, masked[0])
                assert native_geometry_key(app.current) == geometry
                stable = app._preview_pil.copy()
                pump(app, lambda: app._native_cache is not None and app._native_cache[0] == native_key(app.current)
                     and app._native_job_id is None)
                assert app._preview_pair_shape == shape
                np.testing.assert_array_equal(np.asarray(app._preview_pil), np.asarray(stable))
            np.testing.assert_array_equal(np.asarray(app._preview_pil), np.asarray(off))
        checks.append(dict(language=language,aspect=aspect,color_toggle_same_master_crop=True,
                           all_preview_modes=True,no_delayed_color_toggle_jump=True))
    # Let Tk process real scheduled release guards, including repeat pairs.
    app.preview_mode.set('Farbig'); app._on_preview_mode_changed()
    for mode in ('measure', 'left', 'right', 'top', 'bottom'):
        for direction in ('left', 'right', 'up', 'down'):
            if mode == 'measure':
                app._on_measure_press()
            else:
                app._set_floating_key(mode)
            app._on_arrow(direction)
            before = deepcopy(app.current.state)
            if mode == 'measure':
                app._on_measure_release()
            else:
                app._clear_floating_key(mode)
            app.update_idletasks()
            for _ in range(5): app._on_arrow(direction)
            assert app.current.state == before
            app._on_arrow_release(SimpleNamespace(keysym=direction.title()))
            app._on_arrow(direction)  # synthetic X11 release/press
            assert app.current.state == before
            app._on_arrow_release(SimpleNamespace(keysym=direction.title()))
            app.update_idletasks()
            app._on_arrow(direction)
            assert app.current.state.manual != before.manual
    app._reset_keyboard_modes()
    checks.append(dict(language=language,held_arrows_remain_view_only=True,
                       physical_release_restores_manual_editing=True,all_m_and_window_modes=True))


def main():
    checks=[]
    with tempfile.TemporaryDirectory() as td:
        source=RestartAlignmentTests().source(Path(td))
        for language in ('de','en'):
            with patch.object(gui,'load_settings',return_value=AppSettings(language=language)), \
                    patch.object(gui,'save_settings'):
                app=gui.StereoFineApp()
                try:
                    pump(app,lambda:app._preview_pil is not None)
                    app.current=browse_source(source)
                    app.sources, app.source_index=[source],0
                    # A source wider than the screen proves native sampling;
                    # its fine pattern is absent from the reduced fit proxy.
                    h,w=1200,2600
                    x=np.arange(w,dtype=np.uint16)[None,:]
                    y=np.arange(h,dtype=np.uint16)[:,None]
                    pixels=np.empty((h,w,3),np.uint8)
                    pixels[:,:,0]=x%251;pixels[:,:,1]=y%241;pixels[:,:,2]=(x+y)%239
                    old=app.current.loaded_pair
                    app.current.loaded_pair=LoadedStereoPair(
                        pixels,pixels.copy(),old.left_path,old.right_path,'pair',w,h,w,h,w,h)
                    app._sync_vars_from_current();app._refresh_preview();app._refresh_control_states()
                    app.tiff_sbs.set(True);app._persist_settings()
                    assert app.settings.tiff_sbs
                    assert app.tiff_sbs_box.cget('text')==app._t('tiff_sbs')
                    app.preview_mode.set('Kreuzblick');app._on_preview_mode_changed()
                    pump(app,lambda:app._native_cache is not None and
                         app._native_cache[0]==native_key(app.current))
                    before=deepcopy(app.current.state)
                    for scale in (1.,1.25,1.5,2.):
                        ctk.set_widget_scaling(scale);ctk.set_window_scaling(scale)
                        app.geometry('1400x900');app.update()
                        app._on_detail_press()
                        pump(app,lambda:app._native_cache is not None and
                             app._native_cache[0]==native_key(app.current))
                        app._show_detail_preview()
                        image=app._preview_ctk_image.cget('light_image')
                        factor=app.preview_label._get_widget_scaling()
                        assert app._preview_ctk_image._get_scaled_size(factor)==image.size
                        _,left,right=app._native_cache
                        bounds=app._preview_bounds()
                        box,_=detail_box(left.shape,(bounds[0]//2,bounds[1]),app._detail_center)
                        x0,y0,x1,y1=box
                        expected=np.concatenate([right[y0:y1,x0:x1],left[y0:y1,x0:x1]],axis=1)
                        np.testing.assert_array_equal(np.asarray(image),expected)
                        previous=app._detail_center
                        app._on_arrow('left')
                        assert app._detail_center[0] >= previous[0]-1
                        assert app.current.state==before
                        app._end_detail_preview()
                        assert app._handle_detail_arrow('left')  # held key remains view-only
                        app._on_arrow_release(SimpleNamespace(keysym='Left'))
                        app.update()
                        assert not app._handle_detail_arrow('left')
                        fitted = app._preview_ctk_image.cget('light_image')
                        assert app._preview_ctk_image._get_scaled_size(factor) == fitted.size
                        bounds = app._preview_bounds()
                        assert fitted.width <= bounds[0] and fitted.height <= bounds[1]
                        app._on_detail_press();app._reset_keyboard_modes()
                        assert not app.detail_active
                        checks.append(dict(language=language,scale=scale,native_pixels=True,
                                           synchronous_eyes=True,fine_tap=True,edits_preserved=True,fit_returns_inside_bounds=True))
                    ctk.set_widget_scaling(1.);ctk.set_window_scaling(1.)
                    # Native background fit and exported master fit must agree
                    # after the final crop changes, without blocking key input.
                    app.current.state.color.enabled=True
                    app.current.state.framing.aspect='1:1'
                    app._refresh_preview()
                    pump(app,lambda:app._native_cache is not None and
                         app._native_cache[0]==native_key(app.current))
                    expected=deepcopy(app.current.state)
                    render_final_pair(app.current.loaded_pair,expected)
                    assert app.current.state.color.parameters==expected.color.parameters
                    assert app.current.state.color.basis==expected.color.basis
                    # Mask edits must not invalidate the native image or swap
                    # to a proxy while their delayed sidecar write completes.
                    for mode in ('Farbig', 'Graustufen', 'Kreuzblick'):
                        app.preview_mode.set(mode);app._on_preview_mode_changed()
                        app._adjust_floating_edge('bottom', 5-app.current.state.floating_window.bottom_permille)
                        stable=app._preview_pil.copy()
                        cached=app._native_cache
                        since=time.monotonic()
                        pump(app,lambda:time.monotonic()-since>.4)
                        np.testing.assert_array_equal(np.asarray(app._preview_pil),np.asarray(stable))
                        assert app._native_cache is cached
                    # The detail view has the same timed acceleration as M.
                    app._on_detail_press()
                    app._detail_center=(app._native_cache[1].shape[1]/2,app._native_cache[1].shape[0]/2)
                    app._on_arrow('right')
                    tapped=app._detail_center[0]
                    for _ in range(10):app._on_arrow('right')
                    assert app._detail_center[0]==tapped
                    since=time.monotonic()
                    pump(app,lambda:time.monotonic()-since>.9)
                    assert app._detail_center[0]>tapped+100
                    app._on_arrow_release(SimpleNamespace(keysym='Right'));app.update()
                    stopped=app._detail_center
                    since=time.monotonic();pump(app,lambda:time.monotonic()-since>.1)
                    assert app._detail_center==stopped
                    app._end_detail_preview()
                    checks.append(dict(language=language,window_preview_stable=True,accelerated_pan=True,release_stops=True))
                    # Recover from one actual worker failure without retrying
                    # continuously while Z remains held.
                    app.current.state.color.enabled=False
                    app._native_cache=None
                    calls=[]
                    def fail_once(*args,**kwargs):
                        calls.append(1)
                        if len(calls)==1:
                            raise RuntimeError('Simulated transient detail render error')
                        return render_final_pair(*args,**kwargs)
                    with patch('stereofine.native_preview.render_final_pair',side_effect=fail_once):
                        app._on_detail_press()
                        pump(app,lambda:app._native_failed_key==native_key(app.current))
                        for _ in range(5):app._on_detail_press()
                        since=time.monotonic();pump(app,lambda:time.monotonic()-since>.1)
                        assert len(calls)==1
                        app._end_detail_preview();app._on_detail_press()
                        pump(app,lambda:app._native_cache is not None and app._native_cache[0]==native_key(app.current))
                        assert len(calls)==2 and app._native_failed_key is None
                    # Panning into an edge reuses the displayed image. Moving
                    # away, changing modes or refreshing a grid still redraws.
                    for mode in ('Farbig','Graustufen','Kreuzblick'):
                        app.preview_mode.set(mode);app._on_preview_mode_changed()
                        for direction in ('left','right','up','down'):
                            app._move_detail(direction,1e6)
                            image=app._preview_ctk_image;position=app._detail_center
                            for _ in range(10):app._move_detail(direction,25)
                            assert app._preview_ctk_image is image and app._detail_center==position
                            reverse={'left':'right','right':'left','up':'down','down':'up'}[direction]
                            app._move_detail(reverse,1)
                            assert app._preview_ctk_image is not image
                        image=app._preview_ctk_image
                        app.grid_mode.set('Weiß');app._update_preview_display()
                        assert app._preview_ctk_image is not image
                        app.grid_mode.set('Aus')
                    app._end_detail_preview()
                    app.current.state.color.enabled=True;app._refresh_preview()
                    pump(app,lambda:app._native_cache is not None and app._native_cache[0]==native_key(app.current))
                    checks.append(dict(language=language,detail_error_retry=True,no_error_retry_loop=True,
                                       edge_reuses_image=True,edge_reverse_moves=True,overlays_still_refresh=True))
                    app.show_shortcuts_help()
                    app.update()
                    screenshot=Path('build')/f'gui-tiff-detail-{platform.system()}-{language}.png'
                    screenshot.parent.mkdir(parents=True,exist_ok=True)
                    try: ImageGrab.grab().save(screenshot)
                    except OSError: pass
                    app._close_shortcuts_help()
                    checks.append(dict(language=language,final_crop_color_consistent=True,tiff_option=True))
                    final_correction_checks(app, checks, language)
                finally:
                    app._native_worker.cancel_all()
                    app._cancel_disparity_refresh();app.destroy()
        # Exercise real Save, including its worker and persisted colour state.
        process_source(source)
        with patch.object(gui,'load_settings',return_value=AppSettings()), patch.object(gui,'save_settings'), \
                patch.object(gui,'play_ready_sound'), patch.object(gui.messagebox,'showwarning'):
            app=gui.StereoFineApp()
            try:
                app.current=browse_source(source)
                app.current.state.color.enabled=True
                app.sources,app.source_index=[source],0
                app._sync_vars_from_current();app._refresh_control_states();app._refresh_preview()
                pump(app,lambda:app._native_cache is not None and app._native_cache[0]==native_key(app.current))
                app._adjust_floating_edge('bottom',5-app.current.state.floating_window.bottom_permille)
                app._detail_center=(179,117)
                app._effective_output_folder=lambda _root:Path(td)/'output'
                app._flush_state_save(explicit=True)
                since=time.monotonic();pump(app,lambda:time.monotonic()-since>.4)
                stable=app._preview_pil.copy();session=app.current;cache=app._native_cache
                for tiff in (False,True):
                    app.tiff_sbs.set(tiff);app.save_current_result()
                    pump(app,lambda:app.busy_state=='idle',timeout=45)
                    np.testing.assert_array_equal(np.asarray(app._preview_pil),np.asarray(stable))
                    assert app.current is session and app._native_cache is cache
                    assert app._detail_center==(179,117)
                    assert app.current.state.floating_window.bottom_permille==5
                    extension='tif' if tiff else 'jpg'
                    assert (Path(td)/'output'/'sbs'/f'{source.base_name}_sbs.{extension}').is_file()
                checks.append(dict(real_jpeg_and_tiff_save=True,preview_pixels_unchanged=True,detail_position_preserved=True))
            finally:app.destroy()
        ctk.set_widget_scaling(1.);ctk.set_window_scaling(1.)
    output=Path('build')/f'gui-tiff-detail-{platform.system()}.json'
    output.write_text(json.dumps(dict(ok=True,checks=checks),indent=2),encoding='utf-8')
    print(output.read_text())


if __name__=='__main__':main()
