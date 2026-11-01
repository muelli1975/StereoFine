"""Real-window checks for lost key releases and the optional output-name checkbox."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk

from PIL import Image

import stereofine.gui as gui
from stereofine.session import browse_source, source_from_selected_stereo_file
from stereofine.settings import AppSettings


def pump(app, seconds=.2):
    deadline = time.monotonic()+seconds
    while time.monotonic() < deadline:
        app.update()
        time.sleep(.01)


def main():
    settings = AppSettings()
    saved = []
    gui.load_settings = lambda: settings
    gui.save_settings = lambda value: saved.append(value.to_dict())
    app = gui.StereoFineApp()
    focus_events = []
    def record_focus(event):
        focus_events.append(dict(type=str(event.type), widget=str(event.widget),
                                 focus=str(app.focus_get()), pending=app._keyboard_focus_after_id))
    app.bind_all('<FocusIn>', record_focus, add='+')
    app.bind_all('<FocusOut>', record_focus, add='+')
    reset_focus = app._reset_keyboard_if_unfocused
    def traced_reset():
        focused = app.focus_get()
        focus_events.append(dict(reset='before', focus=str(focused), top=str(focused.winfo_toplevel()) if focused is not None else None, same=focused.winfo_toplevel() is app if focused is not None else None, floating=app._floating_key_edge))
        reset_focus()
        focus_events.append(dict(reset='after', floating=app._floating_key_edge))
    app._reset_keyboard_if_unfocused = traced_reset
    import traceback
    set_key = app._set_floating_key
    def traced_set(edge, event=None):
        focus_events.append(dict(set_key=edge, event=str(event), stack=traceback.format_stack(limit=5)))
        return set_key(edge, event)
    app._set_floating_key = traced_set
    other = None
    with tempfile.TemporaryDirectory(prefix='sf-keyboard-filename-') as temporary:
        root = Path(temporary)
        try:
            pump(app, .5)
            path = root/'scene.jpg'
            with Image.open(gui.asset_path('stereofine.jpg')) as image:
                image.resize((1000, round(image.height*1000/image.width))).save(path)
            source = source_from_selected_stereo_file(path)
            app.current = browse_source(source)
            app.sources, app.source_index = [source], 0
            app._sync_vars_from_current()
            app._refresh_control_states()
            app._refresh_preview()
            # Capture work that must survive all focus resets.
            state = app.current.state
            state.manual.delta_x_px, state.manual.delta_y_px = 17, -3
            app._schedule_state_save = lambda **kwargs: None
            app.focus_force()
            pump(app)
            assert app.focus_get() is not None

            # Moving between controls inside the main window must retain a held mode.
            entry = tk.Entry(app)
            entry.place(x=400, y=4, width=80)
            app._set_floating_key('top')
            entry.focus_force()
            pump(app)
            assert app._floating_key_edge == 'top'
            entry.destroy()
            app.focus_force()
            pump(app)

            # Reproduce a held L/R/T/B key whose release occurs in another window.
            other = tk.Toplevel(app)
            other.geometry('160x80+30+30')
            other.title('Focus regression test')
            app.focus_force()
            pump(app)
            app._set_floating_key('top')
            app._g_key_down = True
            app._shortcut_keys_down.add('f11')
            other.focus_force()
            pump(app)
            assert app.focus_get() is not None and app.focus_get().winfo_toplevel() is other
            assert app._floating_key_edge is None, dict(events=focus_events, focus=str(app.focus_get()),
                floating=app._floating_key_edge, pending=app._keyboard_focus_after_id,
                out_binding=app.bind('<FocusOut>'), in_binding=app.bind_all('<FocusIn>'))
            assert not app._g_key_down and not app._shortcut_keys_down
            assert (state.manual.delta_x_px, state.manual.delta_y_px) == (17, -3)
            app.focus_force()
            pump(app)
            for modifier, step in [(0, 1), (1, 5), (4, 10)]:
                before = state.manual.delta_x_px
                app.event_generate('<KeyPress-Right>', state=modifier)
                app.event_generate('<KeyRelease-Right>', state=modifier)
                pump(app, .05)
                assert state.manual.delta_x_px == before+step

            # The same loss must stop a measurement cross and its repeat callback.
            app._on_measure_press()
            app._handle_measure_arrow('right')
            assert app._measure_repeat_job is not None
            other.focus_force()
            pump(app)
            assert not app.measure_cross_active and app._measure_repeat_job is None
            other.destroy()
            other = None
            app.focus_force()
            pump(app)
            assert not app.append_deviation_to_filename.get()
            app.deviation_filename_box.toggle()
            assert app.append_deviation_to_filename.get() and settings.append_deviation_to_filename
            assert saved[-1]['append_deviation_to_filename']

            layouts = []
            for language in ['de', 'en']:
                app._on_language_changed('Deutsch' if language == 'de' else 'English')
                for size in ['1100x700', '1400x850']:
                    app.geometry(size)
                    pump(app)
                    box = app.deviation_filename_box
                    assert box.cget('text') == ('Deviation im Dateinamen' if language == 'de' else 'Deviation in filename')
                    label = box._text_label
                    assert label.winfo_reqwidth() <= label.winfo_width()+2
                    assert box.winfo_width() <= app.sidebar.winfo_width()-20
                    assert app.append_deviation_to_filename.get()
                    app.busy_state = 'save'
                    app._refresh_control_states()
                    assert box.cget('state') == 'disabled'
                    app.busy_state = 'idle'
                    app._refresh_control_states()
                    assert box.cget('state') == 'normal'
                    layouts.append(dict(language=language, requested_size=size, checkbox_width=box.winfo_width()))
            report = dict(ok=True, platform=sys.platform, focus_loss_recovery=True,
                          internal_focus_preserves_keys=True, real_arrow_steps=[1, 5, 10],
                          cross_repeat_cancelled=True, filename_option_persisted=True, layouts=layouts)
            target = Path('build/gui-keyboard-filename-'+sys.platform+'.json')
            target.parent.mkdir(exist_ok=True)
            target.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
            print(json.dumps(report))
        finally:
            if other is not None:
                other.destroy()
            app.destroy()


if __name__ == '__main__':
    main()
