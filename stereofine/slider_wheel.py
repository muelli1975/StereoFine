"""Shared slider gestures and the centered track for exposure."""

import customtkinter as ctk

from .theme import GOLD_DARK


SHIFT_MASK = 0x0001


class CenteredSlider(ctk.CTkSlider):
    """Colour the track from the neutral midpoint to the current grip."""

    def _draw(self, no_color_updates=False):
        super()._draw(no_color_updates)
        tag = 'centered_progress'
        canvas = self._canvas
        if self.cget('state') == 'disabled' or self.get() == 0:
            canvas.itemconfigure(tag, state='hidden')
            return
        grip = canvas.bbox('slider_parts')
        rail = canvas.bbox('inner_parts')
        if grip is None or rail is None:
            return
        midpoint = (rail[0] + rail[2]) / 2
        grip_center = (grip[0] + grip[2]) / 2
        coords = (min(midpoint, grip_center), max(0, rail[1]),
                  max(midpoint, grip_center), min(self._apply_widget_scaling(self._current_height), rail[3]))
        if canvas.find_withtag(tag):
            canvas.coords(tag, *coords)
            canvas.itemconfigure(tag, state='normal')
        else:
            canvas.create_rectangle(*coords, fill=GOLD_DARK, width=0, state='normal', tags=(tag,))
        canvas.tag_lower(tag, 'slider_parts')


def bind_slider_wheel(slider, enabled, step):
    windows = slider.tk.call('tk', 'windowingsystem') == 'win32'
    remainder = 0

    def scroll(event, ticks=None):
        nonlocal remainder
        if not event.state & SHIFT_MASK or not enabled():
            remainder = 0
            return None
        if ticks is None:
            delta = event.delta
            if windows:
                delta += remainder
                ticks = int(delta / 120)
                remainder = delta - 120 * ticks
            else:
                ticks = (delta > 0) - (delta < 0)
        if ticks:
            step(ticks)
        return 'break'

    def reset(_event):
        nonlocal remainder
        remainder = 0

    canvas = slider._canvas
    canvas.bind('<MouseWheel>', scroll)
    canvas.bind('<Button-4>', lambda event: scroll(event, 1))
    canvas.bind('<Button-5>', lambda event: scroll(event, -1))
    canvas.bind('<Leave>', reset, add='+')


def bind_slider_reset(slider, enabled, reset):
    resetting = False

    def double_click(_event):
        nonlocal resetting
        resetting = enabled()
        if resetting:
            return 'break'

    def release(_event):
        nonlocal resetting
        if resetting:
            resetting = False
            if enabled():
                reset()
            return 'break'

    # Motion before the second release can still change the slider value.
    slider.bind('<Double-Button-1>', double_click)
    slider.bind('<ButtonRelease-1>', release)
