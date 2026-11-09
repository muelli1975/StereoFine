"""Compact LUT controls and the program-defaults action."""
from __future__ import annotations

from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from .config import APP_NAME
from .looks import builtin_looks, load_lut, look_path, look_label
from .tooltip import attach_tooltip
from .preferences import mark_preference
from .output_naming import suffix_label
from .state import LookState
from .exposure import normalize_exposure
from .i18n import format_exposure
from .slider_wheel import bind_slider_wheel
from .theme import BORDER, CONTROL_RADIUS, GOLD_DARK, GOLD_LIGHT, SECONDARY_BG, TEXT_PRIMARY, TEXT_DISABLED


def preview_look(app):
    return getattr(app, '_look_hover_state', None) or app.current.state.look


class LookControlsMixin:
    def show_folder_settings(self):
        from .folder_dialog import show_folder_settings
        show_folder_settings(self)

    def _init_look_controls(self):
        self.look_enabled = ctk.BooleanVar(value=self.settings.look_enabled)
        self.look_strength = ctk.DoubleVar(value=round(self.settings.look_strength*100))
        self._look_preset_id = self.settings.look_preset_id
        self._look_path = self.settings.look_path
        self.look_choice = ctk.StringVar(value='')
        self._look_settings_job = None
        self._look_hover_job = None
        self._look_hover_state = None
        self._look_popup_generation = 0
        self._sync_look_display()

    def _current_look_option(self):
        if not hasattr(self, 'look_enabled'):
            return getattr(getattr(getattr(self, 'current', None), 'state', None), 'look', LookState())
        return LookState(bool(self.look_enabled.get()), self._look_preset_id,
                         self._look_path, float(self.look_strength.get())/100).normalize()

    def _sync_look_display(self):
        entries = builtin_looks()
        labels = [look_label(entry, self.settings.language) for entry in entries]
        if self._look_path:
            selected = Path(self._look_path).name
            if selected not in labels: labels.append(selected)
        else:
            selected = next((look_label(entry, self.settings.language) for entry in entries
                             if entry['id'] == self._look_preset_id), labels[0] if labels else '')
        labels.append('Import (.cube, .png)')
        self.look_choice.set(selected)
        if hasattr(self, 'look_menu'):
            self.look_menu.section_headers = {
                index: self._t(f"look_group_{entry['section']}")
                for index, entry in enumerate(entries) if 'section' in entry
            }
            self.look_menu.configure(values=labels)

    def _build_look_controls(self, parent, row):
        from .hover_menu import HoverOptionMenu

        self.look_checkbox = self._checkbox(parent, self._t('look_apply'),
                                            self.look_enabled, self._on_look_enabled)
        self.look_checkbox.grid(row=row, column=0, sticky='w', padx=20, pady=(0, 6)); row += 1
        self.look_menu = self._option_menu(parent, values=['Import (.cube, .png)'],
            variable=self.look_choice, command=self._on_look_selected, menu_class=HoverOptionMenu,
            before_open=self._begin_look_menu, on_hover=self._on_look_hover,
            on_cancel=self._cancel_look_hover, dismiss_checkbox=self.look_checkbox,
            text_color_disabled=TEXT_DISABLED)
        self.look_menu.grid(row=row, column=0, sticky='ew', padx=(42,20), pady=(0,4)); row += 1
        self.look_strength_label = ctk.CTkLabel(parent, text='', text_color=TEXT_PRIMARY,
                                               font=self._font(13), anchor='w')
        self.look_strength_label.grid(row=row,column=0,sticky='ew',padx=(42,20),pady=(2,3));row += 1
        self.look_slider = ctk.CTkSlider(parent, from_=0, to=100, number_of_steps=100,
            variable=self.look_strength, command=self._on_look_strength,
            fg_color=BORDER, progress_color=GOLD_DARK, button_color=GOLD_LIGHT,
            button_hover_color=GOLD_LIGHT)
        bind_slider_wheel(self.look_slider, self._can_step_look_strength, self._step_look_strength)
        self.look_slider.grid(row=row,column=0,sticky='ew',padx=(42,20),pady=(0,12));row += 1
        self._lock_widgets.append(self.look_slider)
        for widget in (self.look_strength_label, self.look_slider):
            attach_tooltip(widget, self._t('look_strength_tooltip'))
        self._look_tooltip_hides = [attach_tooltip(widget, lambda: self._t('look_tooltip'),
            enabled=lambda: self.look_menu.popup is None) for widget in (self.look_checkbox, self.look_menu)]
        self.folder_settings_button = self._secondary_button(parent, self._t('folder_apply'),
                                                             self.show_folder_settings)
        self.folder_settings_button.grid(row=row, column=0, sticky='ew', padx=(42,20), pady=(0,12)); row += 1
        self._lock_widgets.append(self.folder_settings_button)
        self._sync_look_display()
        self._refresh_look_controls()
        return row

    def _build_exposure_controls(self, parent, row):
        frame = ctk.CTkFrame(parent, fg_color='transparent')
        frame.grid(row=row, column=0, sticky='ew', padx=20, pady=(0, 4))
        frame.grid_columnconfigure(1, weight=1)
        label = ctk.CTkLabel(frame, text=self._t('exposure'), anchor='w',
                             text_color=TEXT_PRIMARY, font=self._font(13), width=82)
        label.grid(row=0, column=0, sticky='w', pady=2)
        self._exposure_slider = ctk.CTkSlider(
            frame, from_=-2, to=2, width=90, number_of_steps=400, command=self._set_exposure,
            fg_color=BORDER, progress_color=BORDER, button_color=GOLD_LIGHT,
            button_hover_color=GOLD_LIGHT)
        self._exposure_slider.grid(row=0, column=1, sticky='ew', padx=(4, 7), pady=2)
        self._exposure_text = ctk.StringVar(master=self)
        self._exposure_entry = ctk.CTkEntry(
            frame, width=60, height=25, textvariable=self._exposure_text, justify='right',
            fg_color=SECONDARY_BG, border_color=BORDER, text_color=TEXT_PRIMARY,
            corner_radius=CONTROL_RADIUS, font=self._font(12))
        self._exposure_entry.grid(row=0, column=2, sticky='e', pady=2)
        bind_slider_wheel(self._exposure_slider, self._can_edit_exposure,
                          lambda ticks: self._nudge_exposure(ticks * .1))
        self._exposure_slider.bind('<Double-Button-1>', lambda event: self._set_exposure(0))
        self._exposure_entry.bind('<Return>', lambda event: self._commit_exposure_entry(True))
        self._exposure_entry.bind('<FocusOut>', lambda event: self._commit_exposure_entry(False))
        self._exposure_entry.bind('<Escape>', lambda event: self._reset_exposure_entry())
        self._exposure_entry.bind('<Up>', lambda event: self._nudge_exposure(.01))
        self._exposure_entry.bind('<Down>', lambda event: self._nudge_exposure(-.01))
        attach_tooltip(label, self._t('exposure_tooltip'))
        self._sync_exposure_controls()
        return row + 1

    def _can_edit_exposure(self):
        return self.busy_state == 'idle' and self.current is not None

    def _sync_exposure_value(self):
        value = self.current.state.exposure if self.current is not None else 0.0
        self._exposure_slider.set(value)
        self._exposure_text.set(format_exposure(value, self.settings.language))

    def _sync_exposure_controls(self):
        self._sync_exposure_value()
        self._refresh_exposure_controls()

    def _refresh_exposure_controls(self):
        enabled = self._can_edit_exposure()
        state = 'normal' if enabled else 'disabled'
        self._exposure_slider.configure(state=state, button_color=GOLD_LIGHT if enabled else TEXT_DISABLED)
        self._exposure_entry.configure(state=state, text_color=TEXT_PRIMARY if enabled else TEXT_DISABLED)

    def _set_exposure(self, value):
        if self._can_edit_exposure():
            current = self.current.state
            exposure = normalize_exposure(value)
            changed = exposure != current.exposure
            current.exposure = exposure
            self._sync_exposure_value()
            if changed:
                self._schedule_state_save()
                self._refresh_preview()
        return 'break'

    def _nudge_exposure(self, change):
        if self._can_edit_exposure():
            self._set_exposure(self.current.state.exposure + change)
        return 'break'

    def _commit_exposure_entry(self, release):
        if self._can_edit_exposure():
            try:
                value = float(self._exposure_text.get().replace(',', '.'))
            except ValueError:
                self._sync_exposure_value()
            else:
                self._set_exposure(value)
        if release:
            self.preview_frame.focus_set()
        return 'break'

    def _reset_exposure_entry(self):
        self._sync_exposure_value()
        self.preview_frame.focus_set()
        return 'break'

    def _refresh_look_controls(self):
        if not hasattr(self, 'look_menu'):
            return
        enabled = self.busy_state == 'idle' and bool(self.look_enabled.get())
        color = TEXT_PRIMARY if enabled else TEXT_DISABLED
        self.look_menu.configure(state='normal' if enabled else 'disabled', text_color=color)
        if not enabled:
            self.look_menu.close_popup()
        self.folder_settings_button.configure(state='normal' if self.busy_state == 'idle' and self.current is not None else 'disabled')
        self.look_strength_label.configure(text=self._t('look_strength',value=round(self.look_strength.get())),
                                            text_color=color)
        self.look_slider.configure(state='normal' if enabled else 'disabled',
            fg_color=BORDER, progress_color=GOLD_DARK if enabled else BORDER,
            button_color=GOLD_LIGHT if enabled else TEXT_DISABLED,
            button_hover_color=GOLD_LIGHT if enabled else TEXT_DISABLED)

    def _sync_look_from_current(self):
        if self.current is None or not hasattr(self, 'look_enabled'):
            return
        look = self.current.state.look.normalize()
        self.look_enabled.set(look.enabled)
        self.look_strength.set(round(look.strength*100))
        self._look_preset_id, self._look_path = look.preset_id, look.path
        self._sync_look_display()
        self._refresh_look_controls()

    def _on_look_selected(self, value, *, persist=True):
        self._cancel_look_hover(refresh=value == 'Import (.cube, .png)')
        previous_id, previous_path = self._look_preset_id, self._look_path
        if value == 'Import (.cube, .png)':
            self._sync_look_display()
            initial = self.settings.last_lut_location or (str(Path(self._look_path).parent) if self._look_path else None)
            selected = filedialog.askopenfilename(parent=self, title=self._t('look_import'),
                initialdir=initial, filetypes=[('3D LUT', '*.cube *.png'),('Cube', '*.cube'),('HaldCLUT PNG','*.png')])
            if not selected:
                self._cancel_look_hover()
                self._sync_look_display()
                return
            try:
                load_lut(selected)
            except (OSError, ValueError) as exc:
                messagebox.showerror(APP_NAME,self._t('look_load_failed',text=str(exc)))
                return
            self._look_path = str(Path(selected).resolve())
            self.settings.last_lut_location = str(Path(selected).resolve().parent)
        else:
            entry = next((item for item in builtin_looks()
                          if look_label(item, self.settings.language) == value), None)
            if entry is not None:
                self._look_preset_id, self._look_path = entry['id'], ''
        applied = self._apply_look_change(persist=persist)
        if not applied:
            self._look_preset_id, self._look_path = previous_id, previous_path
            self._refresh_preview()
        self._sync_look_display()
        return applied

    def _cycle_look(self, step):
        if self.current is None or self.busy_state != 'idle' or not self.look_enabled.get():
            return
        entries = builtin_looks()
        if not entries:
            return
        index = -1 if step > 0 else len(entries)
        if not self._look_path:
            index = next((i for i, entry in enumerate(entries) if entry['id'] == self._look_preset_id), index)
        entry = entries[(index + step) % len(entries)]
        if self._look_path or entry['id'] != self._look_preset_id:
            if self._on_look_selected(look_label(entry, self.settings.language), persist=False):
                self._show_look_notice()

    def _begin_look_menu(self):
        if self.busy_state != 'idle' or not self.look_enabled.get():
            return False
        for hide in self._look_tooltip_hides:
            hide()
        if not self._flush_state_save(explicit=True):
            return False
        self._look_popup_generation += 1
        return True

    def _on_look_hover(self, value):
        if self._look_hover_job is not None:
            self.after_cancel(self._look_hover_job)
            self._look_hover_job = None
        if value == 'Import (.cube, .png)':
            self._cancel_look_hover()
            return
        entry = next((item for item in builtin_looks()
                      if look_label(item, self.settings.language) == value), None)
        if entry is None:
            look = self._current_look_option()
        else:
            look = LookState(True, entry['id'], '', float(self.look_strength.get())/100)
        generation, source_id = self._look_popup_generation, id(self.current)
        def preview():
            self._look_hover_job = None
            if (self.busy_state == 'idle' and id(self.current) == source_id
                    and self.look_menu.popup is not None and generation == self._look_popup_generation):
                self._look_hover_state = look
                self._refresh_preview()
        self._look_hover_job = self.after(130, preview)

    def _cancel_look_hover(self, *, refresh=True):
        if getattr(self, '_look_hover_job', None) is not None:
            self.after_cancel(self._look_hover_job)
            self._look_hover_job = None
        changed = getattr(self, '_look_hover_state', None) is not None
        self._look_hover_state = None
        self._look_popup_generation = getattr(self, '_look_popup_generation', 0)+1
        if changed and refresh and self.current is not None:
            self._refresh_preview()

    def _on_look_enabled(self):
        if not self._apply_look_change():
            self.look_enabled.set(False)
            self._apply_look_change()

    def _on_look_strength(self, value):
        self.look_strength.set(round(float(value)))
        self._apply_look_change(persist=False)

    def _can_step_look_strength(self):
        return (self.current is not None and self.busy_state == 'idle'
                and self.look_enabled.get() and self.look_menu.popup is None)

    def _step_look_strength(self, steps):
        if not steps or not self._can_step_look_strength():
            return
        current = self.look_strength.get()
        strength = max(0, min(100, current + 5 * steps))
        if strength != current:
            self._on_look_strength(strength)

    def _apply_look_change(self, *, persist=True):
        if self.busy_state != 'idle':
            return False
        look = self._current_look_option()
        try:
            if look.enabled and look.strength > 0:
                load_lut(look_path(look))
        except (OSError, ValueError) as exc:
            messagebox.showerror(APP_NAME,self._t('look_load_failed',text=str(exc)))
            return False
        self._look_preset_id = look.preset_id
        self.settings.look_enabled, self.settings.look_preset_id = look.enabled, look.preset_id
        self.settings.look_path, self.settings.look_strength = look.path, look.strength
        self._refresh_look_controls()
        if self.current is not None:
            self.current.state.look = look
            mark_preference(self.current.state, 'look')
            self._schedule_state_save()
            self._refresh_preview()
        if self._look_settings_job is not None:
            self.after_cancel(self._look_settings_job)
            self._look_settings_job = None
        if persist:
            self._persist_settings()
        else:
            self._look_settings_job = self.after(250,self._save_look_preferences)
        return True

    def _save_look_preferences(self):
        self._look_settings_job = None
        self._persist_settings()

    def restore_program_defaults(self):
        if self.busy_state != 'idle':
            return
        fresh = self.settings.restored_defaults()
        self.settings = fresh
        for variable, value in (
            (self.analysis_method,fresh.analysis_method), (self.output_aspect,fresh.default_aspect),
            (self.color_match_enabled,fresh.color_match_enabled),
            (self.gray_anaglyph,fresh.gray_anaglyph), (self.save_cross,fresh.save_cross),
            (self.tiff_sbs,fresh.tiff_sbs), (self.save_anaglyph,fresh.save_anaglyph),
            (self.append_deviation_to_filename,fresh.append_deviation_to_filename),
            (self.use_custom_sbs_suffix,fresh.use_custom_sbs_suffix),
            (self.look_enabled,False), (self.look_strength,100),
            (self.show_deviation_points,False), (self.grid_mode,'Aus'),
            (self.grid_spacing,'50 Promille'), (self.preview_mode,'Farbig'),
            (self.float_lr_symmetric,False), (self.analysis_only,False), (self.favorites_only,False)):
            variable.set(value)
        self._last_anaglyph_preview_mode = 'Farbig'
        self._look_preset_id, self._look_path = fresh.look_preset_id, ''
        self.sbs_suffix_display.set(suffix_label(fresh.sbs_suffix,fresh.language))
        self._end_point_measurement()
        self._inspection_view.reset()
        if self.current is not None:
            self._sync_vars_from_current()
        else:
            self._sync_look_display()
            self._sync_localized_display_vars()
        self._persist_settings()
        self._refresh_control_states()
        self._refresh_preview()
