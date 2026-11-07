"""Content-sized input guide with intact groups and a small-screen fallback."""
from __future__ import annotations

import re
import tkinter as tk

import customtkinter as ctk

from .controls_help import HELP_TEXT_DE, HELP_TEXT_EN
from .hover_menu import ModalScrollableFrame, work_area
from .theme import APP_BG, PANEL_BG, SECONDARY_BG, BORDER, HOVER_BG, GOLD_LIGHT, TEXT_PRIMARY, TEXT_SECONDARY


def help_groups(language):
    source = HELP_TEXT_EN if language == 'en' else HELP_TEXT_DE
    groups = []
    for block in source.split('\n\n'):
        lines = [line for line in block.splitlines() if line.strip()]
        rows = []
        for line in lines[1:]:
            parts = re.split(r'\s{2,}', line.strip(), maxsplit=1)
            key, action = parts if len(parts) == 2 else (parts[0], '')
            if key == 'Esc':
                action = ('Close help/menu or meter;\notherwise fit image;\nthen leave fullscreen'
                          if language == 'en' else
                          'Hilfe/Menü oder Messmodus schließen;\nsonst Ansicht einpassen;\ndanach Vollbild verlassen')
            rows.append((key, action))
        groups.append((lines[0], rows))
    groups.append(('Film looks and folder settings' if language == 'en' else 'Filmlooks und Ordnereinstellungen',
        [('Hover over LUT' if language == 'en' else 'Maus über LUT',
          'Temporary preview' if language == 'en' else 'Vorübergehende Vorschau'),
         ('Click on LUT' if language == 'en' else 'Klick auf LUT',
          'Apply look; Esc cancels preview' if language == 'en' else 'Look übernehmen; Esc verwirft Vorschau'),
         ('Apply to folder…' if language == 'en' else 'Für Ordner übernehmen…',
          'Select aspect, LUT and/or color matching' if language == 'en' else
          'Seitenverhältnis, LUT und/oder Farbangleichung auswählen')]))
    return groups


def column_groups(groups, columns):
    if columns == 3:
        return [[groups[i] for i in indices] for indices in ((0, 1), (2, 5), (3, 4, 6))]
    if columns == 1:
        return [groups]
    result, heights = [[], []], [0, 0]
    for group in groups:
        index = 0 if heights[0] <= heights[1] else 1
        result[index].append(group)
        heights[index] += len(group[1])+2
    return result


class ControlsGuide(ctk.CTkToplevel):
    def __init__(self, app):
        super().__init__(app)
        self.withdraw()
        self.app = app
        self.title(app._t('help_title'))
        self.configure(fg_color=APP_BG)
        self.transient(app); self.resizable(True, True)
        self.protocol('WM_DELETE_WINDOW', app._close_shortcuts_help)
        self.bind('<Escape>', lambda e: app._close_shortcuts_help())
        self.scale = app.preview_label._get_widget_scaling()
        self.groups = help_groups(app.settings.language)
        self.panels, self.actions, self._layout_key = [], [], None
        self._resize_job = None
        outer = ctk.CTkFrame(self, fg_color=PANEL_BG, corner_radius=8)
        outer.pack(fill='both', expand=True, padx=18, pady=18)
        ctk.CTkLabel(outer, text=app._t('help_heading'), text_color=GOLD_LIGHT,
            font=app._font(22, 'bold'), anchor='w').pack(fill='x', padx=18, pady=(14, 10))
        self.content = ModalScrollableFrame(outer, fg_color='transparent', corner_radius=0,
            scrollbar_button_color=BORDER, scrollbar_button_hover_color=HOVER_BG)
        self.content.pack(fill='both', expand=True, padx=16, pady=(0, 16))
        l, t, r, b = work_area(app)
        available = (r-l-48)/self.scale
        columns = 3 if available >= 1250 else 2 if available >= 820 else 1
        width = min(r-l-48, round((1360 if columns == 3 else 1100 if columns == 2 else 650)*self.scale))
        self._arrange(width, force=True)
        self.update_idletasks()
        content_height = max((panel.winfo_reqheight() for panel in self.panels), default=400)
        height = min(b-t-70, max(round(540*self.scale), content_height+round(112*self.scale)))
        self.initial_columns = columns
        self.initial_content_height = content_height
        self.initial_window_size = (width, height)
        x = round(max(l+16, min(r-width-16, app.winfo_rootx()+(app.winfo_width()-width)/2)))
        y = round(max(t+16, min(b-height-16, app.winfo_rooty()+(app.winfo_height()-height)/2)))
        tk.Toplevel.geometry(self, f'{width}x{height}{x:+d}{y:+d}')
        self.minsize(520, 360)
        self.bind('<Configure>', self._resized, add='+')
        if app.state() != 'withdrawn':
            self.deiconify(); self.lift(); self.focus_set()
        self.after_idle(self._update_scrollbar)

    def _arrange(self, width, *, force=False):
        logical = width/self.scale
        columns = 3 if logical >= 1250 else 2 if logical >= 820 else 1
        column_width = max(260, (logical-88)/columns)
        signature = (columns, round(column_width/4))
        if signature == self._layout_key and not force:
            return
        if self._layout_key is None or self._layout_key[0] != columns or force:
            for panel in self.panels:
                panel.destroy()
            self.panels, self.actions = [], []
            for index, groups in enumerate(column_groups(self.groups, columns)):
                panel = ctk.CTkFrame(self.content, fg_color=SECONDARY_BG, corner_radius=5)
                panel.grid(row=0, column=index, sticky='nsew', padx=(0, 5) if index == 0 else (5, 0))
                panel.grid_columnconfigure(0, minsize=140)
                panel.grid_columnconfigure(1, weight=1)
                self.panels.append(panel)
                for col, key in enumerate(('help_key_column', 'help_action_column')):
                    ctk.CTkLabel(panel, text=self.app._t(key), text_color=TEXT_SECONDARY,
                        font=self.app._font(11, 'bold'), anchor='e' if col == 0 else 'w').grid(
                            row=0, column=col, sticky='ew', padx=10, pady=(8, 5))
                row = 1
                for title, entries in groups:
                    if row > 1:
                        ctk.CTkFrame(panel, height=1, fg_color=BORDER, corner_radius=0).grid(
                            row=row, column=0, columnspan=2, sticky='ew', padx=10, pady=(7, 6))
                        row += 1
                    ctk.CTkLabel(panel, text=title, text_color=TEXT_PRIMARY,
                        font=self.app._font(13, 'bold'), wraplength=column_width-24,
                        justify='left', anchor='w').grid(row=row, column=0, columnspan=2,
                                                        sticky='ew', padx=10, pady=(1, 5))
                    row += 1
                    for key, action in entries:
                        ctk.CTkLabel(panel, text=key, text_color=GOLD_LIGHT,
                            font=self.app._font(12, 'bold'), wraplength=130, anchor='e', justify='right').grid(
                                row=row, column=0, sticky='ne', padx=(10, 9), pady=1)
                        label = ctk.CTkLabel(panel, text=action, text_color=TEXT_PRIMARY,
                            font=self.app._font(12), anchor='w', justify='left',
                            wraplength=max(120, column_width-175))
                        label.grid(row=row, column=1, sticky='nw', padx=(9, 10), pady=1)
                        self.actions.append(label)
                        row += 1
            for i in range(3):
                self.content.grid_columnconfigure(i, weight=1 if i < columns else 0, uniform='guide')
        for label in self.actions:
            label.configure(wraplength=max(120, column_width-175))
        self._layout_key = signature

    def _resized(self, event):
        if event.widget is not self:
            return
        if self._resize_job is not None:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(80, self._resize)

    def _resize(self):
        self._resize_job = None
        self._arrange(self.winfo_width())
        self.after_idle(self._update_scrollbar)

    def _update_scrollbar(self):
        if not self.winfo_exists():
            return
        canvas = self.content._parent_canvas
        needed = self.content.winfo_reqheight() > canvas.winfo_height()+2
        if needed:
            self.content._scrollbar.grid()
        else:
            self.content._scrollbar.grid_remove()

    def destroy(self):
        if getattr(self, '_resize_job', None) is not None:
            self.after_cancel(self._resize_job)
        super().destroy()
