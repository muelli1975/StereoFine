"""Small delayed tooltips that do not consume sidebar space."""
import tkinter as tk

from .theme import PANEL_BG, TEXT_PRIMARY


def attach_tooltip(widget, text):
    pending = None
    window = None

    def hide(_event=None):
        nonlocal pending, window
        if pending is not None:
            widget.after_cancel(pending)
            pending = None
        if window is not None:
            window.destroy()
            window = None

    def show():
        nonlocal pending, window
        pending = None
        window = tk.Toplevel(widget)
        window.withdraw()
        window.overrideredirect(True)
        tk.Label(window, text=text, wraplength=350, justify='left', padx=10, pady=8,
                 bg=PANEL_BG, fg=TEXT_PRIMARY).pack()
        x = min(widget.winfo_rootx(), widget.winfo_screenwidth() - 380)
        y = widget.winfo_rooty() + widget.winfo_height() + 6
        window.geometry(f'+{max(0,x)}+{max(0,y)}')
        window.deiconify()

    def enter(_event=None):
        nonlocal pending
        hide()
        pending = widget.after(550, show)

    widget.bind('<Enter>', enter, add='+')
    for event in ('<Leave>', '<ButtonPress>', '<Unmap>', '<Destroy>'):
        widget.bind(event, hide, add='+')
