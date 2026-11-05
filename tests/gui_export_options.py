"""Native widget-state, text-entry and output-option integration checks."""
from copy import deepcopy
from pathlib import Path

import customtkinter as ctk
from PIL import ImageGrab

from stereofine.output_naming import suffix_labels
from stereofine.theme import BORDER, GOLD_DARK, HOVER_BG, SECONDARY_BG, TEXT_DISABLED, TEXT_PRIMARY


def check_export_options(app, checks, language):
    assert app.save_anaglyph.get()
    assert app.save_anaglyph_box.cget('text') == app._t('save_anaglyph')
    assert app.gray_anaglyph_box.cget('text') == app._t('gray_anaglyph')
    def left_padding(widget):
        padding = widget.grid_info()['padx']
        return padding[0] if isinstance(padding, (tuple, list)) else padding
    assert left_padding(app.gray_anaglyph_box) > left_padding(app.save_anaglyph_box)
    assert app.sbs_suffix_menu.cget('values') == suffix_labels(language)
    assert '_cs (COSIMA)' in app.sbs_suffix_menu.cget('values')
    app.gray_anaglyph.set(True)
    for save in (False, True):
        app.save_anaglyph.set(save)
        app._on_export_options_changed()
        assert app.gray_anaglyph.get()
        assert app.gray_anaglyph_box.cget('state') == ('normal' if save else 'disabled')
        assert app.gray_anaglyph_box.cget('fg_color') == (GOLD_DARK if save else TEXT_DISABLED)
        assert app.gray_anaglyph_box.cget('text_color_disabled') == TEXT_DISABLED
        assert app.gray_anaglyph_box.cget('checkmark_color') == TEXT_PRIMARY
    app.use_custom_sbs_suffix.set(True)
    app._on_export_options_changed()
    app.sbs_suffix_display.set('_cs (COSIMA)')
    app._on_sbs_suffix_selected()
    assert app._effective_sbs_suffix() == '_cs'
    app.use_custom_sbs_suffix.set(False)
    app._on_export_options_changed()
    assert app._effective_sbs_suffix() == '_sbs'
    assert app.settings.sbs_suffix == '_cs'
    assert app.sbs_suffix_menu.cget('state') == 'disabled'
    assert app.sbs_suffix_menu.cget('text_color_disabled') == TEXT_DISABLED
    assert app.sbs_suffix_menu.cget('fg_color') == SECONDARY_BG
    assert app.sbs_suffix_menu.cget('border_color') == BORDER
    assert app.sbs_suffix_menu.cget('button_color') == HOVER_BG
    app.use_custom_sbs_suffix.set(True)
    app._on_export_options_changed()
    # Native Entry bindings must edit text before the application's shortcuts.
    before = deepcopy(app.current.state)
    mode = app.preview_mode.get()
    app.sbs_suffix_display.set('')
    entry = app.sbs_suffix_menu._entry
    entry.focus_force()
    app.update()
    for key in ('a', 'f', 'g', 's', 'z', 'm', 'l', 'r', 't', 'b', 'space'):
        entry.event_generate('<KeyPress>', keysym=key)
        entry.event_generate('<KeyRelease>', keysym=key)
    for key in ('Left', 'Right', 'Up', 'Down', 'Prior', 'Next'):
        entry.event_generate('<KeyPress>', keysym=key)
        entry.event_generate('<KeyRelease>', keysym=key)
    assert app.sbs_suffix_display.get() == 'afgszmlrtb '
    assert app.current.state == before
    assert app.preview_mode.get() == mode
    assert app.busy_state == 'idle' and not app.detail_active and not app.measure_cross_active
    app.sbs_suffix_display.set('_mein_sbs')
    entry.event_generate('<KeyPress-Return>')
    entry.event_generate('<KeyRelease-Return>')
    assert app.settings.sbs_suffix == '_mein_sbs'
    assert app.busy_state == 'idle'
    app.focus_force()
    app.update()
    for busy in ('save', 'batch', 'analysis', 'idle'):
        app.busy_state = busy
        app._refresh_control_states()
        assert app.gray_anaglyph_box.cget('state') == ('normal' if busy == 'idle' else 'disabled')
        assert app.sbs_suffix_menu.cget('state') == ('normal' if busy == 'idle' else 'disabled')
        assert app.settings.sbs_suffix == '_mein_sbs'
    for scale in (1., 1.5, 2.):
        ctk.set_widget_scaling(scale)
        ctk.set_window_scaling(scale)
        app.update()
        assert app.gray_anaglyph_box.winfo_x()+app.gray_anaglyph_box.winfo_width() <= app.sidebar.winfo_width()+2
        assert app.sbs_suffix_menu.winfo_x()+app.sbs_suffix_menu.winfo_width() <= app.sidebar.winfo_width()+2
    ctk.set_widget_scaling(1.)
    ctk.set_window_scaling(1.)
    app.save_anaglyph.set(False)
    app._on_export_options_changed()
    app.sidebar._parent_canvas.yview_moveto(.65)
    app.update()
    Path('build').mkdir(exist_ok=True)
    ImageGrab.grab().save(f'build/gui-tiff-detail-output-{language}.png')
    app.save_anaglyph.set(True)
    app.use_custom_sbs_suffix.set(False)
    app._on_export_options_changed()
    app._reset_keyboard_modes()
    checks.append(dict(language=language, optional_anaglyph_retains_grayscale=True,
                       custom_suffix_preserved=True, text_entry_never_edits_image=True,
                       disabled_colors_match_shared_palette=True, output_options_dpi_checked=True))
