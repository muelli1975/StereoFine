"""The themed, independently selectable folder-preference action."""
from copy import deepcopy
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

from .config import APP_NAME
from .folder_settings import FolderChoices, FolderProgress, apply_folder_preferences
from .i18n import aspect_label, orientation_label
from .looks import builtin_looks, look_label
from .sources import discover_pair_sources, discover_stereo_file_sources
from .theme import APP_BG, SECONDARY_BG, BORDER, HOVER_BG, TEXT_PRIMARY, TEXT_SECONDARY, GOLD_DARK, GOLD_LIGHT
from .hover_menu import work_area


class FolderSettingsDialog(ctk.CTkToplevel):
    def __init__(self, app, sources):
        super().__init__(app)
        self.withdraw()
        self.app, self.sources, self.running = app, sources, False
        self.title(app._t('folder_apply'))
        self.configure(fg_color=APP_BG)
        self.transient(app); self.resizable(False, False)
        self.protocol('WM_DELETE_WINDOW', self.cancel)
        self.bind('<Escape>', lambda e: self.cancel())
        self.bind('<Return>', lambda e: self.start())
        self.selection = {key: ctk.BooleanVar(value=False) for key in ('aspect', 'look', 'color', 'series_input')}
        self.aspect = app.output_aspect.get()
        self.look = deepcopy(app._current_look_option())
        self.color_enabled = bool(app.color_match_enabled.get())
        self.series_input = deepcopy(app.current.state.input_transform)
        frame = ctk.CTkFrame(self, fg_color=SECONDARY_BG, corner_radius=8)
        frame.pack(fill='both', expand=True, padx=18, pady=18)
        frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(frame, text=str(sources[0].input_root), font=app._font(13),
            text_color=TEXT_PRIMARY, wraplength=520, justify='left', anchor='w').grid(
                row=0, column=0, columnspan=2, sticky='ew', padx=16, pady=(14, 4))
        ctk.CTkLabel(frame, text=app._t('folder_count', count=len(sources)), font=app._font(12),
            text_color=TEXT_SECONDARY, anchor='w').grid(row=1, column=0, columnspan=2,
                                                      sticky='ew', padx=16, pady=(0, 14))
        name = (Path(self.look.path).name if self.look.path else next(
            (look_label(item, app.settings.language) for item in builtin_looks()
             if item['id'] == self.look.preset_id), self.look.preset_id))
        switch = lambda value: app._t('folder_on' if value else 'folder_off')
        transform = self.series_input
        def eye_orientation(value, mirrored):
            rotation = orientation_label(value, app.settings.language)
            return f'{rotation}, {app._t("mirror")}' if mirrored else rotation
        orientation = ' / '.join((eye_orientation(transform.left_orientation, transform.left_mirror),
                                  eye_orientation(transform.right_orientation, transform.right_mirror)))
        if transform.swap_eyes:
            orientation += f' · {app._t("swap_eyes")}'
        values = [('aspect', app._t('aspect_ratio'), aspect_label(self.aspect, app.settings.language)),
                  ('look', app._t('look_apply'), f'{switch(self.look.enabled)} · {name} · {self.look.strength*100:.0f}%'),
                  ('color', app._t('color_match'), switch(self.color_enabled)),
                  ('series_input', app._t('save_series_input'), orientation)]
        self.checkboxes = []
        for row, (key, title, value) in enumerate(values, 2):
            box = ctk.CTkCheckBox(frame, text=title, variable=self.selection[key], command=self._changed,
                fg_color=GOLD_DARK, hover_color=GOLD_LIGHT, border_color=BORDER,
                text_color=TEXT_PRIMARY, font=app._font(13))
            box.grid(row=row, column=0, sticky='w', padx=16, pady=9)
            self.checkboxes.append(box)
            ctk.CTkLabel(frame, text=value, text_color=TEXT_PRIMARY, font=app._font(13),
                wraplength=280, justify='left', anchor='w').grid(row=row, column=1,
                    sticky='ew', padx=(14, 16), pady=9)
        ctk.CTkLabel(frame, text=app._t('folder_scope'), font=app._font(12),
            text_color=TEXT_SECONDARY, wraplength=520, justify='left', anchor='w').grid(
                row=6, column=0, columnspan=2, sticky='ew', padx=16, pady=(12, 8))
        self.progress_label = ctk.CTkLabel(frame, text='', font=app._font(12), text_color=TEXT_PRIMARY,
                                         anchor='w', wraplength=520)
        self.progress_label.grid(row=7, column=0, columnspan=2, sticky='ew', padx=16)
        # Reserve the row before the run so the buttons stay at the same height.
        self.progress = ctk.CTkProgressBar(frame, fg_color=SECONDARY_BG, progress_color=SECONDARY_BG)
        self.progress.set(0)
        self.progress.grid(row=8, column=0, columnspan=2, sticky='ew', padx=16, pady=(0, 12))
        buttons = ctk.CTkFrame(frame, fg_color='transparent')
        buttons.grid(row=9, column=0, columnspan=2, sticky='e', padx=16, pady=(4, 16))
        self.apply_button = app._secondary_button(buttons, app._t('folder_commit'), self.start, width=120)
        self.apply_button.pack(side='left', padx=(0, 8)); self.apply_button.configure(state='disabled')
        self.cancel_button = app._secondary_button(buttons, app._t('cancel'), self.cancel, width=120)
        self.cancel_button.pack(side='left')
        # The modal owns its busy states; its Cancel button must remain active.
        for button in (self.apply_button, self.cancel_button):
            while button in app._lock_widgets:
                app._lock_widgets.remove(button)
        self.update_idletasks()
        scale = self._get_window_scaling()
        width, height = 620, max(350, round(frame.winfo_reqheight()/scale)+36)
        self.geometry(f'{width}x{height}')
        self.update_idletasks()
        l, t, r, b = work_area(app)
        px, py = app.winfo_rootx()+(app.winfo_width()-width*scale)/2, app.winfo_rooty()+(app.winfo_height()-height*scale)/2
        import tkinter as tk
        tk.Toplevel.geometry(self, f'{round(width*scale)}x{round(height*scale)}'
            f'{round(max(l+8,min(r-width*scale-8,px))):+d}{round(max(t+8,min(b-height*scale-8,py))):+d}')
        if app.state() != 'withdrawn':
            self.deiconify(); self.grab_set(); self.focus_set()

    def _changed(self):
        self.apply_button.configure(state='normal' if any(v.get() for v in self.selection.values()) else 'disabled')

    def start(self):
        if self.running or not any(v.get() for v in self.selection.values()):
            return 'break'
        if not self.app._flush_state_save(explicit=True):
            return 'break'
        choices = FolderChoices(self.aspect if self.selection['aspect'].get() else None,
            deepcopy(self.look) if self.selection['look'].get() else None,
            self.color_enabled if self.selection['color'].get() else None,
            self.series_input if self.selection['series_input'].get() else None)
        self.running = True
        for box in self.checkboxes:
            self.app._set_checkbox_enabled(box, False)
        self.apply_button.configure(state='disabled')
        self.progress.configure(fg_color=BORDER, progress_color=GOLD_DARK)
        self.progress_label.configure(text=self.app._t('folder_progress', index=0, total=len(self.sources)))
        def job(token, progress):
            return apply_folder_preferences(self.sources, choices, cancellation=token, progress=progress)
        self.app._start_worker('folder_settings', self.app._t('folder_apply'), job)
        return 'break'

    def update_progress(self, progress):
        self.progress.set(progress.index/max(1, progress.total))
        self.progress_label.configure(text=self.app._t('folder_progress', index=progress.index, total=progress.total))

    def cancel(self):
        if self.running:
            self.app.cancel_current_job()
            self.cancel_button.configure(state='disabled')
            self.progress_label.configure(text=self.app._t('cancelling'))
        else:
            self.destroy(); self.app._folder_dialog = None
        return 'break'


def show_folder_settings(app):
    if app.busy_state != 'idle' or app.current is None:
        return
    existing = getattr(app, '_folder_dialog', None)
    if existing is not None and existing.winfo_exists():
        existing.lift(); return
    root = app.current.source.input_root
    try:
        sources = (discover_pair_sources(root) if app.current.source.kind == 'pair'
                   else discover_stereo_file_sources(root))
        if not sources:
            raise ValueError(app._t('folder_no_images'))
    except (OSError, ValueError) as exc:
        messagebox.showerror(APP_NAME, str(exc)); return
    app._folder_dialog = FolderSettingsDialog(app, sources)


def finish_folder_settings(app, result):
    dialog = getattr(app, '_folder_dialog', None)
    if dialog is not None:
        dialog.destroy(); app._folder_dialog = None
    messages = []
    if result.series_input_saved:
        messages.append(app._t('series_input_saved'))
    if result.updated or result.unchanged or result.failed:
        messages.append(app._t('folder_done', updated=len(result.updated), unchanged=len(result.unchanged), failed=len(result.failed)))
    text = '\n'.join(messages)
    if result.cancelled:
        text = app._t('folder_cancelled')+' '+text
    if result.failed:
        text += '\n'+app._t('folder_error_log')
    if app.source_index is not None:
        app._load_source_index(app.source_index)
    app._folder_feedback = text
    app._render_status()
