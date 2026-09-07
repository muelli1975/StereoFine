from __future__ import annotations

import math
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageGrab

import stereofine.gui as gui
from stereofine.processing import ProcessingDefaults
from stereofine.session import browse_source, source_from_selected_stereo_file
from stereofine.settings import AppSettings


def main() -> None:
    settings = AppSettings(
        use_input_output_subfolder=True,
        output_mode="both",
        analysis_method="AKAZE",
        color_match_enabled=False,
    )
    gui.load_settings = lambda: settings
    gui.save_settings = lambda value: Path("/dev/null")

    with tempfile.TemporaryDirectory(prefix="stereofine_layout_") as td:
        root = Path(td)
        master = Image.open(gui.asset_path("stereofine.jpg")).convert("RGB")
        target_w = 1000
        target_h = max(2, round(master.height * target_w / master.width))
        small = master.resize((target_w, target_h), Image.Resampling.LANCZOS)
        path = root / "layout_reference.jpg"
        small.save(path, quality=95, subsampling=0)

        source = source_from_selected_stereo_file(path)
        session = browse_source(source, ProcessingDefaults())
        state = session.state
        state.alignment.valid = True
        state.alignment.method = "AKAZE"
        state.alignment.model = "Affine"
        state.alignment.vertical_error_mean_px = 0.112
        state.alignment.correction = {
            "vertical_shift_px": -0.030,
            "rotation_deg": -0.0003,
        }
        state.disparity.valid = True
        state.disparity.stale = False
        state.disparity.total_permille = 19.81
        state.disparity.low_edge_permille = -20.44
        state.disparity.high_edge_permille = -0.63
        state.disparity.traffic = "green"
        state.disparity.traffic_label = "grün"
        state.framing.auto_near_offset_x_px = 3
        state.framing.auto_near_base_width_px = 1000
        state.framing.auto_near_status = "ok"

        app = gui.StereoFineApp()
        try:
            app.sources = [source]
            app.source_index = 0
            app.current = session
            app.batch_mode = False
            app._sync_vars_from_current()
            app._render_status()
            app._refresh_control_states()
            app._refresh_preview()
            app.update_idletasks()
            app.update()

            # At the normal 1400x850 launch size the established compact layout
            # layout stays intact, but tighter status row metrics must leave a
            # materially larger scrollable control area above it.
            assert app.winfo_width() == 1400
            assert app.winfo_height() == 850
            assert app.status_frame.winfo_height() <= 220, app.status_frame.winfo_height()
            # The compact v41-style one-button action slot is restored: the
            # start button itself becomes Cancel while work runs, so no second
            # permanent button row consumes sidebar height.
            assert app.sidebar_bottom.winfo_height() <= 445, app.sidebar_bottom.winfo_height()
            # The scrollable controls stay visually bounded by the two subtle
            # one-pixel separators around the scroll area. This
            # checks the actually rendered screen pixels, not only widget
            # existence/geometry alone.
            assert app.header_separator.winfo_height() == 1
            assert app.status_separator.winfo_height() == 1
            screen = ImageGrab.grab()
            expected_separator_rgb = (51, 51, 51)
            for separator in (app.header_separator, app.status_separator):
                sx = separator.winfo_rootx() + separator.winfo_width() // 2
                sy = separator.winfo_rooty()
                assert screen.getpixel((sx, sy))[:3] == expected_separator_rgb
            # Font tuples are deliberately GUI-resource-free; creating CTkFont
            # objects here can let their Tcl destructor run in a worker thread.
            assert app._font(13, "bold") == (gui.FONT_FAMILY, 13, "bold")
            # Primary action: same 42 px / 15 px-bold family geometry as
            # SplatTricia, but StereoFine keeps its compact one-button workflow.
            assert app.start_button.cget("height") == 42
            assert app.start_button.cget("fg_color") == gui.SECONDARY_BG
            assert app.start_button.cget("hover_color") == gui.GOLD_LIGHT
            assert app.start_button.cget("border_color") == gui.GOLD_DARK

            # Exercise the real mouse event path and verify the actual rendered
            # fill, not just internal variables. This is the regression that the
            # earlier release checks missed.
            app.update_idletasks(); app.update()
            bx = app.start_button.winfo_rootx() + 24
            by = app.start_button.winfo_rooty() + app.start_button.winfo_height() // 2
            rest_screen = ImageGrab.grab()
            assert rest_screen.getpixel((bx, by))[:3] == (24, 24, 24)
            app.start_button._canvas.event_generate("<Enter>", x=24, y=app.start_button.winfo_height() // 2)
            app.update_idletasks(); app.update()
            assert app.start_button.cget("fg_color") == gui.GOLD_LIGHT
            assert app.start_button.cget("text_color") == gui.APP_BG
            assert app.start_button.cget("border_color") == gui.GOLD_LIGHT
            hover_screen = ImageGrab.grab()
            assert hover_screen.getpixel((bx, by))[:3] == (198, 169, 94)
            app.start_button._canvas.event_generate("<Leave>", x=1, y=1)
            app.update_idletasks(); app.update()
            assert app.start_button.cget("fg_color") == gui.SECONDARY_BG
            assert app.start_button.cget("text_color") == gui.GOLD_LIGHT
            assert app.start_button.cget("border_color") == gui.GOLD_DARK

            # Ordinary buttons remain SplatTricia-style secondary actions: dark
            # gray border at rest and on hover, no accidental gold decoration.
            assert app.choose_output_button.cget("border_color") == gui.BORDER
            assert app.choose_output_button.cget("hover_color") == gui.HOVER_BG

            # The spinner is an opaque pre-composited image on the exact sidebar
            # background.  This avoids platform-dependent Tk alpha seams. Sample
            # the full 360-degree track and require a visible non-background
            # pixel at every angle.
            spinner = gui._render_activity_spinner_frame(0)
            assert spinner.mode == "RGB"
            cx = (spinner.width - 1) / 2.0
            cy = (spinner.height - 1) / 2.0
            radius = 14.25
            bg = gui.ACTIVITY_SPINNER_BG
            for degree in range(360):
                rad = math.radians(degree)
                # Downsampling can move the strongest ring pixel by about one
                # pixel radially. Search a narrow radial neighborhood instead of
                # assuming the sample center lands on the same raster cell at
                # every angle.
                contrast = 0
                for dr in (-1.5, -0.75, 0.0, 0.75, 1.5):
                    px = int(round(cx + math.cos(rad) * (radius + dr)))
                    py = int(round(cy + math.sin(rad) * (radius + dr)))
                    pixel = spinner.getpixel((px, py))
                    contrast = max(contrast, max(abs(int(pixel[i]) - int(bg[i])) for i in range(3)))
                assert contrast >= 8, (degree, contrast)
            # The ring now occupies a structural grid slot rather than a place()
            # overlay that could be clipped by later status widgets on Windows.
            assert app.activity_canvas.winfo_manager() == "grid"

            # Test the actually composited GUI, not only the PIL source frame:
            # every angle of the track must still be visible after Tk/Canvas
            # rendering and widget stacking.
            app.busy_state = "busy"
            app._start_activity()
            app.update_idletasks(); app.update()
            screen_spinner = ImageGrab.grab()
            root_x = app.activity_canvas.winfo_rootx()
            root_y = app.activity_canvas.winfo_rooty()
            scx = root_x + (gui.ACTIVITY_SPINNER_SIZE - 1) / 2.0
            scy = root_y + (gui.ACTIVITY_SPINNER_SIZE - 1) / 2.0
            bg_screen = tuple(int(v) for v in gui.ACTIVITY_SPINNER_BG)
            for degree in range(360):
                rad = math.radians(degree)
                contrast = 0
                for dr in (-1.5, -0.75, 0.0, 0.75, 1.5):
                    px = int(round(scx + math.cos(rad) * (radius + dr)))
                    py = int(round(scy + math.sin(rad) * (radius + dr)))
                    pixel = screen_spinner.getpixel((px, py))[:3]
                    contrast = max(contrast, max(abs(int(pixel[i]) - bg_screen[i]) for i in range(3)))
                assert contrast >= 8, (degree, contrast)
            app.busy_state = "idle"
            app._finish_activity()
            assert not hasattr(app, "grid_hint_label")
            available_scroll_height = (
                app.sidebar_container.winfo_height()
                - app.sidebar_header.winfo_height()
                - app.sidebar_bottom.winfo_height()
            )
            assert available_scroll_height >= 300, available_scroll_height

            # The startup geometry must never be centered partly outside the
            # available display.  This guards the cropped-sidebar screenshot
            # left sidebar being positioned partly outside a smaller desktop.
            assert app.winfo_x() >= 0 and app.winfo_y() >= 0
            assert app.winfo_x() + app.winfo_width() <= app.winfo_screenwidth()
            assert app.winfo_y() + app.winfo_height() <= app.winfo_screenheight()

            # Dependent output text and grid controls have visibly coherent
            # active/inactive states.
            assert app.custom_output_label.cget("text_color") == gui.TEXT_DISABLED
            assert app.output_path_label.cget("text_color") == gui.TEXT_DISABLED
            assert app.grid_mode.get() == "Aus"
            assert app.grid_spacing_menu.cget("state") == "normal"
            assert app.grid_spacing_label.cget("text_color") == gui.TEXT_PRIMARY
            app.grid_mode.set("Weiß")
            app._on_grid_mode_changed()
            assert app.grid_spacing_menu.cget("state") == "normal"
            app.grid_mode.set("Aus")
            app._on_grid_mode_changed()
            assert app.grid_spacing_menu.cget("state") == "normal"

            # Mouse-wheel scrolling stays on CustomTkinter's native path, as in
            # the stable one-file line.  A normal child control must be accepted
            # by CTkScrollableFrame itself; StereoFine must not install a second
            # competing global wheel handler.
            canvas = app.sidebar._parent_canvas
            before_yview = canvas.yview()
            class _WheelEvent:
                pass
            wheel_event = _WheelEvent()
            wheel_event.widget = app.fullscreen_button
            if sys.platform.startswith("linux"):
                wheel_event.num = 5
                wheel_event.delta = 0
            else:
                wheel_event.delta = -120
            app.sidebar._mouse_wheel_all(wheel_event)
            app.update_idletasks(); app.update()
            after_yview = canvas.yview()
            assert after_yview[0] > before_yview[0], (before_yview, after_yview)
            canvas.yview_moveto(0.0)

            # The declared minimum window size must remain structurally usable:
            # fixed header/status/action areas fit and the controls stay in the
            # scrollable middle region rather than being clipped off-screen.
            app.geometry("1100x700")
            app.update_idletasks(); app.update()
            assert app.winfo_width() >= 1100 and app.winfo_height() >= 700
            min_scroll_height = (
                app.sidebar_container.winfo_height()
                - app.sidebar_header.winfo_height()
                - app.sidebar_bottom.winfo_height()
            )
            assert min_scroll_height > 100, min_scroll_height
            app.geometry("1400x850")
            app.update_idletasks(); app.update()

            app.toggle_fullscreen()
            app.update_idletasks(); app.update()
            assert app.fullscreen_button.cget("text") == "Fensteransicht"
            app._on_escape()
            app.update_idletasks(); app.update()
            assert app.fullscreen_button.cget("text") == "Vollbild"

            # Language switching is live and must keep canonical image
            # state values while translating only their visible labels.
            app._on_language_changed("English")
            app.update_idletasks()
            app.update()
            assert app.settings.language == "en"
            assert app.fullscreen_button.cget("text") == "Fullscreen"
            assert app.output_aspect.get() == "maximum"
            assert app.output_aspect_display.get() == "Maximum"
            assert not hasattr(app, "output_mode")
            assert app.help_footer_label.cget("text") == "F1 · Keyboard help"
            assert app.help_footer_label.cget("text_color") == gui.GOLD_LIGHT
            assert "90° right" in app.left_orientation_menu.cget("values")

            # F1 help may use a comfortably larger desktop window, but must
            # remain a real two-column table without scrolling or clipped rows.
            app.show_shortcuts_help()
            app.update_idletasks(); app.update()
            help_window = app._shortcut_help_window
            assert help_window is not None and help_window.winfo_exists()
            def descendants(widget):
                result = []
                for child in widget.winfo_children():
                    result.append(child)
                    result.extend(descendants(child))
                return result
            help_descendants = descendants(help_window)
            assert not any(child.__class__.__name__ == "CTkScrollableFrame" for child in help_descendants)
            assert help_window.winfo_reqheight() <= help_window.winfo_height()
            help_texts = []
            for child in help_descendants:
                try:
                    if "text" in child.keys():
                        value = str(child.cget("text") or "")
                        if value:
                            help_texts.append(value)
                except Exception:
                    pass
            # The formerly clipped bottom-left Crop block must include both rows.
            assert "Crop" in help_texts, help_texts
            assert "Move crop" in help_texts, help_texts
            assert "Zoom" in help_texts, help_texts
            app._close_shortcuts_help()

            # Walk every currently visible widget and make sure the English GUI
            # does not retain common German UI labels.  "Deutsch" itself is
            # intentionally present in the language selector.
            def visible_texts(widget):
                found = []
                for child in widget.winfo_children():
                    try:
                        if child.winfo_viewable() and "text" in child.keys():
                            value = str(child.cget("text") or "")
                            if value:
                                found.append(value)
                    except Exception:
                        pass
                    found.extend(visible_texts(child))
                return found

            joined = "\n".join(visible_texts(app))
            for forbidden in (
                "Stapelverarbeitung",
                "Nur Analyse",
                "Nur Favoriten",
                "Ausrichtung",
                "Analyseverfahren",
                "Seitenverhältnis",
                "Symmetrische Farbangleichung",
                "Auswählen",
                "Vorschau",
                "Gitter",
                "Einstellungen:",
                "Tastaturhilfe:",
            ):
                assert forbidden not in joined, (forbidden, joined)

            print("GUI layout smoke OK")
            print(f"sidebar_bottom={app.sidebar_bottom.winfo_height()} px")
            print(f"scroll_area={available_scroll_height} px")
        finally:
            app.destroy()


if __name__ == "__main__":
    main()
