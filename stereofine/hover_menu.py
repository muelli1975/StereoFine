"""A themed option-menu popup whose hover callbacks leave Tk responsive."""
from __future__ import annotations

import sys
import tkinter as tk

import customtkinter as ctk

from .theme import SECONDARY_BG, HOVER_BG, BORDER, TEXT_PRIMARY, GOLD_LIGHT


def work_area(widget):
    if sys.platform.startswith('win'):
        try:
            import ctypes
            from ctypes import wintypes
            class Info(ctypes.Structure):
                _fields_ = [('size', wintypes.DWORD), ('monitor', wintypes.RECT),
                            ('work', wintypes.RECT), ('flags', wintypes.DWORD)]
            user = ctypes.windll.user32
            user.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
            user.MonitorFromWindow.restype = wintypes.HANDLE
            user.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Info)]
            user.GetMonitorInfoW.restype = wintypes.BOOL
            monitor = user.MonitorFromWindow(wintypes.HWND(widget.winfo_id()), 2)
            info = Info(); info.size = ctypes.sizeof(info)
            if user.GetMonitorInfoW(monitor, ctypes.byref(info)):
                r = info.work
                return r.left, r.top, r.right, r.bottom
        except (OSError, AttributeError):
            pass
    return 0, 0, widget.winfo_screenwidth(), widget.winfo_screenheight()


class ModalScrollableFrame(ctk.CTkScrollableFrame):
    def bind_all(self, sequence=None, func=None, add=None):
        # CTk registers wheel/Shift callbacks application-wide. A short-lived
        # popup owns its bindings so closing it also removes those callbacks.
        return self.winfo_toplevel().bind(sequence, func, add)


class HoverOptionMenu(ctk.CTkOptionMenu):
    def __init__(self, *args, before_open=None, on_hover=None, on_cancel=None, **kwargs):
        self.popup = None
        self.before_open, self.on_hover, self.on_cancel = before_open, on_hover, on_cancel
        self.section_headers: dict[int, str] = {}
        self._popup_headers: dict[int, ctk.CTkLabel] = {}
        self._popup_buttons = []
        self._active_index = 0
        super().__init__(*args, **kwargs)

    def _open_dropdown_menu(self):
        if self.cget('state') == 'disabled':
            return
        if self.popup is not None and self.popup.winfo_exists():
            self.close_popup()
            return
        if self.before_open is not None and self.before_open() is False:
            return
        window = ctk.CTkToplevel(self.winfo_toplevel())
        window.withdraw(); window.overrideredirect(True)
        window.configure(fg_color=BORDER)
        self.popup = window
        values = self.cget('values')
        scale = self._get_widget_scaling()
        l, t, r, b = work_area(self)
        below = b-self.winfo_rooty()-self.winfo_height()-8
        above = self.winfo_rooty()-t-8
        header_height, header_padding = 20, (10, 3)
        content_height = len(values)*30 + len(self.section_headers)*(header_height + sum(header_padding)) + 10
        height = min(round(content_height*scale), max(below, above), int((b-t)*.82))
        width = max(round(260*scale), self.winfo_width())
        width = min(width, r-l-16)
        x = max(l+8, min(r-width-8, self.winfo_rootx()))
        y = (self.winfo_rooty()+self.winfo_height()+3 if below >= height
             else max(t+8, self.winfo_rooty()-height-3))
        tk.Toplevel.geometry(window, f'{width}x{max(80,height)}{x:+d}{y:+d}')
        frame = ModalScrollableFrame(window, fg_color=SECONDARY_BG, corner_radius=0,
            scrollbar_button_color=BORDER, scrollbar_button_hover_color=HOVER_BG)
        frame.pack(fill='both', expand=True, padx=1, pady=1)
        self._popup_frame = frame
        self._popup_buttons = []
        header_font = ctk.CTkFont(size=12, weight='bold')
        for index, value in enumerate(values):
            if index in self.section_headers:
                header = ctk.CTkLabel(frame, text=self.section_headers[index], height=header_height,
                    anchor='w', text_color=GOLD_LIGHT, font=header_font)
                header.pack(fill='x', padx=8, pady=header_padding)
                self._popup_headers[index] = header
            button = ctk.CTkButton(frame, text=value, height=28, anchor='w', corner_radius=0,
                fg_color=SECONDARY_BG, hover_color=HOVER_BG, text_color=TEXT_PRIMARY,
                font=self.cget('font'), command=lambda i=index: self._choose(i))
            button.pack(fill='x', pady=1)
            button.bind('<Enter>', lambda e, i=index: self._activate(i), add='+')
            self._popup_buttons.append(button)
        selected = self.cget('variable').get() if self.cget('variable') is not None else self.get()
        self._active_index = values.index(selected) if selected in values else 0
        window.bind('<Escape>', lambda e: self._escape())
        window.bind('<Up>', lambda e: self._step(-1))
        window.bind('<Down>', lambda e: self._step(1))
        window.bind('<Return>', lambda e: self._choose(self._active_index))
        window.bind('<ButtonPress-1>', self._outside_click, add='+')
        window.protocol('WM_DELETE_WINDOW', self.close_popup)
        if self.winfo_toplevel().state() != 'withdrawn':
            window.deiconify()
            window.lift()
            window.grab_set()
            window.focus_set()
            window.update_idletasks()
            self._reveal_active()
        self._activate(self._active_index, preview=False)

    def _activate(self, index, *, preview=True):
        self._active_index = index
        for i, button in enumerate(self._popup_buttons):
            button.configure(fg_color=HOVER_BG if i == index else SECONDARY_BG)
        if preview and self.on_hover is not None:
            self.on_hover(self.cget('values')[index])

    def _step(self, direction):
        index = max(0, min(len(self._popup_buttons)-1, self._active_index+direction))
        self._activate(index)
        self._reveal_active()
        return 'break'

    def _reveal_active(self):
        canvas = self._popup_frame._parent_canvas
        bounds = canvas.bbox('all')
        if not bounds:
            return
        button = self._popup_buttons[self._active_index]
        top = button.winfo_y()
        bottom = top + button.winfo_height()
        header = self._popup_headers.get(self._active_index)
        if self._active_index == 0:
            top = 0
        elif header is not None:
            top = header.winfo_y()
        view_top = canvas.canvasy(0)
        view_height = canvas.winfo_height()
        content_height = max(1, bounds[3] - bounds[1])
        if top < view_top:
            canvas.yview_moveto((top - bounds[1]) / content_height)
        elif bottom > view_top + view_height:
            canvas.yview_moveto((bottom - view_height - bounds[1]) / content_height)

    def _choose(self, index):
        value = self.cget('values')[index]
        self.close_popup(cancel=False)
        self._dropdown_callback(value)
        return 'break'

    def _outside_click(self, event):
        p = self.popup
        if p is not None and not (p.winfo_rootx() <= event.x_root < p.winfo_rootx()+p.winfo_width()
                                 and p.winfo_rooty() <= event.y_root < p.winfo_rooty()+p.winfo_height()):
            return self._escape()

    def _escape(self):
        self.close_popup()
        return 'break'

    def close_popup(self, *, cancel=True):
        p, self.popup = self.popup, None
        self._popup_buttons = []
        self._popup_headers.clear()
        if p is not None and p.winfo_exists():
            p.grab_release(); p.destroy()
            if cancel and self.on_cancel is not None:
                self.on_cancel()

    def destroy(self):
        self.close_popup(cancel=False)
        super().destroy()
