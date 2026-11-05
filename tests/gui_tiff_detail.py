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
from stereofine.native_preview import detail_box, native_key, DETAIL_STEP_PX
from stereofine.render import render_final_pair
from stereofine.session import browse_source
from stereofine.settings import AppSettings
from tests.gui_cross_measurement import pump
from tests.test_restart_alignment import RestartAlignmentTests


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
                        assert app._detail_center[0] >= previous[0]-DETAIL_STEP_PX
                        assert app.current.state==before
                        app._end_detail_preview()
                        assert app._handle_detail_arrow('left')  # held key remains view-only
                        app._on_arrow_release(SimpleNamespace(keysym='Left'))
                        app.update()
                        assert not app._handle_detail_arrow('left')
                        app._on_detail_press();app._reset_keyboard_modes()
                        assert not app.detail_active
                        checks.append(dict(language=language,scale=scale,native_pixels=True,
                                           synchronous_eyes=True,fixed_steps=True,edits_preserved=True))
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
                    app.show_shortcuts_help()
                    app.update()
                    screenshot=Path('build')/f'gui-tiff-detail-{platform.system()}-{language}.png'
                    screenshot.parent.mkdir(parents=True,exist_ok=True)
                    try: ImageGrab.grab().save(screenshot)
                    except OSError: pass
                    app._close_shortcuts_help()
                    checks.append(dict(language=language,final_crop_color_consistent=True,tiff_option=True))
                finally:
                    app._native_worker.cancel_all()
                    app._cancel_disparity_refresh();app.destroy()
        ctk.set_widget_scaling(1.);ctk.set_window_scaling(1.)
    output=Path('build')/f'gui-tiff-detail-{platform.system()}.json'
    output.write_text(json.dumps(dict(ok=True,checks=checks),indent=2),encoding='utf-8')
    print(output.read_text())


if __name__=='__main__':main()
