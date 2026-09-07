from __future__ import annotations

import math
import queue
import re
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageTk

from .anaglyph import make_anaglyph
from .batch import BatchRunOptions, BatchRunResult, run_batch
from .config import (
    APP_NAME,
    APP_VERSION,
    ASPECT_RATIOS,
    CROP_ZOOM_LEVELS,
    GRID_SPACING_OPTIONS,
)
from .geometry import framing_crop_geometry
from .i18n import (
    Translator,
    aspect_code,
    aspect_label,
    grid_spacing_code,
    grid_spacing_label,
    language_code,
    language_label,
    orientation_code,
    orientation_label,
)
from .notifications import play_ready_sound
from .preview import draw_grid_overlay, draw_measure_cross_overlay
from .preview_render import PreviewBasePair, build_preview_base, render_preview_from_base
from .processing import ProcessedSource, ProcessingDefaults, ProcessingOptions, process_source
from .resources import asset_path
from .session import (
    BrowsedSource,
    browse_source,
    save_browsed_state,
    source_from_selected_pair_image,
    source_from_selected_stereo_file,
)
from .settings import AppSettings, load_settings, save_settings
from .sidecar import SidecarStatus, load_sidecar
from .sources import StereoSource, discover_pair_sources, discover_stereo_file_sources
from .status import build_status_sections, sidecar_status_text
from .theme import (
    APP_BG,
    BORDER,
    CONTROL_RADIUS,
    DANGER,
    DANGER_HOVER,
    FONT_FAMILY,
    GOLD_DARK,
    GOLD_LIGHT,
    HOVER_BG,
    PANEL_BG,
    PANEL_RADIUS,
    PREVIEW_BG,
    SECONDARY_BG,
    SPACE_1,
    SPACE_2,
    SPACE_3,
    SPACE_4,
    TEXT_DISABLED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    TRAFFIC_GRAY,
    TRAFFIC_GREEN,
    TRAFFIC_ORANGE,
    TRAFFIC_RED,
    preview_border_px,
)
from .worker import WorkerManager, WorkerMessageKind

WINDOW_WIDTH = 1400
WINDOW_HEIGHT = 850
SIDEBAR_WIDTH = 340
STATUS_SYMBOL_COLUMN_WIDTH = 36
ACTIVITY_SPINNER_SIZE = 36
ACTIVITY_SPINNER_RENDER_SCALE = 5
ACTIVITY_SPINNER_FRAME_COUNT = 60
ACTIVITY_FRAME_MS = 16
ACTIVITY_SPINNER_PERIOD_SEC = 1.0
ACTIVITY_MIN_VISIBLE_MS = 200
ACTIVITY_SPINNER_TRACK = (74, 62, 38)
ACTIVITY_SPINNER_ARC = (198, 169, 94)
ACTIVITY_SPINNER_BG = (24, 24, 24)


def _render_activity_spinner_frame(frame_index: int) -> Image.Image:
    """Return one opaque antialiased spinner frame with a closed track.

    The track is rendered pre-composited on the exact sidebar background.  This
    deliberately avoids semi-transparent PhotoImage edges, which can produce
    platform-dependent seams in Tk on Windows even when the source annulus is
    mathematically closed.
    """
    size = max(20, int(ACTIVITY_SPINNER_SIZE))
    render_scale = max(2, int(ACTIVITY_SPINNER_RENDER_SCALE))
    frame_count = max(12, int(ACTIVITY_SPINNER_FRAME_COUNT))
    render_size = size * render_scale

    center = (render_size - 1) / 2.0
    radius = 14.25 * render_scale
    line_width = max(2, int(round(3.0 * render_scale)))

    img = Image.new("RGB", (render_size, render_size), ACTIVITY_SPINNER_BG)
    draw = ImageDraw.Draw(img)
    bbox = (center - radius, center - radius, center + radius, center + radius)

    # One true ellipse is the complete base track. It has no start/end point and
    # therefore no possible 0/360-degree seam.
    draw.ellipse(bbox, outline=ACTIVITY_SPINNER_TRACK, width=line_width)

    angle = (360.0 * float(frame_index % frame_count) / float(frame_count)) % 360.0
    start_deg = -135.0 + angle
    sweep_deg = 90.0
    # Keep the moving segment deliberately simple.  The previous extra circular
    # end caps made the endpoints thicker than the arc on Windows (the visible
    # "Knubbel").  A high-resolution Pillow arc downsampled with Lanczos already
    # gives clean antialiased ends without changing the segment thickness.
    draw.arc(bbox, start=start_deg, end=start_deg + sweep_deg, fill=ACTIVITY_SPINNER_ARC, width=line_width)

    return img.resize((size, size), Image.Resampling.LANCZOS)


# Interactive preview rendering is deliberately decoupled from window size.
# Geometry is rendered once at a useful working resolution; resizing the main
# window only rescales the already rendered anaglyph, which restores the
# immediate feel of the stable v41 preview path.
PREVIEW_RENDER_MAX_WIDTH = 1600
PREVIEW_RENDER_MAX_HEIGHT = 1000
PREVIEW_RESIZE_DEBOUNCE_MS = 150

MEASURE_REPEAT_MS = 16
MEASURE_HOLD_DELAY_MS = 200
MEASURE_START_SPEED_PX_PER_SEC = 320.0
MEASURE_MAX_SPEED_PX_PER_SEC = 900.0
MEASURE_ACCEL_TIME_SEC = 0.55
MEASURE_MAX_DT_SEC = 0.050

def _count_text(count: int, singular: str, plural: str | None = None) -> str:
    plural = plural or singular + "e"
    return f"{count} {singular if count == 1 else plural}"


class StereoFineApp(ctk.CTk):
    """StereoFine 1.0 GUI shell over the GUI-independent processing core."""

    def __init__(self) -> None:
        ctk.set_appearance_mode("dark")
        # No CustomTkinter color theme is used as a design source. Every visible
        # color below is explicitly defined by the shared Stereo-Tool standard.
        super().__init__()

        self.settings: AppSettings = load_settings()
        self.tr = Translator(self.settings.language)
        self.worker = WorkerManager()
        self.current_job_id: str | None = None
        self.current_job_kind: str | None = None
        self.busy_state = "idle"
        self._busy_started_at: float | None = None
        self._spinner_job: str | None = None
        self._spinner_stop_job: str | None = None
        self._spinner_frame_index = 0
        self._spinner_frames: list[ImageTk.PhotoImage] = []

        self.current: BrowsedSource | None = None
        self.sources: list[StereoSource] = []
        self.source_index: int | None = None
        self.batch_mode = False
        # Transient batch-preview identity.  The browsed source/index remains
        # untouched during a worker run so navigation can be restored cleanly;
        # these fields describe the lightweight image that is actually shown.
        self._batch_progress_index: int | None = None
        self._batch_progress_total: int | None = None
        self._batch_progress_source_name: str | None = None
        self._load_rollback_context: tuple[list[StereoSource], int | None, bool, str] | None = None
        self._save_after_id: str | None = None
        self._state_dirty = False
        self._state_dirty_can_create_sidecar = False
        self._resize_after_id: str | None = None
        self._resize_fast_after_id: str | None = None
        self._status_after_id: str | None = None

        self.preview_mode = ctk.StringVar(value="Farbig")
        self.language_display = ctk.StringVar(value=language_label(self.settings.language))
        self.grid_mode = ctk.StringVar(value="Aus")
        self.grid_spacing = ctk.StringVar(value="50 Promille")
        self.grid_spacing_display = ctk.StringVar(value=grid_spacing_label("50 Promille", self.settings.language))
        self.analysis_method = ctk.StringVar(value=self.settings.analysis_method)
        self.left_orientation = ctk.StringVar(value="0")
        self.right_orientation = ctk.StringVar(value="0")
        self.left_orientation_display = ctk.StringVar(value=orientation_label("0", self.settings.language))
        self.right_orientation_display = ctk.StringVar(value=orientation_label("0", self.settings.language))
        self.left_mirror = ctk.BooleanVar(value=False)
        self.right_mirror = ctk.BooleanVar(value=False)
        self.swap_eyes = ctk.BooleanVar(value=False)
        self.output_aspect = ctk.StringVar(value=self.settings.default_aspect)
        self.output_aspect_display = ctk.StringVar(value=aspect_label(self.settings.default_aspect, self.settings.language))
        self.color_match_enabled = ctk.BooleanVar(value=self.settings.color_match_enabled)
        self.use_input_subfolder = ctk.BooleanVar(value=self.settings.use_input_output_subfolder)
        # Batch special modes are session/job state, not persistent preferences.
        self.analysis_only = ctk.BooleanVar(value=False)
        self.favorites_only = ctk.BooleanVar(value=False)
        self.float_lr_symmetric = ctk.BooleanVar(value=False)

        self.measure_cross_active = False
        self.measure_cross_x: float | None = None
        self.measure_cross_y: float | None = None
        self._measure_repeat_job: str | None = None
        self._measure_repeat_direction: str | None = None
        self._measure_hold_started_at: float | None = None
        self._measure_last_tick_at: float | None = None
        self._floating_key_edge: str | None = None
        self._g_key_down = False
        self._shortcut_keys_down: set[str] = set()
        self._shortcut_help_window: ctk.CTkToplevel | None = None
        self._preview_pil: Image.Image | None = None
        self._preview_ctk_image: ctk.CTkImage | None = None
        self._preview_pair_shape: tuple[int, int] | None = None
        self._preview_display_size: tuple[int, int] | None = None
        self._preview_base: PreviewBasePair | None = None
        self._preview_base_session_id: int | None = None
        self._preview_left_current = None
        self._preview_right_current = None
        self.fullscreen = False

        self._lock_widgets: list[Any] = []
        self._checkbox_widgets: list[Any] = []
        self._radio_widgets: list[Any] = []

        self.title(f"{APP_NAME} – {APP_VERSION}")
        self.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.minsize(1100, 700)
        self.configure(fg_color=APP_BG)
        try:
            self.iconbitmap(str(asset_path("stereofine.ico")))
        except Exception:
            pass

        self._build_layout()
        self._bind_shortcuts()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(50, self._center_window)
        self.after(20, self._poll_worker_messages)
        self.after(120, self._load_start_image)
        self._refresh_output_state()
        self._refresh_control_states()

    # ------------------------------------------------------------------
    # Widget construction / shared styling
    # ------------------------------------------------------------------
    def _t(self, key: str, **values: object) -> str:
        return self.tr.t(key, **values)

    def _sync_localized_display_vars(self) -> None:
        language = self.settings.language
        self.language_display.set(language_label(language))
        self.left_orientation_display.set(orientation_label(self.left_orientation.get(), language))
        self.right_orientation_display.set(orientation_label(self.right_orientation.get(), language))
        self.output_aspect_display.set(aspect_label(self.output_aspect.get(), language))
        self.grid_spacing_display.set(grid_spacing_label(self.grid_spacing.get(), language))

    def _rebuild_for_language(self) -> None:
        if self.busy_state != "idle":
            return
        self._close_shortcuts_help()
        self.tr = Translator(self.settings.language)
        self._sync_localized_display_vars()
        self._lock_widgets = []
        self._checkbox_widgets = []
        self._radio_widgets = []
        for child in list(self.winfo_children()):
            child.destroy()
        # _build_sidebar_bottom() renders status before recreating the footer.
        # Remove references to destroyed footer widgets so the status refresh
        # cannot accidentally address stale Tcl commands during a live language
        # switch.
        for name in ("sidecar_status_label", "favorite_label"):
            if hasattr(self, name):
                delattr(self, name)
        self._status_line_widgets = {}
        self._status_widgets = []
        self._build_layout()
        self._refresh_output_state()
        self._render_status()
        self._refresh_control_states()
        self._refresh_preview()

    def _on_language_changed(self, label: str) -> None:
        code = language_code(label)
        if code == self.settings.language:
            return
        self.settings.language = code
        save_settings(self.settings)
        self._rebuild_for_language()

    def _image_filetypes(self) -> list[tuple[str, str]]:
        if self.settings.language == "en":
            return [("Image files", "*.jpg *.jpeg *.png *.tif *.tiff"), ("All files", "*.*")]
        return [("Bilddateien", "*.jpg *.jpeg *.png *.tif *.tiff"), ("Alle Dateien", "*.*")]

    def _stereo_filetypes(self) -> list[tuple[str, str]]:
        if self.settings.language == "en":
            return [("Stereo files", "*.jpg *.jpeg *.png *.tif *.tiff *.mpo"), ("All files", "*.*")]
        return [("Stereodateien", "*.jpg *.jpeg *.png *.tif *.tiff *.mpo"), ("Alle Dateien", "*.*")]

    @staticmethod
    def _font(size: int = 13, weight: str = "normal") -> tuple[str, int, str]:
        # Use CustomTkinter's supported tuple-font form instead of creating a
        # tkinter Font/CTkFont object for every widget.  Tk font objects own Tcl
        # resources whose destructor may otherwise be triggered by Python's
        # garbage collector from a worker thread while OpenCV is running.  A
        # tuple stays GUI-thread-neutral and is still DPI-scaled by CustomTkinter.
        return (FONT_FAMILY, size, weight)

    def _secondary_button(self, parent, text: str, command, **kwargs):
        button = ctk.CTkButton(
            parent,
            text=text,
            command=command,
            fg_color=SECONDARY_BG,
            hover_color=HOVER_BG,
            border_color=BORDER,
            border_width=1,
            text_color=TEXT_PRIMARY,
            text_color_disabled=TEXT_DISABLED,
            corner_radius=CONTROL_RADIUS,
            font=self._font(13),
            **kwargs,
        )
        self._lock_widgets.append(button)
        return button

    def _primary_button(self, parent, text: str, command, **kwargs):
        button = ctk.CTkButton(
            parent,
            text=text,
            command=command,
            fg_color=SECONDARY_BG,
            hover_color=GOLD_LIGHT,
            border_color=GOLD_DARK,
            border_width=1,
            text_color=GOLD_LIGHT,
            text_color_disabled=TEXT_DISABLED,
            corner_radius=CONTROL_RADIUS,
            font=self._font(15, "bold"),
            **kwargs,
        )
        return button

    def _checkbox(self, parent, text: str, variable, command=None):
        box = ctk.CTkCheckBox(
            parent,
            text=text,
            variable=variable,
            command=command,
            fg_color=GOLD_DARK,
            hover_color=GOLD_LIGHT,
            border_color=BORDER,
            checkmark_color=TEXT_PRIMARY,
            text_color=TEXT_PRIMARY,
            corner_radius=4,
            font=self._font(13),
        )
        self._lock_widgets.append(box)
        self._checkbox_widgets.append(box)
        return box

    def _option_menu(self, parent, *, values: list[str], variable, command=None):
        menu = ctk.CTkOptionMenu(
            parent,
            values=values,
            variable=variable,
            command=command,
            fg_color=PANEL_BG,
            button_color=HOVER_BG,
            button_hover_color=BORDER,
            dropdown_fg_color=SECONDARY_BG,
            dropdown_hover_color=HOVER_BG,
            text_color=TEXT_PRIMARY,
            dropdown_text_color=TEXT_PRIMARY,
            corner_radius=CONTROL_RADIUS,
            font=self._font(13),
            dropdown_font=self._font(13),
        )
        self._lock_widgets.append(menu)
        return menu

    def _section_title(self, parent, text: str, row: int) -> None:
        ctk.CTkLabel(
            parent,
            text=text,
            text_color=TEXT_PRIMARY,
            font=self._font(16, "bold"),
            anchor="w",
        ).grid(row=row, column=0, sticky="ew", padx=20, pady=(20, 8))

    def _hint(self, parent, text: str, row: int, *, pady=(0, 10)) -> ctk.CTkLabel:
        label = ctk.CTkLabel(
            parent,
            text=text,
            text_color=TEXT_SECONDARY,
            font=self._font(12),
            wraplength=286,
            justify="left",
            anchor="w",
        )
        label.grid(row=row, column=0, sticky="ew", padx=20, pady=pady)
        return label

    def _two_button_row(self, parent, row: int, left_text: str, left_command, right_text: str, right_command):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=row, column=0, sticky="ew", padx=20, pady=(0, 8))
        frame.grid_columnconfigure((0, 1), weight=1)
        left = self._secondary_button(frame, left_text, left_command)
        right = self._secondary_button(frame, right_text, right_command)
        left.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        right.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        return left, right

    def _separator(self, parent, row: int):
        # A native Tk frame is used deliberately: CTkFrame can visually swallow
        # a logical 1 px height on some scaling/rendering paths. This separator
        # must be visibly present, not merely exist in the widget tree.
        separator = tk.Frame(parent, height=1, bg=BORDER, bd=0, highlightthickness=0)
        separator.grid(row=row, column=0, columnspan=2, sticky="ew", padx=20, pady=0)
        separator.grid_propagate(False)
        return separator

    def _build_layout(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar_container = ctk.CTkFrame(self, width=SIDEBAR_WIDTH, corner_radius=0, fg_color=SECONDARY_BG)
        self.sidebar_container.grid(row=0, column=0, sticky="nsw")
        self.sidebar_container.grid_propagate(False)
        self.sidebar_container.grid_columnconfigure(0, weight=1)
        self.sidebar_container.grid_rowconfigure(1, weight=1)

        self.sidebar_header = ctk.CTkFrame(self.sidebar_container, fg_color=SECONDARY_BG, corner_radius=0)
        self.sidebar_header.grid(row=0, column=0, sticky="ew")
        self.sidebar_header.grid_columnconfigure(0, weight=1)
        self.sidebar_header.grid_columnconfigure(1, weight=0)

        self.sidebar = ctk.CTkScrollableFrame(
            self.sidebar_container,
            width=SIDEBAR_WIDTH,
            corner_radius=0,
            fg_color=SECONDARY_BG,
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=HOVER_BG,
        )
        self.sidebar.grid(row=1, column=0, sticky="nsew")
        self.sidebar.grid_columnconfigure(0, weight=1)

        self.sidebar_bottom = ctk.CTkFrame(self.sidebar_container, fg_color=SECONDARY_BG, corner_radius=0)
        self.sidebar_bottom.grid(row=2, column=0, sticky="ew")
        self.sidebar_bottom.grid_columnconfigure(0, weight=1)

        self.preview_frame = ctk.CTkFrame(self, fg_color=PREVIEW_BG, corner_radius=0)
        self.preview_frame.grid(row=0, column=1, sticky="nsew")
        self.preview_frame.grid_columnconfigure(0, weight=1)
        self.preview_frame.grid_rowconfigure(0, weight=1)
        self.preview_frame.bind("<Configure>", self._on_preview_resize)

        self.preview_label = ctk.CTkLabel(self.preview_frame, text="", fg_color=PREVIEW_BG)
        self.preview_label.grid(row=0, column=0, sticky="nsew", padx=32, pady=32)

        self._build_sidebar_header()
        self._build_sidebar_controls()
        self._build_sidebar_bottom()

    def _build_sidebar_header(self) -> None:
        ctk.CTkLabel(
            self.sidebar_header,
            text=APP_NAME,
            text_color=GOLD_LIGHT,
            font=self._font(26, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=(20, 8), pady=(20, 2))
        ctk.CTkLabel(
            self.sidebar_header,
            text=self._t("subtitle"),
            text_color=TEXT_SECONDARY,
            font=self._font(14),
            anchor="w",
        ).grid(row=1, column=0, columnspan=2, sticky="ew", padx=20, pady=(0, 14))
        self.language_menu = self._option_menu(
            self.sidebar_header,
            values=["Deutsch", "English"],
            variable=self.language_display,
            command=self._on_language_changed,
        )
        self.language_menu.configure(width=92)
        self.language_menu.grid(row=0, column=1, sticky="e", padx=(0, 20), pady=(20, 2))
        self.header_separator = self._separator(self.sidebar_header, 2)

    def _build_sidebar_controls(self) -> None:
        row = 0
        self.fullscreen_button = self._secondary_button(self.sidebar, self._t("fullscreen"), self.toggle_fullscreen)
        self.fullscreen_button.grid(row=row, column=0, sticky="ew", padx=20, pady=(12, 8)); row += 1

        self._section_title(self.sidebar, self._t("input"), row); row += 1
        self._hint(self.sidebar, self._t("single_edit"), row, pady=(0, 4)); row += 1
        self.single_pair_button, self.single_sbs_button = self._two_button_row(
            self.sidebar, row, self._t("left_right"), self.choose_single_pair, self._t("full_sbs_mpo"), self.choose_single_stereo
        ); row += 1
        self._hint(self.sidebar, self._t("batch_processing"), row, pady=(4, 4)); row += 1
        self.batch_pair_button, self.batch_sbs_button = self._two_button_row(
            self.sidebar, row, self._t("left_right"), self.choose_batch_pair, self._t("full_sbs_mpo"), self.choose_batch_stereo
        ); row += 1

        self.analysis_only_box = self._checkbox(self.sidebar, self._t("analysis_only"), self.analysis_only, self._on_batch_mode_option_changed)
        self.analysis_only_box.grid(row=row, column=0, sticky="w", padx=20, pady=(2, 6)); row += 1
        self.favorites_only_box = self._checkbox(self.sidebar, self._t("favorites_only"), self.favorites_only, self._on_batch_mode_option_changed)
        self.favorites_only_box.grid(row=row, column=0, sticky="w", padx=20, pady=(0, 10)); row += 1

        self._section_title(self.sidebar, self._t("alignment"), row); row += 1
        align = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        align.grid(row=row, column=0, sticky="ew", padx=20, pady=(0, 8)); row += 1
        align.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkLabel(align, text=self._t("left"), text_color=TEXT_SECONDARY, font=self._font(12), anchor="w").grid(row=0, column=0, sticky="ew", padx=(0, 4), pady=(0, 4))
        ctk.CTkLabel(align, text=self._t("right"), text_color=TEXT_SECONDARY, font=self._font(12), anchor="w").grid(row=0, column=1, sticky="ew", padx=(4, 0), pady=(0, 4))
        orientation_values = [orientation_label(value, self.settings.language) for value in ["0", "180", "90_cw", "90_ccw"]]
        self.left_orientation_menu = self._option_menu(
            align, values=orientation_values, variable=self.left_orientation_display, command=self._on_left_orientation_display_changed
        )
        self.right_orientation_menu = self._option_menu(
            align, values=orientation_values, variable=self.right_orientation_display, command=self._on_right_orientation_display_changed
        )
        self.left_orientation_menu.grid(row=1, column=0, sticky="ew", padx=(0, 4), pady=(0, 6))
        self.right_orientation_menu.grid(row=1, column=1, sticky="ew", padx=(4, 0), pady=(0, 6))
        self.left_mirror_box = self._checkbox(align, self._t("mirror"), self.left_mirror, self._on_input_transform_changed)
        self.right_mirror_box = self._checkbox(align, self._t("mirror"), self.right_mirror, self._on_input_transform_changed)
        self.left_mirror_box.grid(row=2, column=0, sticky="w", padx=(0, 4))
        self.right_mirror_box.grid(row=2, column=1, sticky="w", padx=(4, 0))
        self.swap_eyes_box = self._checkbox(self.sidebar, self._t("swap_eyes"), self.swap_eyes, self._on_input_transform_changed)
        self.swap_eyes_box.grid(row=row, column=0, sticky="w", padx=20, pady=(0, 8)); row += 1

        ctk.CTkLabel(self.sidebar, text=self._t("analysis_method"), text_color=TEXT_PRIMARY, font=self._font(13), anchor="w").grid(
            row=row, column=0, sticky="ew", padx=20, pady=(4, 4)
        ); row += 1
        self.analysis_method_menu = self._option_menu(
            self.sidebar, values=["AKAZE", "SIFT"], variable=self.analysis_method, command=self._on_analysis_method_changed
        )
        self.analysis_method_menu.grid(row=row, column=0, sticky="ew", padx=20, pady=(0, 8)); row += 1

        self._section_title(self.sidebar, self._t("image_output"), row); row += 1
        ctk.CTkLabel(self.sidebar, text=self._t("aspect_ratio"), text_color=TEXT_PRIMARY, font=self._font(13), anchor="w").grid(
            row=row, column=0, sticky="ew", padx=20, pady=(0, 4)
        ); row += 1
        aspect_values = [aspect_label(value, self.settings.language) for value in ASPECT_RATIOS.keys()]
        self.aspect_menu = self._option_menu(
            self.sidebar, values=aspect_values, variable=self.output_aspect_display, command=self._on_aspect_display_changed
        )
        self.aspect_menu.grid(row=row, column=0, sticky="ew", padx=20, pady=(0, 8)); row += 1

        self.color_match_box = self._checkbox(self.sidebar, self._t("color_match"), self.color_match_enabled, self._on_color_match_changed)
        self.color_match_box.grid(row=row, column=0, sticky="w", padx=20, pady=(0, 8)); row += 1

        self.use_input_subfolder_box = self._checkbox(
            self.sidebar,
            self._t("use_input_subfolder"),
            self.use_input_subfolder,
            self._on_output_folder_mode_changed,
        )
        self.use_input_subfolder_box.grid(row=row, column=0, sticky="w", padx=20, pady=(0, 8)); row += 1
        self.custom_output_label = ctk.CTkLabel(
            self.sidebar,
            text=self._t("custom_output_folder"),
            text_color=TEXT_SECONDARY,
            font=self._font(12),
            anchor="w",
        )
        self.custom_output_label.grid(row=row, column=0, sticky="ew", padx=20, pady=(0, 3)); row += 1
        self.choose_output_button = self._secondary_button(self.sidebar, self._t("choose"), self.choose_output_folder)
        self.choose_output_button.grid(row=row, column=0, sticky="ew", padx=20, pady=(0, 5)); row += 1
        self.output_path_label = ctk.CTkLabel(
            self.sidebar,
            text="–",
            text_color=TEXT_DISABLED if self.use_input_subfolder.get() else TEXT_PRIMARY,
            font=self._font(12),
            wraplength=286,
            justify="left",
            anchor="w",
        )
        self.output_path_label.grid(row=row, column=0, sticky="ew", padx=20, pady=(0, 8)); row += 1

        self._section_title(self.sidebar, self._t("preview"), row); row += 1
        preview_modes = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        preview_modes.grid(row=row, column=0, sticky="ew", padx=20, pady=(0, 8)); row += 1
        preview_modes.grid_columnconfigure((0, 1), weight=1)
        for col, (text, value) in enumerate(((self._t("preview_color"), "Farbig"), (self._t("preview_gray"), "Graustufen"))):
            radio = ctk.CTkRadioButton(
                preview_modes,
                text=text,
                variable=self.preview_mode,
                value=value,
                command=self._on_preview_mode_changed,
                fg_color=GOLD_DARK,
                hover_color=GOLD_LIGHT,
                border_color=BORDER,
                text_color=TEXT_PRIMARY,
                font=self._font(13),
            )
            radio.grid(row=0, column=col, sticky="w", padx=(0 if col == 0 else 4, 4))
            self._lock_widgets.append(radio)
            self._radio_widgets.append(radio)

        ctk.CTkLabel(self.sidebar, text=self._t("grid"), text_color=TEXT_PRIMARY, font=self._font(13), anchor="w").grid(
            row=row, column=0, sticky="ew", padx=20, pady=(2, 4)
        ); row += 1
        grid_modes = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        grid_modes.grid(row=row, column=0, sticky="ew", padx=20, pady=(0, 7)); row += 1
        grid_modes.grid_columnconfigure((0, 1, 2), weight=1)
        for col, (text, value) in enumerate((
            (self._t("grid_off"), "Aus"),
            (self._t("grid_white"), "Weiß"),
            (self._t("grid_black"), "Schwarz"),
        )):
            radio = ctk.CTkRadioButton(
                grid_modes,
                text=text,
                variable=self.grid_mode,
                value=value,
                command=self._on_grid_mode_changed,
                fg_color=GOLD_DARK,
                hover_color=GOLD_LIGHT,
                border_color=BORDER,
                text_color=TEXT_PRIMARY,
                font=self._font(12),
            )
            radio.grid(row=0, column=col, sticky="w", padx=(0 if col == 0 else 3, 3))
            self._lock_widgets.append(radio)
            self._radio_widgets.append(radio)

        self.grid_spacing_label = ctk.CTkLabel(
            self.sidebar, text=self._t("grid_spacing"), text_color=TEXT_DISABLED, font=self._font(12), anchor="w"
        )
        self.grid_spacing_label.grid(row=row, column=0, sticky="ew", padx=20, pady=(0, 4)); row += 1
        grid_values = [grid_spacing_label(value, self.settings.language) for value in GRID_SPACING_OPTIONS]
        self.grid_spacing_menu = self._option_menu(
            self.sidebar, values=grid_values, variable=self.grid_spacing_display, command=self._on_grid_spacing_display_changed
        )
        self.grid_spacing_menu.grid(row=row, column=0, sticky="ew", padx=20, pady=(0, 16)); row += 1
        self._update_grid_control_state()

    def _build_sidebar_bottom(self) -> None:
        self.status_separator = self._separator(self.sidebar_bottom, 0)

        self.status_frame = ctk.CTkFrame(self.sidebar_bottom, fg_color="transparent")
        self.status_frame.grid(row=1, column=0, sticky="ew", padx=20, pady=(8, 3))
        self.status_frame.grid_columnconfigure(0, weight=1)
        self.status_frame.grid_columnconfigure(1, minsize=STATUS_SYMBOL_COLUMN_WIDTH)

        self.activity_canvas = tk.Canvas(
            self.status_frame,
            width=ACTIVITY_SPINNER_SIZE,
            height=ACTIVITY_SPINNER_SIZE,
            bg=SECONDARY_BG,
            bd=0,
            highlightthickness=0,
            relief="flat",
        )
        # Structural symbol-column slot: never overlay the status labels with
        # place(), because that can clip/cover part of the ring on Windows.
        self.activity_canvas.grid(row=0, column=1, rowspan=3, sticky="ne")
        self.traffic_label = ctk.CTkLabel(
            self.status_frame,
            text="●",
            width=STATUS_SYMBOL_COLUMN_WIDTH,
            text_color=TRAFFIC_GRAY,
            font=self._font(26),
            anchor="center",
        )
        self._status_widgets: list[Any] = []
        self._render_status()

        footer = ctk.CTkFrame(self.sidebar_bottom, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 2))
        footer.grid_columnconfigure(0, weight=1)
        footer.grid_columnconfigure(1, minsize=STATUS_SYMBOL_COLUMN_WIDTH)
        self.sidecar_status_label = ctk.CTkLabel(
            footer,
            text=self._t("settings_none"),
            text_color=TEXT_SECONDARY,
            font=self._font(12),
            anchor="w",
        )
        self.sidecar_status_label.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.favorite_label = ctk.CTkLabel(
            footer,
            text="★",
            width=36,
            height=36,
            font=self._font(24),
            text_color=TRAFFIC_GRAY,
            fg_color="transparent",
            anchor="center",
        )
        self.favorite_label.grid(row=0, column=1, sticky="e")
        self.favorite_label.bind("<Button-1>", self._on_favorite_clicked)
        self.favorite_label.bind("<Enter>", lambda _e: self._update_favorite_star(hover=True))
        self.favorite_label.bind("<Leave>", lambda _e: self._update_favorite_star(hover=False))

        nav = ctk.CTkFrame(self.sidebar_bottom, fg_color="transparent")
        nav.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 6))
        nav.grid_columnconfigure((0, 1), weight=1)
        self.previous_button = self._secondary_button(nav, self._t("previous"), self.previous_source)
        self.next_button = self._secondary_button(nav, self._t("next"), self.next_source)
        self.previous_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.next_button.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        # StereoFine intentionally uses one primary action slot. In idle state it
        # starts alignment/batch work; while a worker is active the very same
        # button becomes the cancellation action. This continues the compact v41
        # layout without adding a second permanent button row.
        self.start_button = self._primary_button(
            self.sidebar_bottom, self._t("start_single"), self._on_primary_action, height=42
        )
        self.start_button.grid(row=4, column=0, sticky="ew", padx=20, pady=(0, 6))
        self.start_button.bind("<Enter>", self._on_start_button_enter, add="+")
        self.start_button.bind("<Leave>", self._on_start_button_leave, add="+")

        self.save_button = self._secondary_button(self.sidebar_bottom, self._t("save"), self.save_current_result, height=36)
        self.save_button.grid(row=5, column=0, sticky="ew", padx=20, pady=(0, 4))

        self.help_footer_label = ctk.CTkLabel(
            self.sidebar_bottom,
            text=self._t("help_footer"),
            text_color=GOLD_LIGHT,
            font=self._font(12, "bold"),
            anchor="w",
            cursor="hand2",
        )
        self.help_footer_label.grid(row=6, column=0, sticky="ew", padx=20, pady=(1, 12))
        self.help_footer_label.bind("<Button-1>", self.show_shortcuts_help)
        self.help_footer_label.bind("<Enter>", lambda _e: self.help_footer_label.configure(text_color=TEXT_PRIMARY))
        self.help_footer_label.bind("<Leave>", lambda _e: self.help_footer_label.configure(text_color=GOLD_LIGHT))

    # ------------------------------------------------------------------
    # Status and visual state
    # ------------------------------------------------------------------
    def _input_status_text(self) -> str:
        if self.current is None:
            return "–"
        if self.batch_mode:
            if (
                self.current_job_kind == "batch"
                and self._batch_progress_index is not None
                and self._batch_progress_source_name
            ):
                total = self._batch_progress_total or len(self.sources)
                return (
                    f"{self._t('status_batch_preview', count=total, index=self._batch_progress_index)}\n"
                    f"{self._batch_progress_source_name}"
                )
            index = (self.source_index or 0) + 1
            return f"{self._t('status_batch_preview', count=len(self.sources), index=index)}\n{self.current.source.display_name}"
        if len(self.sources) > 1 and self.source_index is not None:
            return f"{self.current.source.display_name} · {self.source_index + 1}/{len(self.sources)}"
        return self.current.source.display_name

    def _traffic_color(self) -> str:
        if self.current is None:
            return TRAFFIC_GRAY
        disparity = self.current.state.disparity
        if not disparity.valid or disparity.stale:
            return TRAFFIC_GRAY
        value = disparity.traffic
        return {
            "green": TRAFFIC_GREEN,
            "orange": TRAFFIC_ORANGE,
            "red": TRAFFIC_RED,
            "gray": TRAFFIC_GRAY,
        }.get(value, TRAFFIC_GRAY)

    def _schedule_status_refresh(self, delay_ms: int = 90) -> None:
        """Coalesce status redraws during rapid keyboard interaction.

        Status text is updated in place, but coalescing still avoids redundant
        Tcl/configure traffic during cursor-key repeat. The preview stays
        immediate; status catches up after the short interaction burst.
        """
        if self._status_after_id:
            try:
                self.after_cancel(self._status_after_id)
            except Exception:
                pass
            self._status_after_id = None
        self._status_after_id = self.after(max(1, int(delay_ms)), self._run_scheduled_status_refresh)

    def _run_scheduled_status_refresh(self) -> None:
        self._status_after_id = None
        self._render_status()

    def _ensure_status_widgets(self) -> None:
        """Create the status panel once and update it in place afterwards.

        The earlier modular GUI destroyed and recreated every status label for
        each key repeat and again after the debounced sidecar save. On Windows
        this visibly flashed the status/F1-footer area and also generated
        avoidable <Configure> traffic for the preview. Keep a fixed widget
        geometry and only replace text/color values.
        """
        widgets = getattr(self, "_status_line_widgets", None)
        if widgets:
            try:
                if all(widget.winfo_exists() for widget in widgets.values()):
                    return
            except Exception:
                pass

        self._status_line_widgets = {}
        self._status_widgets = []

        def add_label(
            name: str,
            row: int,
            *,
            muted: bool = False,
            bold: bool = False,
            height: int = 19,
        ) -> None:
            label = ctk.CTkLabel(
                self.status_frame,
                text="",
                text_color=TEXT_SECONDARY if muted else TEXT_PRIMARY,
                font=self._font(12 if muted else 13, "bold" if bold else "normal"),
                height=height,
                justify="left",
                anchor="w",
                wraplength=246,
            )
            label.grid(row=row, column=0, sticky="ew", padx=(0, 8), pady=0)
            self._status_line_widgets[name] = label
            self._status_widgets.append(label)

        def add_spacer(row: int, height: int = 4) -> None:
            spacer = ctk.CTkFrame(self.status_frame, height=height, fg_color="transparent")
            # Never span the reserved symbol column; doing so caused the old
            # spinner seam/clipping regression on Windows.
            spacer.grid(row=row, column=0, sticky="ew")
            self._status_widgets.append(spacer)

        # Fixed rows deliberately avoid text wrapping/clipping and, more
        # importantly, prevent the bottom controls from jumping while values
        # change. The batch input row reserves two text lines for filename + n/N.
        add_label("input", 0, height=38)
        add_spacer(1)
        add_label("analysis_model", 2)
        add_label("vertical_error", 3)
        add_label("vertical_shift", 4)
        add_label("rotation", 5)
        add_label("vergence", 6)
        add_spacer(7)
        add_label("deviation", 8)
        add_label("near_far", 9)
        add_label("warning", 10, muted=True)
        add_spacer(11)
        add_label("floating_title", 12, bold=True)
        add_label("floating_values", 13)

    def _render_status(self) -> None:
        """Update the fixed status area without destroying/recreating widgets."""
        if self._status_after_id:
            try:
                self.after_cancel(self._status_after_id)
            except Exception:
                pass
            self._status_after_id = None

        self._ensure_status_widgets()
        labels = self._status_line_widgets

        if self.current is None:
            from .state import PairState
            state = PairState()
        else:
            state = self.current.state

        input_section, analysis, deviation, floating = build_status_sections(
            state, input_text=self._input_status_text(), language=self.settings.language
        )

        input_value = input_section.rows[0].value if input_section.rows else "–"
        labels["input"].configure(text=f"{input_section.name}: {input_value}")

        if analysis and len(analysis.rows) >= 6:
            labels["analysis_model"].configure(
                text=f"{analysis.rows[0].label}: {analysis.rows[0].value} · "
                     f"{analysis.rows[1].label}: {analysis.rows[1].value}"
            )
            labels["vertical_error"].configure(text=f"{analysis.rows[2].label}: {analysis.rows[2].value}")
            labels["vertical_shift"].configure(text=f"{analysis.rows[3].label}: {analysis.rows[3].value}")
            labels["rotation"].configure(text=f"{analysis.rows[4].label}: {analysis.rows[4].value}")
            labels["vergence"].configure(text=f"{analysis.rows[5].label}: {analysis.rows[5].value}")
        else:
            for name in ("analysis_model", "vertical_error", "vertical_shift", "rotation", "vergence"):
                labels[name].configure(text="")

        deviation_item = next((item for item in deviation.rows if item.role == "deviation"), None) if deviation else None
        if deviation_item is not None:
            labels["deviation"].configure(text=f"{deviation_item.label}: {deviation_item.value}")
            self.traffic_label.configure(text_color=self._traffic_color())
            self.traffic_label.grid(row=8, column=1, sticky="e", pady=0)
        else:
            labels["deviation"].configure(text="")
            self.traffic_label.grid_forget()

        normal_items = [item for item in deviation.rows if item.role == "normal"] if deviation else []
        if len(normal_items) >= 2:
            labels["near_far"].configure(
                text=f"{normal_items[0].label}: {normal_items[0].value} · "
                     f"{normal_items[1].label}: {normal_items[1].value}"
            )
        else:
            labels["near_far"].configure(text="")

        warnings = [item.value for item in deviation.rows if item.role == "warning" and item.value] if deviation else []
        # Keep the warning row allocated even when empty. This removes the last
        # source of vertical layout jumps in the status/footer area.
        labels["warning"].configure(text=warnings[0] if warnings else "")

        if floating and len(floating.rows) >= 2:
            labels["floating_title"].configure(text=f"{floating.name}:")
            tb_short = "O/U" if self.settings.language == "de" else "T/B"
            labels["floating_values"].configure(
                text=f"L/R: {floating.rows[0].value} · {tb_short}: {floating.rows[1].value}"
            )
        else:
            labels["floating_title"].configure(text="")
            labels["floating_values"].configure(text="")

        try:
            self.activity_canvas.lift()
        except Exception:
            pass
        if hasattr(self, "sidecar_status_label"):
            self.sidecar_status_label.configure(
                text=sidecar_status_text(self.current.sidecar if self.current else None, self.settings.language)
            )
        self._update_favorite_star()

    def _update_favorite_star(self, hover: bool = False) -> None:
        if not hasattr(self, "favorite_label"):
            return
        active = bool(self.current and self.current.state.favorite)
        can_toggle = bool(self.current and self.busy_state == "idle")
        color = GOLD_DARK if (active or (hover and can_toggle)) else TRAFFIC_GRAY
        if active and hover and can_toggle:
            color = GOLD_LIGHT
        self.favorite_label.configure(text_color=color)
        try:
            self.favorite_label.configure(cursor="hand2" if can_toggle else "")
        except Exception:
            pass

    def _set_checkbox_enabled(self, widget, enabled: bool) -> None:
        widget.configure(
            state="normal" if enabled else "disabled",
            fg_color=GOLD_DARK if enabled else TEXT_DISABLED,
            hover_color=GOLD_LIGHT if enabled else TEXT_DISABLED,
            text_color=TEXT_PRIMARY if enabled else TEXT_DISABLED,
        )

    def _set_radio_enabled(self, widget, enabled: bool) -> None:
        widget.configure(
            state="normal" if enabled else "disabled",
            fg_color=GOLD_DARK if enabled else TEXT_DISABLED,
            hover_color=GOLD_LIGHT if enabled else TEXT_DISABLED,
            text_color=TEXT_PRIMARY if enabled else TEXT_DISABLED,
        )

    def _set_start_button_normal(self) -> None:
        has_source = self.current is not None
        if not has_source:
            self.start_button.configure(
                state="disabled",
                fg_color=SECONDARY_BG,
                hover_color=SECONDARY_BG,
                text_color=TEXT_DISABLED,
                border_color=BORDER,
            )
            return
        self.start_button.configure(
            state="normal",
            fg_color=SECONDARY_BG,
            hover_color=GOLD_LIGHT,
            text_color=GOLD_LIGHT,
            border_color=GOLD_DARK,
        )

    def _set_start_button_hover(self) -> None:
        if self.busy_state != "idle" or self.current is None:
            return
        self.start_button.configure(
            fg_color=GOLD_LIGHT,
            hover_color=GOLD_LIGHT,
            text_color=APP_BG,
            border_color=GOLD_LIGHT,
        )

    def _set_start_button_cancel(self) -> None:
        self.start_button.configure(
            state="normal",
            text=self._t("cancel"),
            fg_color=SECONDARY_BG,
            hover_color=DANGER_HOVER,
            text_color=TEXT_PRIMARY,
            border_color=DANGER,
        )

    def _set_start_button_cancelling(self) -> None:
        self.start_button.configure(
            state="disabled",
            text=self._t("cancelling"),
            fg_color=SECONDARY_BG,
            hover_color=SECONDARY_BG,
            text_color=TEXT_DISABLED,
            border_color=BORDER,
        )

    def _on_start_button_enter(self, _event=None) -> None:
        if self.busy_state == "idle" and self.current is not None:
            self.after_idle(self._set_start_button_hover)

    def _on_start_button_leave(self, _event=None) -> None:
        if self.busy_state == "idle":
            self.after_idle(self._set_start_button_normal)

    def _on_primary_action(self) -> None:
        if self.busy_state != "idle":
            self.cancel_current_job()
        else:
            self.start_processing()

    def _refresh_control_states(self) -> None:
        busy = self.busy_state != "idle"
        has_source = self.current is not None
        can_navigate = not busy and self.source_index is not None

        for widget in self._lock_widgets:
            try:
                widget.configure(state="disabled" if busy else "normal")
            except Exception:
                pass
        for widget in self._checkbox_widgets:
            try:
                self._set_checkbox_enabled(widget, not busy)
            except Exception:
                pass
        for widget in self._radio_widgets:
            try:
                self._set_radio_enabled(widget, not busy)
            except Exception:
                pass

        if self.analysis_only.get():
            try:
                self._set_checkbox_enabled(self.favorites_only_box, False)
            except Exception:
                pass

        custom_active = not self.use_input_subfolder.get()
        custom_color = TEXT_PRIMARY if (custom_active and not busy) else TEXT_DISABLED
        if hasattr(self, "custom_output_label"):
            self.custom_output_label.configure(text_color=custom_color)
        if hasattr(self, "output_path_label"):
            self.output_path_label.configure(text_color=custom_color)

        self.previous_button.configure(
            state="normal" if can_navigate and (self.source_index or 0) > 0 else "disabled"
        )
        self.next_button.configure(
            state="normal" if can_navigate and self.source_index is not None and self.source_index < len(self.sources) - 1 else "disabled"
        )
        self.save_button.configure(state="normal" if has_source and not self.batch_mode and not busy else "disabled")

        if busy:
            self._set_start_button_cancel()
        else:
            self._update_start_button_text()
            self._set_start_button_normal()

        self._update_grid_control_state()
        self._update_favorite_star()

    def _update_start_button_text(self) -> None:
        if self.busy_state != "idle":
            return
        if self.batch_mode:
            if self.analysis_only.get():
                text = self._t("start_analysis")
            elif self.favorites_only.get():
                text = self._t("start_favorites")
            else:
                text = self._t("start_batch")
        else:
            text = self._t("start_single")
        self.start_button.configure(text=text)

    # ------------------------------------------------------------------
    # Activity ring
    # ------------------------------------------------------------------
    def _build_spinner_frames(self) -> None:
        """Pre-render the clean 36 px ring without a base-ring seam."""
        if self._spinner_frames:
            return
        frame_count = max(12, int(ACTIVITY_SPINNER_FRAME_COUNT))
        for frame_index in range(frame_count):
            self._spinner_frames.append(ImageTk.PhotoImage(_render_activity_spinner_frame(frame_index)))

    def _start_activity(self) -> None:
        if self._spinner_stop_job:
            try:
                self.after_cancel(self._spinner_stop_job)
            except Exception:
                pass
            self._spinner_stop_job = None
        self._build_spinner_frames()
        self._busy_started_at = time.perf_counter()
        self._spinner_frame_index = 0
        self._draw_spinner_frame()

    def _draw_spinner_frame(self) -> None:
        self._spinner_job = None
        if self.busy_state == "idle" or not self._spinner_frames:
            return
        frame_count = len(self._spinner_frames)
        now = time.perf_counter()
        frame_index = int((now / max(0.001, ACTIVITY_SPINNER_PERIOD_SEC)) * frame_count) % frame_count
        frame = self._spinner_frames[frame_index]
        self.activity_canvas.delete("all")
        self.activity_canvas.create_image(ACTIVITY_SPINNER_SIZE // 2, ACTIVITY_SPINNER_SIZE // 2, image=frame)
        self.activity_canvas._sf_image = frame  # type: ignore[attr-defined]
        self._spinner_frame_index = frame_index
        self._spinner_job = self.after(ACTIVITY_FRAME_MS, self._draw_spinner_frame)

    def _stop_activity(self) -> None:
        elapsed_ms = 9999.0
        if self._busy_started_at is not None:
            elapsed_ms = (time.perf_counter() - self._busy_started_at) * 1000.0
        remaining = max(0, int(ACTIVITY_MIN_VISIBLE_MS - elapsed_ms))
        if remaining:
            self._spinner_stop_job = self.after(remaining, self._finish_activity)
        else:
            self._finish_activity()

    def _finish_activity(self) -> None:
        self._spinner_stop_job = None
        if self.busy_state != "idle":
            return
        if self._spinner_job:
            try:
                self.after_cancel(self._spinner_job)
            except Exception:
                pass
            self._spinner_job = None
        self.activity_canvas.delete("all")
        self._busy_started_at = None

    # ------------------------------------------------------------------
    # Settings / defaults / output
    # ------------------------------------------------------------------
    def _new_source_defaults(self) -> ProcessingDefaults:
        """Global defaults for the first source in a newly selected collection."""
        return ProcessingDefaults(
            aspect=self.settings.default_aspect,
            color_enabled=bool(self.settings.color_match_enabled),
        )

    def _navigation_defaults(self) -> ProcessingDefaults:
        """Defaults for the next/previous image in the same browsed collection.

        v41 deliberately kept orientation, mirroring and eye order while
        stepping through a folder because a camera series normally shares the
        same physical orientation.  A valid per-image sidecar still wins; these
        values are only used when the target image has no reusable sidecar.
        Aspect and color remain global/per-image preferences and do not leak
        from the currently displayed sidecar.
        """
        if self.current is None:
            return self._new_source_defaults()
        transform = self.current.state.input_transform
        return ProcessingDefaults(
            left_orientation=transform.left_orientation,
            right_orientation=transform.right_orientation,
            left_mirror=bool(transform.left_mirror),
            right_mirror=bool(transform.right_mirror),
            swap_eyes=bool(transform.swap_eyes),
            aspect=self.settings.default_aspect,
            color_enabled=bool(self.settings.color_match_enabled),
        )

    def _batch_defaults(self) -> ProcessingDefaults:
        """Camera-series transform plus global non-geometric defaults for a batch.

        v41 kept orientation/mirroring/eye order while stepping through one
        folder. The same camera-series transform must also seed batch items that
        do not yet own a valid sidecar. Aspect and color remain global defaults
        so values from one image sidecar never leak into another image.
        """
        return self._navigation_defaults()

    def _processing_defaults(self) -> ProcessingDefaults:
        return ProcessingDefaults(
            left_orientation=self.left_orientation.get(),
            right_orientation=self.right_orientation.get(),
            left_mirror=bool(self.left_mirror.get()),
            right_mirror=bool(self.right_mirror.get()),
            swap_eyes=bool(self.swap_eyes.get()),
            aspect=self.output_aspect.get(),
            color_enabled=bool(self.color_match_enabled.get()),
        )

    def _processing_options(
        self,
        *,
        keep_loaded_pair: bool = False,
        use_batch_defaults: bool = False,
    ) -> ProcessingOptions:
        defaults = self._batch_defaults() if use_batch_defaults else self._processing_defaults()
        return ProcessingOptions(
            analysis_method=self.analysis_method.get(),
            save_sidecar=True,
            keep_loaded_pair=keep_loaded_pair,
            defaults=defaults,
        )

    def _persist_settings(self) -> None:
        self.settings.analysis_method = self.analysis_method.get()
        self.settings.color_match_enabled = bool(self.color_match_enabled.get())
        self.settings.default_aspect = self.output_aspect.get()
        self.settings.use_input_output_subfolder = bool(self.use_input_subfolder.get())
        # Output is intentionally fixed: SBS plus one anaglyph.
        self.settings.output_mode = "both"
        save_settings(self.settings)

    def _effective_output_folder(self, root: Path | None = None) -> Path | None:
        if self.use_input_subfolder.get():
            if root is None:
                root = self.current.source.input_root if self.current else None
            return root / "output" if root else None
        if self.settings.custom_output_folder:
            return Path(self.settings.custom_output_folder)
        return None

    def _refresh_output_state(self) -> None:
        path = self.settings.custom_output_folder or "–"
        if hasattr(self, "output_path_label"):
            self.output_path_label.configure(text=path)
        self._refresh_control_states()

    def choose_output_folder(self) -> None:
        initial = self.settings.custom_output_folder or self.settings.last_input_location or str(Path.home())
        selected = filedialog.askdirectory(title=self._t("output_folder_dialog"), initialdir=initial)
        if not selected:
            return
        self.settings.custom_output_folder = str(Path(selected))
        self.use_input_subfolder.set(False)
        self.settings.use_input_output_subfolder = False
        self._persist_settings()
        self._refresh_output_state()

    def _on_left_orientation_display_changed(self, value: str) -> None:
        self.left_orientation.set(orientation_code(value))
        self._on_input_transform_changed()

    def _on_right_orientation_display_changed(self, value: str) -> None:
        self.right_orientation.set(orientation_code(value))
        self._on_input_transform_changed()

    def _on_aspect_display_changed(self, value: str) -> None:
        self.output_aspect.set(aspect_code(value))
        self._on_aspect_changed()

    def _update_grid_control_state(self) -> None:
        if not hasattr(self, "grid_spacing_menu"):
            return
        # The spacing selector remains usable while the grid itself is off.
        # This keeps keyboard and menu state synchronized and lets the user
        # choose the next spacing before re-enabling the overlay.
        editable = self.busy_state == "idle"
        self.grid_spacing_menu.configure(state="normal" if editable else "disabled")
        if hasattr(self, "grid_spacing_label"):
            self.grid_spacing_label.configure(text_color=TEXT_PRIMARY if editable else TEXT_DISABLED)

    def _on_grid_mode_changed(self) -> None:
        self._update_grid_control_state()
        self._update_preview_display()

    def _on_grid_spacing_display_changed(self, value: str) -> None:
        self.grid_spacing.set(grid_spacing_code(value))
        self._update_preview_display()

    def _on_output_folder_mode_changed(self) -> None:
        self._persist_settings()
        self._refresh_output_state()

    def _on_analysis_method_changed(self, _value=None) -> None:
        self._persist_settings()

    def _on_batch_mode_option_changed(self) -> None:
        if self.analysis_only.get():
            self.favorites_only.set(False)
        self._refresh_control_states()

    # ------------------------------------------------------------------
    # Source selection / navigation
    # ------------------------------------------------------------------
    def _dialog_initial_dir(self) -> str:
        value = self.settings.last_input_location
        return value if value and Path(value).exists() else str(Path.home())

    def choose_single_pair(self) -> None:
        selected = filedialog.askopenfilename(
            title=self._t("single_pair_dialog"),
            filetypes=self._image_filetypes(),
            initialdir=self._dialog_initial_dir(),
        )
        if not selected:
            return
        try:
            source = source_from_selected_pair_image(Path(selected))
            sources = discover_pair_sources(source.input_root)
            index = next((i for i, item in enumerate(sources) if item.left_path == source.left_path and item.right_path == source.right_path), 0)
            self._set_source_collection(sources or [source], index, batch=False)
        except Exception as exc:
            messagebox.showerror(APP_NAME, self.tr.message(str(exc)))

    def choose_single_stereo(self) -> None:
        selected = filedialog.askopenfilename(
            title=self._t("single_stereo_dialog"),
            filetypes=self._stereo_filetypes(),
            initialdir=self._dialog_initial_dir(),
        )
        if not selected:
            return
        path = Path(selected)
        source = source_from_selected_stereo_file(path)
        sources = discover_stereo_file_sources(path.parent)
        index = next((i for i, item in enumerate(sources) if item.left_path == path), 0)
        self._set_source_collection(sources or [source], index, batch=False)

    def choose_batch_pair(self) -> None:
        selected = filedialog.askdirectory(title=self._t("batch_pair_dialog"), initialdir=self._dialog_initial_dir())
        if not selected:
            return
        folder = Path(selected)
        sources = discover_pair_sources(folder)
        if not sources:
            messagebox.showerror(APP_NAME, self._t("no_pair_files"))
            return
        self._set_source_collection(sources, 0, batch=True)

    def choose_batch_stereo(self) -> None:
        selected = filedialog.askdirectory(title=self._t("batch_stereo_dialog"), initialdir=self._dialog_initial_dir())
        if not selected:
            return
        folder = Path(selected)
        sources = discover_stereo_file_sources(folder)
        if not sources:
            messagebox.showerror(APP_NAME, self._t("no_stereo_files"))
            return
        self._set_source_collection(sources, 0, batch=True)

    def _set_source_collection(self, sources: list[StereoSource], index: int, *, batch: bool) -> None:
        if not sources:
            return
        target_index = max(0, min(len(sources) - 1, int(index)))
        rollback = (
            list(self.sources),
            self.source_index,
            bool(self.batch_mode),
            str(self.settings.last_input_location or ""),
        )
        inherit_input_transform = False
        if self.current is not None:
            try:
                inherit_input_transform = (
                    self.current.source.input_root.resolve() == sources[target_index].input_root.resolve()
                )
            except Exception:
                inherit_input_transform = self.current.source.input_root == sources[target_index].input_root
            self._flush_state_save()
        self.sources = list(sources)
        self.source_index = target_index
        self.batch_mode = bool(batch)
        self.settings.last_input_location = str(sources[self.source_index].input_root)
        self._persist_settings()
        # Re-selecting another image from the same folder is the same camera
        # series workflow as Page Up/Page Down in v41: keep orientation, mirror
        # and eye order unless the target has its own valid sidecar.
        self._load_source_index(
            self.source_index,
            inherit_input_transform=inherit_input_transform,
            rollback_context=rollback,
        )

    def previous_source(self, event=None):
        if self.busy_state != "idle" or self.source_index is None or self.source_index <= 0:
            return "break"
        self._flush_state_save()
        self._load_source_index(self.source_index - 1, inherit_input_transform=True)
        return "break"

    def next_source(self, event=None):
        if self.busy_state != "idle" or self.source_index is None or self.source_index >= len(self.sources) - 1:
            return "break"
        self._flush_state_save()
        self._load_source_index(self.source_index + 1, inherit_input_transform=True)
        return "break"

    def _load_source_index(
        self,
        index: int,
        *,
        inherit_input_transform: bool = False,
        rollback_context: tuple[list[StereoSource], int | None, bool, str] | None = None,
    ) -> None:
        if not (0 <= index < len(self.sources)):
            return
        if rollback_context is None:
            rollback_context = (
                list(self.sources),
                self.source_index,
                bool(self.batch_mode),
                str(self.settings.last_input_location or ""),
            )
        self._load_rollback_context = rollback_context
        source = self.sources[index]
        self.source_index = index
        self.measure_cross_active = False
        self.measure_cross_x = None
        self.measure_cross_y = None
        self._stop_measure_repeat()

        # Tk variables must never be read from the worker thread.  When the
        # user steps through one folder, preserve the current camera-series
        # orientation exactly as v41 did.  A target image's valid sidecar still
        # overrides these defaults.
        defaults = self._navigation_defaults() if inherit_input_transform else self._new_source_defaults()

        def job(_token, _progress):
            return browse_source(source, defaults)

        self._start_worker("load", self._t("loading"), job)

    def _restore_load_rollback(self) -> None:
        context = self._load_rollback_context
        self._load_rollback_context = None
        if context is None:
            return
        sources, index, batch_mode, last_input = context
        self.sources = list(sources)
        self.source_index = index
        self.batch_mode = bool(batch_mode)
        self.settings.last_input_location = last_input
        try:
            self._persist_settings()
        except Exception:
            pass
        if self.current is not None:
            self._sync_vars_from_current()
            self._refresh_preview()
            self._render_status()
            self._refresh_control_states()

    def _sync_vars_from_current(self) -> None:
        if self.current is None:
            return
        state = self.current.state
        self.left_orientation.set(state.input_transform.left_orientation)
        self.right_orientation.set(state.input_transform.right_orientation)
        self.left_mirror.set(state.input_transform.left_mirror)
        self.right_mirror.set(state.input_transform.right_mirror)
        self.swap_eyes.set(state.input_transform.swap_eyes)
        self.output_aspect.set(state.framing.aspect)
        self.color_match_enabled.set(state.color.enabled)
        self._sync_localized_display_vars()
        # Analysis method is a processing preference, not a per-image GUI
        # default. The status area still shows the method used by this sidecar.
        self.analysis_method.set(self.settings.analysis_method)

    # ------------------------------------------------------------------
    # Per-image state edits
    # ------------------------------------------------------------------
    def _schedule_state_save(self, *, immediate: bool = False, create_if_missing: bool = True) -> None:
        if self.current is None:
            return
        self._state_dirty = True
        self._state_dirty_can_create_sidecar = self._state_dirty_can_create_sidecar or bool(create_if_missing)
        if self._save_after_id:
            try:
                self.after_cancel(self._save_after_id)
            except Exception:
                pass
            self._save_after_id = None

        has_reusable_sidecar = self.current.sidecar.status in {SidecarStatus.VALID, SidecarStatus.MIGRATED}
        if not create_if_missing and not has_reusable_sidecar:
            # Orientation/mirror-only changes on a new source remain session
            # state until a real edit/analysis/export establishes a sidecar.
            return
        if immediate:
            self._flush_state_save()
        else:
            self._save_after_id = self.after(220, self._flush_state_save)

    def _flush_state_save(self) -> None:
        if self._save_after_id:
            try:
                self.after_cancel(self._save_after_id)
            except Exception:
                pass
            self._save_after_id = None
        if self.current is None or not self._state_dirty:
            return

        has_reusable_sidecar = self.current.sidecar.status in {SidecarStatus.VALID, SidecarStatus.MIGRATED}
        should_write = has_reusable_sidecar or self._state_dirty_can_create_sidecar
        try:
            if should_write:
                save_browsed_state(self.current)
                self.current.sidecar = load_sidecar(self.current.source.sidecar_path, expected_source=self.current.source_stamp)
                self._render_status()
        except Exception:
            # Debounced key edits must not interrupt the session with modal errors.
            # A later explicit analysis/export will surface hard file errors.
            pass
        finally:
            self._state_dirty = False
            self._state_dirty_can_create_sidecar = False

    def _on_input_transform_changed(self, _value=None) -> None:
        self.left_orientation_display.set(orientation_label(self.left_orientation.get(), self.settings.language))
        self.right_orientation_display.set(orientation_label(self.right_orientation.get(), self.settings.language))
        if self.current is None or self.busy_state != "idle":
            return
        state = self.current.state
        changed = (
            state.input_transform.left_orientation != self.left_orientation.get()
            or state.input_transform.right_orientation != self.right_orientation.get()
            or state.input_transform.left_mirror != bool(self.left_mirror.get())
            or state.input_transform.right_mirror != bool(self.right_mirror.get())
            or state.input_transform.swap_eyes != bool(self.swap_eyes.get())
        )
        state.input_transform.left_orientation = self.left_orientation.get()
        state.input_transform.right_orientation = self.right_orientation.get()
        state.input_transform.left_mirror = bool(self.left_mirror.get())
        state.input_transform.right_mirror = bool(self.right_mirror.get())
        state.input_transform.swap_eyes = bool(self.swap_eyes.get())
        if changed:
            state.invalidate_for_input_transform()
        self._schedule_state_save(create_if_missing=False)
        self._refresh_preview(rebuild_base=True)
        self._render_status()

    def _on_aspect_changed(self, _value=None) -> None:
        self.output_aspect_display.set(aspect_label(self.output_aspect.get(), self.settings.language))
        self.settings.default_aspect = self.output_aspect.get()
        self._persist_settings()
        if self.current is None or self.busy_state != "idle":
            return
        state = self.current.state
        if state.framing.aspect != self.output_aspect.get():
            state.framing.aspect = self.output_aspect.get()
            state.framing.pan_x_permille = 0
            state.framing.pan_y_permille = 0
            state.invalidate_disparity_for_framing("aspect_changed")
        self._schedule_state_save()
        self._refresh_preview()
        self._render_status()

    def _on_color_match_changed(self) -> None:
        self.settings.color_match_enabled = bool(self.color_match_enabled.get())
        self._persist_settings()
        if self.current is None or self.busy_state != "idle":
            return
        self.current.state.color.enabled = bool(self.color_match_enabled.get())
        self.current.state.color.strength = 1.0
        self._schedule_state_save()
        self._refresh_preview(rebuild_base=True)

    def _on_favorite_clicked(self, _event=None):
        if self.current is None or self.busy_state != "idle":
            return "break"
        self.current.state.favorite = not self.current.state.favorite
        self._schedule_state_save(immediate=True)
        self._update_favorite_star()
        return "break"

    def reset_manual_to_auto(self) -> None:
        if self.current is None or self.busy_state != "idle":
            return
        self.current.state.reset_manual_to_auto()
        self._schedule_state_save(immediate=True)
        self._refresh_preview()
        self._render_status()

    def _adjust_manual_offset(self, dx: int = 0, dy: int = 0) -> None:
        if self.current is None or self.busy_state != "idle":
            return
        state = self.current.state
        state.manual.delta_x_px += int(dx)
        state.manual.delta_y_px += int(dy)
        state.color.valid = False
        if dy:
            state.disparity.invalidate()
            state.disparity.status = "stale"
        self._schedule_state_save()
        self._refresh_preview()
        self._schedule_status_refresh()

    def _adjust_crop_zoom(self, delta: int) -> None:
        if self.current is None or self.busy_state != "idle":
            return
        state = self.current.state
        old = state.framing.crop_zoom_index
        state.framing.crop_zoom_index = max(0, min(len(CROP_ZOOM_LEVELS) - 1, old + int(delta)))
        if state.framing.crop_zoom_index != old:
            state.invalidate_disparity_for_framing("crop_changed")
            self._schedule_state_save()
            self._refresh_preview()
            self._schedule_status_refresh()

    def _framing_step_permille(self, axis: str = "x") -> int:
        if self.current is None or self._preview_pair_shape is None:
            return 1000
        width, height = self._preview_pair_shape
        state = self.current.state
        crop_w, crop_h, max_x, max_y = framing_crop_geometry(
            width,
            height,
            state.framing.aspect,
            CROP_ZOOM_LEVELS[state.framing.crop_zoom_index],
            width / max(1, height),
        )
        _ = crop_w, crop_h
        max_shift = max_x if axis == "x" else max_y
        if max_shift <= 0.5:
            return 1000
        return max(1, int(round(5.0 / max_shift * 1000.0)))

    def _adjust_framing_pan(self, dx: int = 0, dy: int = 0) -> None:
        if self.current is None or self.busy_state != "idle":
            return
        state = self.current.state
        old = (state.framing.pan_x_permille, state.framing.pan_y_permille)
        state.framing.pan_x_permille = max(-1000, min(1000, state.framing.pan_x_permille + int(dx)))
        state.framing.pan_y_permille = max(-1000, min(1000, state.framing.pan_y_permille + int(dy)))
        if old != (state.framing.pan_x_permille, state.framing.pan_y_permille):
            state.invalidate_disparity_for_framing("crop_moved")
            self._schedule_state_save()
            self._refresh_preview()
            self._schedule_status_refresh()

    def _adjust_floating_edge(self, edge: str, delta: int) -> None:
        if self.current is None or self.busy_state != "idle":
            return
        fw = self.current.state.floating_window
        if edge == "left":
            fw.left_permille = max(0, min(30, fw.left_permille + delta))
            if self.float_lr_symmetric.get():
                fw.right_permille = fw.left_permille
            if fw.left_permille > 0:
                fw.top_permille = 0
                fw.bottom_permille = 0
        elif edge == "right":
            fw.right_permille = max(0, min(30, fw.right_permille + delta))
            if self.float_lr_symmetric.get():
                fw.left_permille = fw.right_permille
            if fw.right_permille > 0:
                fw.top_permille = 0
                fw.bottom_permille = 0
        elif edge == "top":
            fw.top_permille = max(0, min(30, fw.top_permille + delta))
            if fw.top_permille > 0:
                fw.bottom_permille = 0
                fw.left_permille = 0
                fw.right_permille = 0
        elif edge == "bottom":
            fw.bottom_permille = max(0, min(30, fw.bottom_permille + delta))
            if fw.bottom_permille > 0:
                fw.top_permille = 0
                fw.left_permille = 0
                fw.right_permille = 0
        else:
            return
        fw.normalize()
        self._schedule_state_save()
        # Proven v41 data flow: the current preview pair itself carries the
        # Floating-Window masks; the preview anaglyph is built directly from it.
        if self.current is not None:
            self._render_session_preview(self.current)
        self._schedule_status_refresh()

    # ------------------------------------------------------------------
    # Preview rendering
    # ------------------------------------------------------------------
    def _invalidate_preview_base(self) -> None:
        self._preview_base = None
        self._preview_base_session_id = None
        self._preview_left_current = None
        self._preview_right_current = None

    def _load_start_image(self) -> None:
        try:
            source = source_from_selected_stereo_file(asset_path("stereofine.jpg"))
            session = browse_source(source, ProcessingDefaults())
            # Start image is branding only: never expose or persist its sidecar state.
            self._invalidate_preview_base()
            self._render_session_preview(session, start_image=True)
        except Exception as exc:
            self.preview_label.configure(text=self._t("start_image_error", text=self.tr.message(str(exc))), text_color=TEXT_PRIMARY, image=None)

    def _preview_bounds(self) -> tuple[int, int]:
        width = self.preview_frame.winfo_width()
        height = self.preview_frame.winfo_height()
        if width < 300 or height < 300:
            width = max(300, WINDOW_WIDTH - SIDEBAR_WIDTH)
            height = max(300, WINDOW_HEIGHT)

        # The black preview border is outside the image and must never cover the
        # image edge.  Reserve enough room for the shared Stereo-Tool rule
        # (3% of displayed image width + 2 px, minimum 16 px) before scaling
        # the image.  The previous modular code subtracted only 40 px total and
        # added the dynamic border afterwards; at normal window sizes that could
        # clip the complete 30‰ Floating-Window area on screen.
        border_reserve = preview_border_px(width)
        return (
            max(200, width - border_reserve * 2),
            max(200, height - border_reserve * 2),
        )

    def _ensure_preview_base(self, session: BrowsedSource, *, start_image: bool = False) -> PreviewBasePair:
        session_id = id(session)
        if self._preview_base is None or self._preview_base_session_id != session_id:
            bound_w, bound_h = self._preview_bounds()
            self._preview_base = build_preview_base(
                session.loaded_pair,
                session.state,
                max_width=min(PREVIEW_RENDER_MAX_WIDTH, max(320, int(bound_w))),
                max_height=min(PREVIEW_RENDER_MAX_HEIGHT, max(240, int(bound_h))),
                apply_color=not start_image,
            )
            self._preview_base_session_id = session_id
        return self._preview_base

    def _build_preview_anaglyph(self) -> None:
        if self._preview_left_current is None or self._preview_right_current is None:
            return

        # As in the proven v41 data flow, the current preview pair already
        # contains the Floating-Window masks.  Build the anaglyph from that
        # authoritative pair using StereoFine's current colorimetric mixer.
        gray = self.preview_mode.get() == "Graustufen"
        self._preview_pil = Image.fromarray(
            make_anaglyph(self._preview_left_current, self._preview_right_current, gray=gray),
            "RGB",
        )
        self._update_preview_display()

    def _render_session_preview(self, session: BrowsedSource, *, start_image: bool = False) -> None:
        base = self._ensure_preview_base(session, start_image=start_image)
        pair = render_preview_from_base(
            base,
            session.state,
            apply_color=not start_image,
            apply_floating_window=not start_image,
        )
        self._preview_left_current = pair.left
        self._preview_right_current = pair.right
        self._preview_pair_shape = (pair.left.shape[1], pair.left.shape[0])
        self._build_preview_anaglyph()

    def _update_preview_display(self, *, resampling=Image.Resampling.LANCZOS) -> None:
        """Scale the already rendered anaglyph to the current window only.

        No image loading, orientation, alignment warp or color fitting is done
        here.  This is the hot path used by window resizing, grid changes and
        the measurement cross.
        """
        if self._preview_pil is None:
            return

        max_width, max_height = self._preview_bounds()
        source_w, source_h = self._preview_pil.size
        scale = min(max_width / max(1, source_w), max_height / max(1, source_h))
        display_size = (
            max(1, int(round(source_w * scale))),
            max(1, int(round(source_h * scale))),
        )
        if display_size == self._preview_pil.size:
            image = self._preview_pil.copy()
        else:
            image = self._preview_pil.resize(display_size, resampling)

        # Overlays belong to the visible preview and therefore stay crisp and
        # correctly scaled while the main window changes size.
        if not self.measure_cross_active and self.grid_mode.get() != "Aus":
            image = draw_grid_overlay(image, self.grid_spacing.get(), self.grid_mode.get())
        if self.measure_cross_active:
            if self._preview_display_size and self.measure_cross_x is not None and self.measure_cross_y is not None:
                old_w, old_h = self._preview_display_size
                if old_w > 0 and old_h > 0 and (old_w, old_h) != display_size:
                    self.measure_cross_x *= display_size[0] / old_w
                    self.measure_cross_y *= display_size[1] / old_h
            self._preview_display_size = display_size
            self._clamp_measure_cross(display_size)
            image = draw_measure_cross_overlay(image, self.measure_cross_x, self.measure_cross_y)
        else:
            self._preview_display_size = display_size

        border = preview_border_px(display_size[0])
        self.preview_label.grid_configure(padx=border, pady=border)
        self._preview_ctk_image = ctk.CTkImage(light_image=image, dark_image=image, size=image.size)
        self.preview_label.configure(text="", image=self._preview_ctk_image)

    def _refresh_preview(self, *, rebuild_base: bool = False) -> None:
        if rebuild_base:
            self._invalidate_preview_base()
        if self.current is not None:
            try:
                self._render_session_preview(self.current)
            except Exception as exc:
                self.preview_label.configure(text=self._t("preview_error", text=self.tr.message(str(exc))), text_color=TEXT_PRIMARY, image=None)
        else:
            self._load_start_image()

    def _on_preview_mode_changed(self) -> None:
        if self._preview_left_current is not None and self._preview_right_current is not None:
            self._build_preview_anaglyph()
        else:
            self._refresh_preview()

    def _on_preview_resize(self, _event=None) -> None:
        if self._preview_pil is None:
            return
        # Coalesce the flood of <Configure> events, but show a cheap bilinear
        # rescale on the next idle turn so the image visibly follows the window
        # instead of waiting for the resize to finish.
        if self._resize_fast_after_id is None:
            self._resize_fast_after_id = self.after_idle(self._fast_preview_resize)
        if self._resize_after_id:
            try:
                self.after_cancel(self._resize_after_id)
            except Exception:
                pass
        self._resize_after_id = self.after(PREVIEW_RESIZE_DEBOUNCE_MS, self._finish_preview_resize)

    def _fast_preview_resize(self) -> None:
        self._resize_fast_after_id = None
        self._update_preview_display(resampling=Image.Resampling.BILINEAR)

    def _finish_preview_resize(self) -> None:
        self._resize_after_id = None
        # v41 contract: while dragging the window we cheaply scale the existing
        # rendered image, but once resizing settles we rebuild the bounded
        # preview base for the new viewport. Otherwise enlarging the window
        # merely upscales an older smaller proxy and never returns to full
        # preview quality.
        #
        # A threaded batch is the one deliberate exception: its lightweight
        # progress frame has no reusable left/right preview pair. Rebuilding the
        # browsed session here would replace the current batch image with the
        # image that happened to be open before the batch started. Keep that
        # progress frame and only rescale it at high quality.
        if self.current_job_kind == "batch" and self._preview_left_current is None:
            self._update_preview_display(resampling=Image.Resampling.LANCZOS)
            return
        self._refresh_preview(rebuild_base=True)

    # ------------------------------------------------------------------
    # Worker jobs / processing / export
    # ------------------------------------------------------------------
    def _start_worker(self, kind: str, button_text: str, function) -> None:
        if self.busy_state != "idle":
            return
        self.busy_state = kind
        self.current_job_kind = kind
        # ``button_text`` is retained for call-site clarity/history, but the
        # primary action itself is always the active cancellation affordance
        # while work is running. Progress is shown by preview/status/spinner.
        _ = button_text
        self._refresh_control_states()
        self._start_activity()
        job = self.worker.start(function, name=f"StereoFine-{kind}")
        self.current_job_id = job.job_id

    def start_processing(self, event=None):
        if self.current is None or self.busy_state != "idle":
            return "break"
        self._flush_state_save()
        if self.batch_mode:
            self._start_batch_run()
        else:
            source = self.current.source
            options = self._processing_options(keep_loaded_pair=True)

            def job(token, _progress):
                return process_source(source, options, cancellation=token)

            self._start_worker("analysis", self._t("alignment_running"), job)
        return "break"

    def _start_batch_run(self) -> None:
        if not self.sources:
            return
        self._batch_progress_index = None
        self._batch_progress_total = None
        self._batch_progress_source_name = None
        output_folder = None if self.analysis_only.get() else self._effective_output_folder(self.sources[0].input_root)
        if not self.analysis_only.get() and output_folder is None:
            messagebox.showinfo(APP_NAME, self._t("select_output_folder"))
            return
        options = BatchRunOptions(
            processing=self._processing_options(keep_loaded_pair=False, use_batch_defaults=True),
            analysis_only=bool(self.analysis_only.get()),
            favorites_only=bool(self.favorites_only.get()),
            output_folder=output_folder,
            gray_anaglyph=self.preview_mode.get() == "Graustufen",
            language=self.settings.language,
        )

        def job(token, progress):
            return run_batch(self.sources, options, cancellation=token, progress=progress)

        text = self._t("analysis_running") if self.analysis_only.get() else self._t("batch_running")
        self._start_worker("batch", text, job)

    def save_current_result(self, event=None):
        if self.current is None or self.batch_mode or self.busy_state != "idle":
            return "break"
        self._flush_state_save()
        output_folder = self._effective_output_folder(self.current.source.input_root)
        if output_folder is None:
            messagebox.showinfo(APP_NAME, self._t("select_output_folder"))
            return "break"
        options = BatchRunOptions(
            processing=self._processing_options(keep_loaded_pair=False),
            output_folder=output_folder,
            gray_anaglyph=self.preview_mode.get() == "Graustufen",
            language=self.settings.language,
        )
        source = self.current.source

        def job(token, progress):
            return run_batch([source], options, cancellation=token, progress=progress)

        self._start_worker("save", self._t("saving"), job)
        return "break"

    def cancel_current_job(self) -> None:
        if self.current_job_id and self.worker.cancel(self.current_job_id):
            self._set_start_button_cancelling()

    def _poll_worker_messages(self) -> None:
        try:
            while True:
                message = self.worker.messages.get_nowait()
                if message.job_id != self.current_job_id:
                    continue
                if message.kind == WorkerMessageKind.PROGRESS:
                    self._handle_progress(message.payload)
                elif message.kind == WorkerMessageKind.RESULT:
                    self._finish_worker_success(message.payload)
                elif message.kind == WorkerMessageKind.CANCELLED:
                    self._finish_worker_cancelled()
                elif message.kind == WorkerMessageKind.ERROR:
                    self._finish_worker_error(message.payload)
        except queue.Empty:
            pass
        finally:
            self.after(20, self._poll_worker_messages)

    def _handle_progress(self, payload: Any) -> None:
        if not (hasattr(payload, "index") and hasattr(payload, "total")):
            return

        if self.current_job_kind == "batch":
            # Progress identity is independent from the optional preview image.
            # The worker reports index/name at analysis/export boundaries for
            # every source, while a lightweight preview may be unavailable for
            # a particular item.  Coupling these states made the status stick at
            # the first image even though the batch continued normally.
            self._batch_progress_index = int(payload.index)
            self._batch_progress_total = int(payload.total)
            self._batch_progress_source_name = str(getattr(payload, "source_name", "") or "")
            self._schedule_status_refresh(1)

        preview_rgb = getattr(payload, "preview_rgb", None)
        if preview_rgb is not None and self.current_job_kind == "batch":
            try:
                self._preview_pil = Image.fromarray(preview_rgb, "RGB")
                self._preview_left_current = None
                self._preview_right_current = None
                self._preview_pair_shape = (int(preview_rgb.shape[1]), int(preview_rgb.shape[0]))
                self._update_preview_display()
            except Exception:
                # A lightweight progress preview must never turn an otherwise
                # valid batch into a processing failure.
                pass

        # Keep the primary action unambiguous while work is active: it remains
        # "Abbrechen/Cancel" instead of being overwritten by progress text.

    def _finish_busy_common(self) -> str | None:
        kind = self.current_job_kind
        self.current_job_id = None
        self.current_job_kind = None
        self.busy_state = "idle"
        if kind == "batch":
            self._batch_progress_index = None
            self._batch_progress_total = None
            self._batch_progress_source_name = None
        self._refresh_control_states()
        self._stop_activity()
        return kind

    def _finish_worker_success(self, payload: Any) -> None:
        kind = self._finish_busy_common()
        if kind == "load" and isinstance(payload, BrowsedSource):
            self._load_rollback_context = None
            self.current = payload
            self._state_dirty = False
            self._state_dirty_can_create_sidecar = False
            self._sync_vars_from_current()
            self._refresh_preview()
            self._render_status()
            self._refresh_control_states()
            return

        if kind == "analysis" and isinstance(payload, ProcessedSource):
            if payload.loaded_pair is None:
                messagebox.showerror(APP_NAME, self._t("internal_preview_error"))
                return
            sidecar = load_sidecar(payload.source.sidecar_path, expected_source=payload.source_stamp)
            self.current = BrowsedSource(
                payload.source,
                payload.loaded_pair,
                payload.source_stamp,
                payload.state,
                sidecar,
            )
            self._sync_vars_from_current()
            self._refresh_preview()
            self._render_status()
            play_ready_sound(asset_path("ready.wav"))
            return

        if kind in {"batch", "save"} and isinstance(payload, BatchRunResult):
            if payload.failed:
                details = "\n".join(f"{source.display_name}: {self.tr.message(message)}" for source, message in payload.failed[:15])
                messagebox.showwarning(
                    APP_NAME, self._t("processing_failed_count", count=len(payload.failed), details=details)
                )
            else:
                # Image processing itself completed successfully. Metadata-copy
                # warnings remain nonfatal but must be visible to the user.  A
                # native Windows info box has its own system chime, so ordinary
                # success uses only assets/ready.wav plus lightweight button
                # feedback. This avoids the former double completion sound.
                if kind == "save":
                    text = self._t("saved")
                elif self.analysis_only.get():
                    images = self.tr.image_count(len(payload.items))
                    if payload.report_path:
                        text = self._t("analysis_complete", images=images, report=payload.report_path)
                    else:
                        text = f"{self._t('report_title')}: {images}"
                elif self.favorites_only.get():
                    images = self.tr.image_count(payload.exported_count)
                    text = self._t("favorites_complete", images=images)
                    if payload.skipped_export_count:
                        skipped = self.tr.nonfavorite_count(payload.skipped_export_count)
                        text += f"\n\n{self._t('nonfavorites_skipped', images=skipped)}"
                else:
                    images = self.tr.image_count(payload.exported_count)
                    text = self._t("batch_complete", images=images)

                if payload.warnings:
                    details = "\n".join(
                        f"{source.display_name}: {self.tr.message(message)}"
                        for source, message in payload.warnings[:15]
                    )
                    text += f"\n\n{self._t('metadata_warnings', details=details)}"
                    # The warning dialog already provides the Windows alert; do
                    # not layer ready.wav on top of it.
                    messagebox.showwarning(APP_NAME, text)
                else:
                    play_ready_sound(asset_path("ready.wav"))
                    if kind == "save":
                        self.save_button.configure(text=self._t("saved").rstrip("."))
                        self.after(1200, lambda: self.save_button.configure(text=self._t("save")))
                    else:
                        # Batch/analysis completion is intentionally non-modal.
                        # The ready sound plus a short primary-button message is
                        # enough feedback and does not add a Windows system chime.
                        self.start_button.configure(text=self._t("completed_short"))
                        self.after(1400, self._update_start_button_text)
            # Reload the visible item so status and any fitted color parameters
            # exactly match what the batch persisted.
            if self.source_index is not None and self.sources:
                self._load_source_index(self.source_index)

    def _finish_worker_cancelled(self) -> None:
        kind = self._finish_busy_common()
        if kind == "load":
            self._restore_load_rollback()
        elif kind == "batch" and self.current is not None:
            # Batch progress temporarily owns the preview. Restore the browsed
            # image after cancellation so no stale progress frame remains.
            self._refresh_preview()
            self._render_status()
        messagebox.showinfo(APP_NAME, self._t("processing_cancelled"))

    def _finish_worker_error(self, payload: Any) -> None:
        kind = self._finish_busy_common()
        if kind == "load":
            self._restore_load_rollback()
        elif kind == "batch" and self.current is not None:
            self._refresh_preview()
            self._render_status()
        if isinstance(payload, dict):
            exc = payload.get("exception")
            text = self.tr.message(str(exc or self._t("unknown_error")))
        else:
            text = self.tr.message(str(payload))
        messagebox.showerror(APP_NAME, self._t("processing_failed", text=text))

    # ------------------------------------------------------------------
    # Keyboard handling
    # ------------------------------------------------------------------
    def _bind_shortcuts(self) -> None:
        self.bind_all("<F11>", self._on_f11)
        self.bind_all("<KeyRelease-F11>", lambda e: self._release_shortcut_key("f11"))
        self.bind("<Escape>", self._on_escape)
        self.bind("<Prior>", self.previous_source)
        self.bind("<Next>", self.next_source)
        self.bind_all("<space>", self.start_processing)
        self.bind_all("<Return>", self.save_current_result)
        self.bind_all("<KP_Enter>", self.save_current_result)
        self.bind_all("<Control-r>", self._on_ctrl_r)
        self.bind_all("<Control-R>", self._on_ctrl_r)
        self.bind_all("<a>", self._on_a)
        self.bind_all("<A>", self._on_a)
        self.bind_all("<KeyRelease-a>", lambda e: self._release_shortcut_key("a"))
        self.bind_all("<KeyRelease-A>", lambda e: self._release_shortcut_key("a"))
        self.bind_all("<g>", self._on_g)
        self.bind_all("<G>", self._on_g)
        self.bind_all("<KeyRelease-g>", self._on_g_release)
        self.bind_all("<KeyRelease-G>", self._on_g_release)
        self.bind_all("<s>", self._on_s)
        self.bind_all("<S>", self._on_s)
        self.bind_all("<KeyRelease-s>", lambda e: self._release_shortcut_key("s"))
        self.bind_all("<KeyRelease-S>", lambda e: self._release_shortcut_key("s"))
        self.bind_all("<F1>", self._on_f1)
        self.bind_all("<KeyRelease-F1>", lambda e: self._release_shortcut_key("f1"))

        self.bind_all("<KeyPress-m>", self._on_measure_press)
        self.bind_all("<KeyPress-M>", self._on_measure_press)
        self.bind_all("<KeyRelease-m>", self._on_measure_release)
        self.bind_all("<KeyRelease-M>", self._on_measure_release)
        for key in ("Left", "Right", "Up", "Down"):
            self.bind_all(f"<KeyRelease-{key}>", self._on_arrow_release)

        self.bind_all("<Left>", lambda e: self._on_arrow("left", e))
        self.bind_all("<Right>", lambda e: self._on_arrow("right", e))
        self.bind_all("<Up>", lambda e: self._on_arrow("up", e))
        self.bind_all("<Down>", lambda e: self._on_arrow("down", e))
        self.bind_all("<Alt-Left>", lambda e: self._on_alt_arrow("left", e))
        self.bind_all("<Alt-Right>", lambda e: self._on_alt_arrow("right", e))
        self.bind_all("<Alt-Up>", lambda e: self._on_alt_arrow("up", e))
        self.bind_all("<Alt-Down>", lambda e: self._on_alt_arrow("down", e))

        for edge, key in (("left", "l"), ("right", "r"), ("top", "t"), ("bottom", "b")):
            self.bind_all(f"<KeyPress-{key}>", lambda e, edge=edge: self._set_floating_key(edge, e))
            self.bind_all(f"<KeyPress-{key.upper()}>", lambda e, edge=edge: self._set_floating_key(edge, e))
            self.bind_all(f"<KeyRelease-{key}>", lambda e, edge=edge: self._clear_floating_key(edge, e))
            self.bind_all(f"<KeyRelease-{key.upper()}>", lambda e, edge=edge: self._clear_floating_key(edge, e))

    def _is_alt(self, event) -> bool:
        return bool(event is not None and event.state & (0x0008 | 0x0080 | 0x20000))

    def _is_ctrl(self, event) -> bool:
        return bool(event is not None and event.state & 0x0004)

    def _is_shift(self, event) -> bool:
        return bool(event is not None and event.state & 0x0001)

    def _is_ctrl_shift(self, event) -> bool:
        return self._is_ctrl(event) and self._is_shift(event)

    def _keyboard_step(self, event) -> int:
        if self._is_ctrl(event):
            return 10
        if self._is_shift(event):
            return 5
        return 1

    def _on_arrow(self, direction: str, event=None):
        if self._handle_measure_arrow(direction):
            return "break"
        if self._floating_key_edge is not None:
            if direction in {"left", "right"}:
                self._adjust_floating_edge(self._floating_key_edge, 1 if direction == "right" else -1)
            return "break"
        if self._is_ctrl_shift(event):
            if direction == "up":
                self._adjust_crop_zoom(1)
            elif direction == "down":
                self._adjust_crop_zoom(-1)
            return "break"
        if self._is_alt(event):
            return self._on_alt_arrow(direction, event)
        step = self._keyboard_step(event)
        if direction == "left":
            self._adjust_manual_offset(-step, 0)
        elif direction == "right":
            self._adjust_manual_offset(step, 0)
        elif direction == "up":
            self._adjust_manual_offset(0, -step)
        elif direction == "down":
            self._adjust_manual_offset(0, step)
        return "break"

    def _on_alt_arrow(self, direction: str, _event=None):
        if self.current is None or self.busy_state != "idle":
            return "break"
        if direction == "left":
            self._adjust_framing_pan(-self._framing_step_permille("x"), 0)
        elif direction == "right":
            self._adjust_framing_pan(self._framing_step_permille("x"), 0)
        elif direction == "up":
            self._adjust_framing_pan(0, -self._framing_step_permille("y"))
        elif direction == "down":
            self._adjust_framing_pan(0, self._framing_step_permille("y"))
        return "break"

    def _on_ctrl_r(self, event=None):
        if self.busy_state != "idle" or not self._claim_shortcut_key("ctrl-r", event):
            return "break"
        self.reset_manual_to_auto()
        return "break"

    def _claim_shortcut_key(self, key: str, event=None) -> bool:
        """Accept one physical press and ignore operating-system key repeat."""
        if event is None:
            return True
        if key in self._shortcut_keys_down:
            return False
        self._shortcut_keys_down.add(key)
        return True

    def _release_shortcut_key(self, key: str):
        self._shortcut_keys_down.discard(key)
        return "break"

    def _on_a(self, event=None):
        if self.busy_state != "idle" or not self._claim_shortcut_key("a", event):
            return "break"
        self.preview_mode.set("Graustufen" if self.preview_mode.get() == "Farbig" else "Farbig")
        self._on_preview_mode_changed()
        return "break"

    def _on_g(self, event=None):
        if self._g_key_down:
            return "break"
        self._g_key_down = True
        if self._is_shift(event):
            self.grid_mode.set("Aus")
            self._update_grid_control_state()
            self._update_preview_display()
            return "break"
        cycle = [
            ("Weiß", "25 Promille"), ("Weiß", "50 Promille"), ("Weiß", "100 Promille"), ("Weiß", "Drittel-Raster"),
            ("Schwarz", "25 Promille"), ("Schwarz", "50 Promille"), ("Schwarz", "100 Promille"), ("Schwarz", "Drittel-Raster"),
        ]
        current = (self.grid_mode.get(), self.grid_spacing.get())
        if self.grid_mode.get() == "Aus":
            next_value = cycle[0]
        else:
            try:
                idx = cycle.index(current)
                next_value = ("Aus", self.grid_spacing.get()) if idx == len(cycle) - 1 else cycle[idx + 1]
            except ValueError:
                next_value = cycle[0]
        self.grid_mode.set(next_value[0])
        self.grid_spacing.set(next_value[1])
        self.grid_spacing_display.set(grid_spacing_label(self.grid_spacing.get(), self.settings.language))
        self._update_grid_control_state()
        self._update_preview_display()
        return "break"

    def _on_g_release(self, _event=None):
        self._g_key_down = False
        return "break"

    def _on_s(self, event=None):
        if (
            self.current is None
            or self.busy_state != "idle"
            or not self._claim_shortcut_key("s", event)
        ):
            return "break"
        # S is deliberately only a coupling mode. It never creates, removes or
        # changes an existing floating-window mask value.
        self.float_lr_symmetric.set(not self.float_lr_symmetric.get())
        return "break"

    def _set_floating_key(self, edge: str, event=None):
        if self._is_ctrl(event):
            if edge == "right":
                return self._on_ctrl_r(event)
            return "break"
        if self.busy_state == "idle" and self.current is not None:
            self._floating_key_edge = edge
        return "break"

    def _clear_floating_key(self, edge: str, _event=None):
        if self._floating_key_edge == edge:
            self._floating_key_edge = None
        if edge == "right":
            # R also carries Ctrl+R. The shared release event clears that
            # repeat guard so a later physical Ctrl+R press is accepted.
            self._shortcut_keys_down.discard("ctrl-r")
        return "break"

    # ------------------------------------------------------------------
    # Measurement cross
    # ------------------------------------------------------------------
    def _measure_can_run(self) -> bool:
        return self._preview_pil is not None and self.busy_state == "idle"

    def _clamp_measure_cross(self, size: tuple[int, int] | None = None) -> None:
        if size is None:
            size = self._preview_display_size
            if size is None:
                if self._preview_pil is None:
                    return
                size = self._preview_pil.size
        width, height = size
        if self.measure_cross_x is None or self.measure_cross_y is None:
            self.measure_cross_x = float(round((width - 1) / 2))
            self.measure_cross_y = float(round((height - 1) / 2))
        self.measure_cross_x = max(0.0, min(float(width - 1), float(self.measure_cross_x)))
        self.measure_cross_y = max(0.0, min(float(height - 1), float(self.measure_cross_y)))

    def _on_measure_press(self, _event=None):
        if not self._measure_can_run():
            return "break"
        if not self.measure_cross_active:
            self.measure_cross_active = True
            self._clamp_measure_cross(self._preview_display_size)
            self._update_preview_display()
        return "break"

    def _on_measure_release(self, _event=None):
        if self.measure_cross_active:
            self.measure_cross_active = False
            self._stop_measure_repeat()
            self._update_preview_display()
        return "break"

    def _on_arrow_release(self, _event=None):
        if self.measure_cross_active or self._measure_repeat_job is not None:
            self._stop_measure_repeat()
            return "break"
        if self._status_after_id:
            self._render_status()
        return None

    def _stop_measure_repeat(self) -> None:
        self._measure_repeat_direction = None
        self._measure_hold_started_at = None
        self._measure_last_tick_at = None
        if self._measure_repeat_job:
            try:
                self.after_cancel(self._measure_repeat_job)
            except Exception:
                pass
        self._measure_repeat_job = None

    def _move_measure_cross(self, direction: str, pixels: float) -> None:
        if not self.measure_cross_active:
            return
        self._clamp_measure_cross()
        if direction == "left":
            self.measure_cross_x = float(self.measure_cross_x or 0) - pixels
        elif direction == "right":
            self.measure_cross_x = float(self.measure_cross_x or 0) + pixels
        elif direction == "up":
            self.measure_cross_y = float(self.measure_cross_y or 0) - pixels
        elif direction == "down":
            self.measure_cross_y = float(self.measure_cross_y or 0) + pixels
        self._clamp_measure_cross(self._preview_display_size)
        self._update_preview_display()

    def _measure_speed(self, held_seconds: float) -> float:
        t = max(0.0, min(1.0, held_seconds / MEASURE_ACCEL_TIME_SEC))
        t = t * t * (3.0 - 2.0 * t)
        return MEASURE_START_SPEED_PX_PER_SEC + (MEASURE_MAX_SPEED_PX_PER_SEC - MEASURE_START_SPEED_PX_PER_SEC) * t

    def _measure_repeat_tick(self) -> None:
        self._measure_repeat_job = None
        direction = self._measure_repeat_direction
        if not self.measure_cross_active or direction is None:
            return
        now = time.perf_counter()
        if self._measure_hold_started_at is None:
            self._measure_hold_started_at = now
        if self._measure_last_tick_at is None:
            self._measure_last_tick_at = now
        held = max(0.0, now - self._measure_hold_started_at)
        delay = MEASURE_HOLD_DELAY_MS / 1000.0
        if held < delay:
            self._measure_last_tick_at = now
            self._measure_repeat_job = self.after(MEASURE_REPEAT_MS, self._measure_repeat_tick)
            return
        dt = max(0.001, min(MEASURE_MAX_DT_SEC, now - self._measure_last_tick_at))
        self._measure_last_tick_at = now
        pixels = self._measure_speed(max(0.0, held - delay)) * dt
        self._move_measure_cross(direction, pixels)
        self._measure_repeat_job = self.after(MEASURE_REPEAT_MS, self._measure_repeat_tick)

    def _handle_measure_arrow(self, direction: str) -> bool:
        if not self.measure_cross_active:
            return False
        if self._measure_repeat_direction != direction:
            self._stop_measure_repeat()
            now = time.perf_counter()
            self._measure_repeat_direction = direction
            self._measure_hold_started_at = now
            self._measure_last_tick_at = now
            self._move_measure_cross(direction, 1.0)
            self._measure_repeat_job = self.after(MEASURE_REPEAT_MS, self._measure_repeat_tick)
        return True

    # ------------------------------------------------------------------
    # Fullscreen / help / close
    # ------------------------------------------------------------------
    def _on_f11(self, event=None):
        if not self._claim_shortcut_key("f11", event):
            return "break"
        return self.toggle_fullscreen(event)

    def toggle_fullscreen(self, _event=None):
        self.fullscreen = not self.fullscreen
        self.attributes("-fullscreen", self.fullscreen)
        if hasattr(self, "fullscreen_button"):
            self.fullscreen_button.configure(text=self._t("windowed") if self.fullscreen else self._t("fullscreen"))
        return "break"

    def _on_escape(self, _event=None):
        if self._shortcut_help_window is not None and self._shortcut_help_window.winfo_exists():
            self._close_shortcuts_help()
            return "break"
        if self.fullscreen:
            self.fullscreen = False
            self.attributes("-fullscreen", False)
            if hasattr(self, "fullscreen_button"):
                self.fullscreen_button.configure(text=self._t("fullscreen"))
        return "break"

    def _on_f1(self, event=None):
        if self.busy_state != "idle" or not self._claim_shortcut_key("f1", event):
            return "break"
        if self._shortcut_help_window is not None and self._shortcut_help_window.winfo_exists():
            self._close_shortcuts_help()
            return "break"
        return self.show_shortcuts_help(event)

    def show_shortcuts_help(self, _event=None):
        if self.busy_state != "idle":
            return "break"
        if self._shortcut_help_window is not None and self._shortcut_help_window.winfo_exists():
            self._shortcut_help_window.lift()
            self._shortcut_help_window.focus()
            return "break"

        window = ctk.CTkToplevel(self)
        self._shortcut_help_window = window
        window.title(self._t("help_title"))
        screen_w = max(1, window.winfo_screenwidth())
        screen_h = max(1, window.winfo_screenheight())
        help_w = min(960, max(760, screen_w - 120))
        help_h = min(640, max(560, screen_h - 100))
        window.geometry(f"{help_w}x{help_h}")
        window.minsize(min(820, help_w), min(560, help_h))
        window.resizable(True, True)
        window.configure(fg_color=APP_BG)
        window.transient(self)
        window.protocol("WM_DELETE_WINDOW", self._close_shortcuts_help)
        window.bind("<Escape>", lambda _e: self._close_shortcuts_help())
        # F1 is handled once via the application-wide repeat-safe binding.

        frame = ctk.CTkFrame(window, fg_color=PANEL_BG, corner_radius=PANEL_RADIUS)
        frame.pack(fill="both", expand=True, padx=18, pady=18)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            frame,
            text=self._t("help_heading"),
            text_color=GOLD_LIGHT,
            font=self._font(22, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 9))

        content = ctk.CTkFrame(frame, fg_color="transparent")
        content.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 16))
        content.grid_columnconfigure((0, 1), weight=1, uniform="help")
        content.grid_rowconfigure(0, weight=1)

        blocks = [block for block in self._t("help_text").split("\n\n") if block.strip()]
        columns = (blocks[:3], blocks[3:])

        def build_table(parent, column: int, table_blocks: list[str]) -> None:
            table = ctk.CTkFrame(parent, fg_color=SECONDARY_BG, corner_radius=CONTROL_RADIUS)
            table.grid(
                row=0,
                column=column,
                sticky="nsew",
                padx=(0, 5) if column == 0 else (5, 0),
            )
            table.grid_columnconfigure(0, minsize=148, weight=0)
            table.grid_columnconfigure(1, weight=1)

            ctk.CTkLabel(
                table,
                text=self._t("help_key_column"),
                text_color=TEXT_SECONDARY,
                font=self._font(11, "bold"),
                anchor="e",
            ).grid(row=0, column=0, sticky="ew", padx=(10, 9), pady=(8, 5))
            ctk.CTkLabel(
                table,
                text=self._t("help_action_column"),
                text_color=TEXT_SECONDARY,
                font=self._font(11, "bold"),
                anchor="w",
            ).grid(row=0, column=1, sticky="ew", padx=(9, 10), pady=(8, 5))

            grid_row = 1
            for block_index, block in enumerate(table_blocks):
                lines = [line.rstrip() for line in block.splitlines() if line.strip()]
                if not lines:
                    continue
                if block_index:
                    ctk.CTkFrame(table, height=1, fg_color=BORDER, corner_radius=0).grid(
                        row=grid_row, column=0, columnspan=2, sticky="ew", padx=10, pady=(4, 4)
                    )
                    grid_row += 1

                ctk.CTkLabel(
                    table,
                    text=lines[0].strip(),
                    text_color=TEXT_PRIMARY,
                    font=self._font(12, "bold"),
                    anchor="w",
                ).grid(row=grid_row, column=0, columnspan=2, sticky="ew", padx=10, pady=(1, 3))
                grid_row += 1

                for line in lines[1:]:
                    match = re.match(r"^\s*(.*?)\s{2,}(.*?)\s*$", line)
                    if match:
                        key_text, action_text = match.groups()
                    else:
                        key_text, action_text = line.strip(), ""
                    ctk.CTkLabel(
                        table,
                        text=key_text,
                        text_color=GOLD_LIGHT,
                        font=self._font(11, "bold"),
                        anchor="e",
                    ).grid(row=grid_row, column=0, sticky="ew", padx=(10, 9), pady=1)
                    ctk.CTkLabel(
                        table,
                        text=action_text,
                        text_color=TEXT_PRIMARY,
                        font=self._font(11),
                        anchor="w",
                    ).grid(row=grid_row, column=1, sticky="ew", padx=(9, 10), pady=1)
                    grid_row += 1

        build_table(content, 0, list(columns[0]))
        build_table(content, 1, list(columns[1]))
        return "break"

    def _close_shortcuts_help(self) -> None:
        if self._shortcut_help_window is not None:
            try:
                self._shortcut_help_window.destroy()
            except Exception:
                pass
        self._shortcut_help_window = None

    def _center_window(self) -> None:
        self.update_idletasks()
        screen_w = max(1, self.winfo_screenwidth())
        screen_h = max(1, self.winfo_screenheight())
        # Keep the established 1400x850 workspace where it fits, but never
        # center a larger window partly off-screen on smaller displays.
        width = min(WINDOW_WIDTH, max(1100, screen_w - 40))
        height = min(WINDOW_HEIGHT, max(700, screen_h - 80))
        width = min(width, screen_w)
        height = min(height, screen_h)
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _on_close(self) -> None:
        if self.busy_state != "idle":
            if not messagebox.askyesno(APP_NAME, self._t("close_busy")):
                return
            self.worker.cancel_all()
        self._flush_state_save()
        self._persist_settings()
        self.destroy()


def run() -> None:
    app = StereoFineApp()
    app.mainloop()
