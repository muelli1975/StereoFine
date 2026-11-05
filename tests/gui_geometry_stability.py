"""Measure fixed UI rectangles throughout real edit/measurement transitions."""
import argparse
import json
from pathlib import Path
import platform
import tempfile
import time
from unittest.mock import patch

import customtkinter as ctk

from stereofine import gui
from stereofine.settings import AppSettings
from tests.gui_cross_measurement import pump
from tests.gui_tiff_detail import native_ready
from tests.test_restart_alignment import RestartAlignmentTests


def rectangles(app):
    names = ('sidebar_container', 'sidebar_header', 'sidebar_bottom', 'status_frame',
             'preview_frame', 'start_button', 'save_button', 'help_footer_label')
    widgets = {name: getattr(app, name) for name in names}
    widgets.update({'status:'+name: value for name, value in app._status_line_widgets.items()})
    result = {name: [w.winfo_rootx(), w.winfo_rooty(), w.winfo_width(), w.winfo_height()]
              for name, w in widgets.items()}
    # Scrollable content may move when a newly selected path wraps. The actual
    # controls must retain their sizes when they are enabled/disabled or edited.
    result.update({f'control:{index}:{type(w).__name__}': [w.winfo_width(), w.winfo_height()]
                   for index, w in enumerate(app._lock_widgets)})
    return result


def text_details(app):
    return {name: dict(text=w.cget('text'), height=w.winfo_height(),
                      requested_height=w.winfo_reqheight(),
                      text_fits=(w._label.winfo_reqheight() <= w.winfo_height()
                                 and w._label.winfo_reqwidth() <= w.winfo_width()))
            for name, w in app._status_line_widgets.items()}


def observe(app, name, action, finished=None):
    app.update_idletasks()
    before = rectangles(app)
    before_text = text_details(app)
    clipped = [dict(phase='before', row=k, detail=v) for k, v in before_text.items() if not v['text_fits']]
    changes = []
    action()
    until = time.monotonic()+30
    settled = None
    while time.monotonic() < until:
        app.update()
        after = rectangles(app)
        for key, detail in text_details(app).items():
            if not detail['text_fits'] and not any(x['row'] == key for x in clipped):
                clipped.append(dict(phase='transition', row=key, detail=detail))
        diff = {key: [before[key], value] for key, value in after.items() if value != before[key]}
        if diff and (not changes or diff != changes[-1]['rectangles']):
            changes.append(dict(rectangles=diff, text=text_details(app)))
        done = (app.busy_state == 'idle' and app._measurement_after_id is None
                and app._measurement_job_id is None and (finished is None or finished()))
        if done:
            if settled is None:
                settled = time.monotonic()
            if time.monotonic()-settled > .25:
                break
        else:
            settled = None
        time.sleep(.008)
    else:
        raise TimeoutError(name)
    return dict(action=name, stable=not changes, clipped=clipped, before_text=before_text,
                changes=changes[:8], settled_text=text_details(app))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-only', action='store_true')
    args = parser.parse_args()
    checks = []
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = RestartAlignmentTests().source(root)
        for language in ('de', 'en'):
            for scale in (1., 1.25, 1.5):
                ctk.set_widget_scaling(scale)
                ctk.set_window_scaling(scale)
                with patch.object(gui, 'load_settings', return_value=AppSettings(language=language)), \
                        patch.object(gui, 'save_settings'), patch.object(gui, 'play_ready_sound'), \
                        patch.object(gui.messagebox, 'showwarning'), patch.object(gui.messagebox, 'showinfo'), \
                        patch.object(gui.messagebox, 'showerror'):
                    app = gui.StereoFineApp()
                    try:
                        app.geometry('1400x900')
                        since = time.monotonic()
                        pump(app, lambda: time.monotonic()-since > .4)
                        rows = []
                        rows.append(observe(app, 'load', lambda: app._set_source_collection([source], 0, batch=False),
                                            lambda: app.current is not None and native_ready(app)))
                        rows.append(observe(app, 'align', app.start_processing,
                                            lambda: native_ready(app)))
                        for model in ('Affine', 'Affine + Vergence + yQuad'):
                            app.current.state.alignment.model = model
                            app._render_status()
                            app.update_idletasks()
                            for aspect in ('1:1', '16:9', 'original'):
                                def change(aspect=aspect):
                                    app.output_aspect.set(aspect)
                                    app._on_aspect_changed()
                                rows.append(observe(app, 'aspect:'+model+':'+aspect, change,
                                                    lambda: native_ready(app)))
                        rows.append(observe(app, 'crop-zoom', lambda: app._adjust_crop_zoom(1),
                                            lambda: native_ready(app)))
                        rows.append(observe(app, 'manual-offset', lambda: app._adjust_manual_offset(1, 1),
                                            lambda: native_ready(app)))
                        rows.append(observe(app, 'floating-window', lambda: app._adjust_floating_edge('left', 1)))
                        def grid():
                            app.grid_mode.set('Weiß')
                            app._update_preview_display()
                        rows.append(observe(app, 'grid', grid))
                        for uncertain in (True, False):
                            def warning(uncertain=uncertain):
                                app.current.state.disparity.uncertain = uncertain
                                app._render_status()
                            rows.append(observe(app, 'warning:'+str(uncertain), warning))
                        def colour():
                            app.color_match_enabled.set(not app.color_match_enabled.get())
                            app._on_color_match_changed()
                        rows.append(observe(app, 'colour', colour, lambda: native_ready(app)))
                        app._effective_output_folder = lambda _root: root/'output'
                        rows.append(observe(app, 'save', app.save_current_result))
                        rows.append(observe(app, 'manual-reset', app.reset_manual_to_auto,
                                            lambda: native_ready(app)))
                        checks.append(dict(language=language, scale=scale, checks=rows))
                        print(json.dumps(dict(language=language, scale=scale,
                            unstable=[r['action'] for r in rows if not r['stable']])), flush=True)
                    finally:
                        app.destroy()
    ctk.set_widget_scaling(1.)
    ctk.set_window_scaling(1.)
    Path('build').mkdir(exist_ok=True)
    path = Path('build')/f'gui-geometry-stability-{platform.system()}.json'
    path.write_text(json.dumps(dict(checks=checks), indent=2)+'\n', encoding='utf-8')
    if not args.report_only:
        assert all(r['stable'] and not r['clipped'] for group in checks for r in group['checks']), str(path)


if __name__ == '__main__':
    main()
