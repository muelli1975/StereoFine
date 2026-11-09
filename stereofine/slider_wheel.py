"""Mouse gestures scoped to an enabled image editing slider."""


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

    slider.bind('<MouseWheel>', scroll)
    slider.bind('<Button-4>', lambda event: scroll(event, 1))
    slider.bind('<Button-5>', lambda event: scroll(event, -1))
    slider.bind('<Leave>', reset)


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
