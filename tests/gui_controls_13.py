"""Hidden native GUI checks for the 1.3 input and colour workflow."""
from __future__ import annotations

import _tkinter
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

import stereofine.gui as gui
from stereofine.inspection import measured_deviation
from stereofine.looks import builtin_looks
from stereofine.processing import ProcessingOptions, process_source
from stereofine.settings import AppSettings
from stereofine.sources import source_from_pair


def pump(app, predicate=lambda: True, timeout=45):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        # A withdrawn Aqua window can keep feeding events to Tcl's update.
        for _ in range(32):
            if not app.tk.dooneevent(_tkinter.ALL_EVENTS | _tkinter.DONT_WAIT):
                break
        if predicate(): return
        time.sleep(.01)
    raise TimeoutError(f'GUI timeout: {app.busy_state}, {app.current_job_kind}')


def main():
    messages=[];errors=[];settings_writes=[]
    settings=AppSettings(color_match_enabled=False)
    gui.load_settings=lambda: settings
    gui.save_settings=lambda value: settings_writes.append(asdict(value))
    gui.messagebox.showerror=lambda _title,text: messages.append(str(text))
    gui.messagebox.showwarning=lambda _title,text: messages.append(str(text))
    gui.messagebox.showinfo=lambda _title,text: messages.append(str(text))
    gui.StereoFineApp._load_start_image=lambda self: None
    root=Path(__file__).resolve().parents[1]
    output=root/'build/checks-13';output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='sf13-controls-') as td:
        folder=Path(td)
        rng=np.random.default_rng(313)
        left=cv2.GaussianBlur(rng.integers(0,256,(640,1024,3),np.uint8),(5,5),0)
        for _ in range(70):
            x,y=rng.integers([10,10],[1010,630])
            cv2.circle(left,(int(x),int(y)),int(rng.integers(2,8)),
                       tuple(int(v) for v in rng.integers(0,256,3)),-1)
        right=cv2.warpAffine(left,np.float32([[1,0,8],[0,1,0]]),(1024,640),
                             borderMode=cv2.BORDER_REFLECT)
        for name,pixels in [('scene_l.png',left),('scene_r.png',right)]:
            Image.fromarray(pixels).save(folder/name)
        source=source_from_pair(folder/'scene_l.png',folder/'scene_r.png',folder)
        app=gui.StereoFineApp()
        app.withdraw()  # never show a test window on the user's desktop
        app.report_callback_exception=lambda *exc: errors.append(repr(exc))
        try:
            pump(app)
            app._set_source_collection([source],0,batch=False)
            pump(app,lambda: app.busy_state=='idle' and app.current is not None)
            pump(app,lambda: app._detail_texture_cache is not None)
            assert app.deviation_points_box.cget('text')=='Nah-/Fernpunkte anzeigen'
            assert int(app.deviation_points_box.grid_info()['row']) < int(app.grid_spacing_menu.grid_info()['row'])
            assert int(app.defaults_button.grid_info()['row']) > int(app.grid_spacing_menu.grid_info()['row'])
            assert len(builtin_looks()) == 25
            assert app.look_menu.cget('values')[:2] == ['Dia kräftig', 'Analog sanft']
            assert app.look_choice.get() == 'Dia kräftig'
            assert not app.current.state.look.enabled
            app.look_checkbox.toggle()
            assert app.current.state.look.enabled and app.current.state.look.preset_id == 'velvia50'
            app.look_checkbox.toggle()

            app._on_look_selected('Blue House')
            app.look_enabled.set(True);app._on_look_enabled()
            app._on_look_strength(43)
            pump(app,lambda: app.busy_state == 'idle' and app._detail_texture_cache is not None and
                 app._detail_texture_cache[0]==app._detail_texture_signature())
            assert app.current.state.look.enabled and app.current.state.look.strength==.43
            assert app.look_slider.cget('state')=='normal'
            pump(app, lambda: app._look_settings_job is None)
            assert app._flush_state_save()
            sidecar_before = source.sidecar_path.read_bytes()
            look_before = asdict(app.current.state.look)
            writes_before = len(settings_writes)
            menu = app.look_menu
            menu._open_dropdown_menu()
            assert menu.popup is not None
            assert [widget.cget('text') for widget in menu._popup_frame.winfo_children()
                    if isinstance(widget, gui.ctk.CTkLabel)] == [
                'Farbfilm & Sofortbild', 'Schwarzweiß & Sepia', 'Kino', 'Licht & Stimmung',
            ]
            menu._activate(menu.cget('values').index('Vintage 35 mm'), preview=False)
            menu._step(1)
            assert menu._popup_buttons[menu._active_index].cget('text') == 'Cinema'
            menu._activate(menu.cget('values').index('Matrix'))
            pump(app, lambda: getattr(app._look_hover_state, 'preset_id', None) == 'matrix')
            assert app._look_hover_state.preset_id == 'matrix'
            assert asdict(app.current.state.look) == look_before
            assert source.sidecar_path.read_bytes() == sidecar_before
            assert len(settings_writes) == writes_before
            app._on_escape()
            assert app._look_hover_state is None and menu.popup is None
            menu._open_dropdown_menu()
            menu._activate(menu.cget('values').index('Matrix'))
            menu.close_popup()
            assert app._look_hover_job is None
            menu._open_dropdown_menu()
            menu._choose(menu.cget('values').index('Matrix'))
            assert app.current.state.look.preset_id == 'matrix'
            menu._open_dropdown_menu()
            menu._activate(menu.cget('values').index('Blue House'))
            pump(app, lambda: getattr(app._look_hover_state, 'preset_id', None) == 'blue_house')
            with patch('stereofine.look_controls.filedialog.askopenfilename', return_value='') as choose_file:
                menu._choose(menu.cget('values').index('Import (.cube, .png)'))
            choose_file.assert_called_once()
            assert app._look_hover_state is None, app._look_hover_state
            assert app.current.state.look.preset_id == 'matrix', app.current.state.look
            assert app._flush_state_save()
            assert json.loads(source.sidecar_path.read_text('utf-8'))['look']['preset_id'] == 'matrix'
            geometry=(asdict(app.current.state.framing),asdict(app.current.state.manual),
                      asdict(app.current.state.floating_window))
            app._zoom_inspection(2)
            pump(app,lambda: app._inspection_view.active and app._view_source_box is not None)
            scale=app._inspection_view.scale;center=app._inspection_view.center
            app._on_detail_press();pump(app,lambda: app.detail_active)
            app._end_detail_preview();pump(app)
            assert app._inspection_view.active and app._inspection_view.scale==scale
            assert app._inspection_view.center==center
            assert geometry==(asdict(app.current.state.framing),asdict(app.current.state.manual),
                              asdict(app.current.state.floating_window))

            app._measure_tool_var.set(True);app._toggle_point_measurement()
            box=app._view_source_box
            x=(box[0]+box[2])/2;y=(box[1]+box[3])/2
            for index, px in enumerate((x,x+10)):
                dw,dh=app._preview_display_size
                label=app.preview_label._label
                event=SimpleNamespace(x_root=label.winfo_rootx()+(label.winfo_width()-dw)/2+
                    (px-box[0])/(box[2]-box[0])*dw,
                    y_root=label.winfo_rooty()+(label.winfo_height()-dh)/2+(y-box[1])/(box[3]-box[1])*dh)
                if index == 0:
                    app._on_view_measure_click(event)
                else:
                    app._on_view_double_click(event)
            assert len(app._point_measurements)==2
            measured=measured_deviation(*app._point_measurements,app._view_native_size[0])
            assert abs(measured-10000/1024)<1e-6,measured
            app._on_escape()
            assert not app._measure_tool_var.get() and app._inspection_view.active
            app._on_view_double_click(None);pump(app)
            assert not app._inspection_view.active
            assert app._flush_state_save()
            saved=json.loads(source.sidecar_path.read_text('utf-8'))
            assert saved['look']['strength']==.43

            app.show_deviation_points.set(True);app._on_deviation_option_changed()
            app.start_processing()
            pump(app,lambda: app.busy_state=='idle' and app.current.state.alignment.valid,timeout=90)
            assert app.current.state.disparity.endpoints.get('coordinate_system')=='aligned_master'
            pump(app)
            app._preview_ctk_image._light_image.save(output/'near-far-preview.png')

            help_sizes = {}
            for language in ('de','en'):
                app.settings.language=language;app._rebuild_for_language();pump(app)
                assert app._t('help_heading')==('Bedienhilfe' if language=='de' else 'Controls')
                if language == 'en':
                    assert list(app.look_menu.section_headers.values()) == [
                        'Color & Instant Film', 'Monochrome & Sepia', 'Cinema', 'Light & Mood',
                    ]
                    assert app.look_menu.cget('values')[15] == 'Rose Gold'
                with patch('stereofine.controls_guide.work_area', return_value=(0, 0, 1920, 1040)):
                    app.show_shortcuts_help()
                window=app._shortcut_help_window;window.withdraw();pump(app)
                assert window.winfo_exists()
                width, height = window.initial_window_size
                assert window.initial_content_height + 100*window.scale <= height
                help_sizes[language] = [width, height, window.initial_columns]
                app._on_escape();assert app._shortcut_help_window is None

            for name,pixels in [('second_l.png',left),('second_r.png',right)]:
                Image.fromarray(pixels).save(folder/name)
            other = source_from_pair(folder/'second_l.png',folder/'second_r.png',folder)
            assert app._flush_state_save()
            app.show_folder_settings()
            dialog = app._folder_dialog
            assert len(dialog.sources) == 2
            assert not any(value.get() for value in dialog.selection.values())
            assert dialog.apply_button.cget('state') == 'disabled'
            dialog.update_idletasks()
            button_row = dialog.apply_button.master
            initial_button_y = button_row.winfo_y()
            initial_dialog_height = dialog.winfo_reqheight()
            assert initial_button_y > 0
            assert dialog.progress.cget('fg_color') == '#181818'
            dialog.selection['look'].set(True)
            dialog._changed()
            assert dialog.apply_button.cget('state') == 'normal'
            dialog.start()
            dialog.update_idletasks()
            assert button_row.winfo_y() == initial_button_y
            assert dialog.winfo_reqheight() == initial_dialog_height
            assert dialog.progress.cget('fg_color') == '#333333'
            assert dialog.cancel_button.cget('state') == 'normal'
            pump(app, lambda: app.busy_state == 'idle' and app._folder_dialog is None)
            saved_other = json.loads(other.sidecar_path.read_text('utf-8'))
            assert saved_other['preference_fields'] == ['look']
            assert saved_other['look']['preset_id'] == 'matrix'
            assert app.current.source == source and app.current.state.alignment.valid
            assert app._folder_feedback

            app.settings.custom_output_folder=str(folder/'chosen-output')
            app.settings.use_input_output_subfolder=False
            app.use_input_subfolder.set(False)
            before_defaults = source.sidecar_path.read_bytes()
            app.restore_program_defaults();pump(app)
            assert app.settings.custom_output_folder==str(folder/'chosen-output')
            assert not app.use_input_subfolder.get()
            assert app.current.state.look.enabled and app.current.state.look.preset_id == 'matrix'
            assert app.look_slider.cget('state')=='normal'
            assert not app.current.state.color.enabled and app.settings.color_match_enabled
            assert not app.settings.look_enabled and source.sidecar_path.read_bytes() == before_defaults
            assert not app.show_deviation_points.get()
            app.use_custom_sbs_suffix.set(False)
            app._refresh_control_states()
            assert app.sbs_suffix_menu.cget('state') == 'normal'
            app._activate_sbs_suffix()
            assert app.use_custom_sbs_suffix.get()
            app.look_checkbox.toggle()
            assert not app.look_enabled.get()
            app.look_menu._open_dropdown_menu()
            assert app.look_enabled.get() and app.look_menu.popup is not None
            app._on_escape()

            for name, pixels in [('third_l.png', left), ('third_r.png', right)]:
                Image.fromarray(pixels).save(folder/name)
            third = source_from_pair(folder/'third_l.png', folder/'third_r.png', folder)
            app.left_orientation.set('180'); app.right_orientation.set('180')
            app._on_input_transform_changed()
            app._set_source_collection([source, other, third], 0, batch=True)
            pump(app, lambda: app.busy_state == 'idle' and app.current.source == source)
            series_path = source.sidecar_path.with_name('series.json')
            assert not series_path.exists()
            app.show_folder_settings()
            dialog = app._folder_dialog
            dialog.selection['series_input'].set(True)
            dialog._changed()
            dialog.start()
            pump(app, lambda: app.busy_state == 'idle' and app._folder_dialog is None)
            assert json.loads(series_path.read_text('utf-8'))['input_state']['left_orientation'] == '180'
            assert json.loads(other.sidecar_path.read_text('utf-8')) == saved_other
            app.next_source()
            pump(app, lambda: app.busy_state == 'idle' and app.current.source == other)
            assert app.left_orientation.get() == app.right_orientation.get() == '180'
            assert app.current.state.look.preset_id == 'matrix'
            batch_options = ProcessingOptions(save_sidecar=False)
            inherited = process_source(other, batch_options).state.input_transform
            assert inherited.left_orientation == inherited.right_orientation == '180'

            app.left_orientation.set('0'); app.right_orientation.set('0')
            app._on_input_transform_changed()
            assert app._flush_state_save()
            explicit = process_source(other, batch_options).state.input_transform
            assert explicit.left_orientation == explicit.right_orientation == '0'
            app.next_source()
            pump(app, lambda: app.busy_state == 'idle' and app.current.source == third)
            assert app.left_orientation.get() == app.right_orientation.get() == '180'
            app.previous_source()
            pump(app, lambda: app.busy_state == 'idle' and app.current.source == other)
            assert app.left_orientation.get() == app.right_orientation.get() == '0'
            assert app.series_input_button.cget('state') == 'normal'
            app.series_input_button.invoke()
            assert app.left_orientation.get() == app.right_orientation.get() == '180'
            assert app._flush_state_save()
            assert json.loads(other.sidecar_path.read_text('utf-8'))['input_override'] is False
            assert app.series_input_button.cget('state') == 'disabled'
            assert not messages,messages
            assert not errors,errors
            report=dict(loading=True,look_strength_sidecar=True,zoom_preserves_crop=True,
                        z_restores_view=True,measurement_zoom_invariant=True,escape_priority=True,
                        near_far_evidence=True,help_languages=['de','en'],defaults_keep_destination=True,
                        hover_preview=True,folder_apply=True,field_activation=True,help_sizes=help_sizes,
                        series_orientation=True,defaults_keep_image=True,folder_buttons_stable=True,
                        callback_errors=errors)
            (output/'gui-controls.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            print(json.dumps(report))
        finally:
            app.worker.cancel_all();app.measurement_worker.cancel_all();app.destroy()


if __name__=='__main__':main()
