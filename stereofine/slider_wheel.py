"""Use Shift-wheel only over an enabled image editing slider."""


def bind_slider_wheel(slider, enabled, step):
    windows = slider.tk.call('tk', 'windowingsystem') == 'win32'
    remainder = 0

    def scroll(event, ticks=None):
        nonlocal remainder
        if not enabled():
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

    slider.bind('<Shift-MouseWheel>', scroll)
    slider.bind('<Shift-Button-4>', lambda event: scroll(event, 1))
    slider.bind('<Shift-Button-5>', lambda event: scroll(event, -1))
    slider.bind('<Leave>', reset)
