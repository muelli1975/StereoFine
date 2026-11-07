"""Native widget-state, text-entry and output-option integration checks."""
from copy import deepcopy
from pathlib import Path
import time
import sys
from unittest.mock import patch

import customtkinter as ctk
import numpy as np
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
    assert app.sbs_suffix_display.get() == '_cs (COSIMA)'
    assert '_sbs (StereoFine)' not in app.sbs_suffix_menu.cget('values')
    assert app._effective_sbs_suffix() == '_sbs'
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
    assert app.sbs_suffix_menu.cget('text_color') == TEXT_DISABLED
    assert app.sbs_suffix_menu.cget('text_color_disabled') == TEXT_DISABLED
    assert app.sbs_suffix_menu.cget('fg_color') == SECONDARY_BG
    assert app.sbs_suffix_menu.cget('border_color') == BORDER
    assert app.sbs_suffix_menu.cget('button_color') == HOVER_BG
    entry = app.sbs_suffix_menu._entry
    entry.event_generate('<ButtonPress-1>', x=5, y=5)
    entry.event_generate('<ButtonRelease-1>', x=5, y=5)
    assert not app.use_custom_sbs_suffix.get()
    assert app._effective_sbs_suffix() == '_sbs'
    app.custom_sbs_suffix_box.toggle()
    assert app.use_custom_sbs_suffix.get()
    assert app._effective_sbs_suffix() == '_cs'
    assert app.sbs_suffix_menu.cget('text_color') == TEXT_PRIMARY
    # Native Entry bindings must edit text before the application's shortcuts.
    before = deepcopy(app.current.state)
    mode = app.preview_mode.get()
    app.sbs_suffix_display.set('')
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
    def assert_image_keys_work():
        app.update()
        focused = app.focus_get()
        assert focused is not None and focused is not entry, str(focused)
        before_x = app.current.state.manual.delta_x_px
        focused.event_generate('<KeyPress-Right>')
        focused.event_generate('<KeyRelease-Right>')
        app.update()
        assert app.current.state.manual.delta_x_px == before_x+1

    def edit(text='_mein_sbs'):
        entry.focus_force()
        app.update()
        app.sbs_suffix_display.set(text)
        assert app.focus_get() is entry

    # No focus recovery in the test: the actual exit action must restore keys.
    assert_image_keys_work()
    # Win32 Tk maps both Enter keys to Return; KP_Enter has no virtual keycode
    # there (tk/win/tkWinKey.c). Generate the platform's actual native symbol.
    keypad_enter = '<Return>' if sys.platform == 'win32' else '<KP_Enter>'
    for sequence in (keypad_enter, '<Escape>', '<Tab>', '<Shift-Tab>'):
        edit()
        print(f'Suffix focus exit: {language} {sequence}', flush=True)
        entry.event_generate(sequence)
        assert_image_keys_work()
    edit('invalid?')
    with patch('stereofine.gui.messagebox.showerror') as error:
        entry.event_generate('<Return>')
        app.update()
        assert error.call_count == 1
        assert app.focus_get() is entry
        assert app.busy_state == 'idle'
    entry.event_generate('<Escape>')
    assert app.sbs_suffix_display.get() == '_mein_sbs'
    assert_image_keys_work()
    # Invoke the real menu entry callbacks, including the no-suffix option.
    for index, expected in enumerate(('_s', '_cs', '-lr', '')):
        edit()
        app.sbs_suffix_menu._dropdown_menu.invoke(index)
        assert app.settings.sbs_suffix == expected
        assert_image_keys_work()
    for target in (app.preview_label._label, app.preview_frame, app.output_path_label._label):
        edit()
        target.event_generate('<ButtonPress-1>', x=5, y=5)
        target.event_generate('<ButtonRelease-1>', x=5, y=5)
        assert_image_keys_work()
    edit()
    app.save_anaglyph_box.toggle()
    assert_image_keys_work()
    app.save_anaglyph_box.toggle()
    edit()
    app.custom_sbs_suffix_box.toggle()
    assert not app.use_custom_sbs_suffix.get()
    assert app._effective_sbs_suffix() == '_sbs'
    assert app.sbs_suffix_menu.cget('text_color') == TEXT_DISABLED
    assert_image_keys_work()
    app.custom_sbs_suffix_box.toggle()
    # A different option menu and a cancelled native-dialog action must also
    # relinquish the editor, before their command is executed.
    edit()
    app.analysis_method_menu._dropdown_menu.invoke(0)
    assert_image_keys_work()
    edit()
    with patch('stereofine.gui.filedialog.askdirectory', return_value=''):
        app.choose_output_button.invoke()
    assert_image_keys_work()
    # Exercise the real source-loading worker, not a test-only session swap.
    source = app.current.source
    edit()
    app._set_source_collection([source], 0, batch=False)
    deadline = time.monotonic()+30
    while app.busy_state != 'idle' and time.monotonic() < deadline:
        app.update()
        time.sleep(.01)
    assert app.busy_state == 'idle'
    assert app.current.source == source
    first_loaded = np.asarray(app._preview_pil).copy()
    deadline = time.monotonic()+.4
    while time.monotonic() < deadline:
        app.update()
        np.testing.assert_array_equal(np.asarray(app._preview_pil), first_loaded)
        time.sleep(.01)
    assert_image_keys_work()
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
                       enter_escape_tab_restore_image_keys=True, suffix_selection_restores_image_keys=True,
                       outside_clicks_and_other_actions_restore_image_keys=True,
                       source_loading_restores_image_keys=True,
                       first_loaded_frame_is_stable=True,
                       disabled_colors_match_shared_palette=True, output_options_dpi_checked=True))
