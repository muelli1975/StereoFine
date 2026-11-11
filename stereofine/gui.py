from __future__ import annotations

import math
import queue
from concurrent.futures import Future, ThreadPoolExecutor, wait
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
import re
import sys
import time
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any

import customtkinter as ctk
import numpy as np
from PIL import Image, ImageDraw, ImageTk

from .batch import BatchRunOptions, BatchRunResult, batch_worker_count, run_batch
from .config import (
    APP_NAME,
    APP_VERSION,
    ASPECT_RATIOS,
    CROP_ZOOM_LEVELS,
    GRID_SPACING_OPTIONS,
    SUPPORTED_IMAGE_EXTENSIONS,
    SUPPORTED_STEREO_SINGLE_EXTENSIONS,
)
from .diagnostics import configure_logging, log_failure
from .geometry import crop_shifted_pair_to_overlap, framing_crop_geometry, clamp_offset_for_size
from .geometry_controls import GeometryControlsMixin
from .manual_geometry import GeometryAdjustment
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
from .look_controls import LookControlsMixin
from .looks import look_signature
from .view_controls import ViewControlsMixin
from .output_naming import suffix_label, suffix_labels, suffix_value, validate_sbs_suffix
from .native_preview import (NativePreviewMixin, mask_preview_pair, native_key, prepare_native_preview,
    preview_image, pan_speed, MEASURE_REPEAT_MS,
    MEASURE_HOLD_DELAY_MS, MEASURE_START_SPEED_PX_PER_SEC, MEASURE_MAX_SPEED_PX_PER_SEC,
    MEASURE_ACCEL_TIME_SEC, MEASURE_MAX_DT_SEC)
from .tooltip import attach_tooltip
from .preview import PreviewImageCache, draw_grid_overlay, draw_measure_cross_overlay
from .preview_render import PreviewBasePair, build_preview_base, render_preview_from_base, preview_geometry_key
from .preferences import save_series_input
from .processing import ProcessingDefaults, ProcessingOptions, process_source
from .inputs import LoadedStereoPair, load_full_sbs
from .resources import asset_path, start_image_bytes
from .session import (
    DECODED_CACHE_LIMIT,
    BrowsedSource,
    browse_file_signature,
    browse_source,
    preload_browsable_source,
    is_saved_favorite,
    save_browsed_state,
    source_from_selected_pair_image,
    source_from_selected_stereo_file,
)
from .settings import AppSettings, load_settings, save_settings
from .sidecar import SidecarStatus, load_sidecar
from .sources import StereoSource, discover_pair_sources, discover_stereo_file_sources
from .state import InputTransformState, LookState, PairState
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
from .worker import CancellationToken, WorkerManager, WorkerMessageKind

WINDOW_WIDTH = 1400
WINDOW_HEIGHT = 850
SIDEBAR_WIDTH = 340
STATUS_SYMBOL_COLUMN_WIDTH = 36
STATUS_ROW_HEIGHT = 19
STATUS_WARNING_HEIGHT = 36
ACTIVITY_SPINNER_SIZE = 36
ACTIVITY_SPINNER_RENDER_SCALE = 5
ACTIVITY_SPINNER_FRAME_COUNT = 60
ACTIVITY_FRAME_MS = 16
ACTIVITY_SPINNER_PERIOD_SEC = 1.0
ACTIVITY_MIN_VISIBLE_MS = 200
BROWSE_ACTIVITY_DELAY_MS = 140
ACTIVITY_SPINNER_TRACK = (74, 62, 38)
ACTIVITY_SPINNER_ARC = (198, 169, 94)
ACTIVITY_SPINNER_BG = (24, 24, 24)


@dataclass(frozen=True)
class FittedBrowseFrame:
    left: np.ndarray
    right: np.ndarray
    image: Image.Image
    mode: str


@dataclass(frozen=True)
class PreparedSessionPreview:
    session: BrowsedSource
    native_result: tuple
    fitted_frame: FittedBrowseFrame | None = None


@dataclass(frozen=True)
class PreviewPrefetch:
    source: StereoSource
    defaults: ProcessingDefaults
    bounds: tuple[int, int]
    mode: str
    token: CancellationToken
    future: Future


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

class StereoFineApp(GeometryControlsMixin, LookControlsMixin, ViewControlsMixin, NativePreviewMixin, ctk.CTk):
    """GUI shell over the GUI-independent processing core."""

    _show_calculation_status = False

    def __init__(self) -> None:
        ctk.set_appearance_mode("dark")
        # No CustomTkinter color theme is used as a design source. Every visible
        # color below is explicitly defined by the shared Stereo-Tool standard.
        super().__init__()
        configure_logging()

        self.settings: AppSettings = load_settings()
        self.tr = Translator(self.settings.language)
        self._init_native_preview()
        self.worker = WorkerManager()
        self.measurement_worker = WorkerManager()
        self._measurement_after_id = None
        self._measurement_job_id = None
        self._measurement_running_id = None
        self._measurement_session = None
        self._measurement_basis = None
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
        self._favorite_indices: set[int] | None = None
        self.batch_mode = False
        # Transient batch-preview identity.  The browsed source/index remains
        # untouched during a worker run so navigation can be restored cleanly;
        # these fields describe the lightweight image that is actually shown.
        self._batch_progress_index: int | None = None
        self._batch_progress_total: int | None = None
        self._batch_progress_source_name: str | None = None
        self._batch_progress_state = None
        self._load_rollback_context: tuple[list[StereoSource], int | None, bool, str, set[int] | None] | None = None
        self._save_after_id: str | None = None
        self._state_save_error = None
        self._state_dirty = False
        self._state_dirty_can_create_sidecar = False
        self._resize_after_id: str | None = None
        self._resize_fast_after_id: str | None = None
        self._status_after_id: str | None = None

        self.preview_mode = ctk.StringVar(value="Farbig")
        self._last_anaglyph_preview_mode = "Farbig"
        self.gray_anaglyph = ctk.BooleanVar(value=self.settings.gray_anaglyph)
        self.save_cross = ctk.BooleanVar(value=self.settings.save_cross)
        self.tiff_sbs = ctk.BooleanVar(value=self.settings.tiff_sbs)
        self.save_anaglyph = ctk.BooleanVar(value=self.settings.save_anaglyph)
        self.use_custom_sbs_suffix = ctk.BooleanVar(value=self.settings.use_custom_sbs_suffix)
        self.sbs_suffix_display = ctk.StringVar(value=suffix_label(self.settings.sbs_suffix, self.settings.language))
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
        self.append_deviation_to_filename = ctk.BooleanVar(value=self.settings.append_deviation_to_filename)
        # Batch special modes are session/job state, not persistent preferences.
        self.analysis_only = ctk.BooleanVar(value=False)
        self.favorites_only = ctk.BooleanVar(value=False)
        self.float_lr_symmetric = ctk.BooleanVar(value=False)
        self._init_look_controls()
        self._prefetch_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='StereoFine-preload')
        self._prefetched = []
        self._previous_decoded = None
        self._previous_views = None
        self._browse_step = 1
        self._init_view_controls()

        self.measure_cross_active = False
        self.measure_cross_x: float | None = None
        self.measure_cross_y: float | None = None
        self._measure_repeat_job: str | None = None
        self._measure_repeat_direction: str | None = None
        self._measure_hold_started_at: float | None = None
        self._measure_last_tick_at: float | None = None
        self._floating_key_edge: str | None = None
        self._g_key_down = False
        self._look_key_used = False
        self._shortcut_keys_down: set[str] = set()
        self._keyboard_focus_after_id: str | None = None
        self._shortcut_help_window: ctk.CTkToplevel | None = None
        self._preview_pil: Image.Image | None = None
        self._preview_display_cache = PreviewImageCache()
        self._preview_ctk_image: ctk.CTkImage | None = None
        self._preview_pair_shape: tuple[int, int] | None = None
        self._preview_display_size: tuple[int, int] | None = None
        self._measure_display_size: tuple[int, int] | None = None
        self._preview_base: PreviewBasePair | None = None
        self._preview_base_session_id: int | None = None
        self._preview_left_current = None
        self._preview_right_current = None
        self.fullscreen = False
        self._titlebar_restore_job: str | None = None

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
        self._cancel_look_hover(refresh=False)
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
        self._build_layout()
        self._refresh_output_state()
        self._render_status()
        self._refresh_control_states()
        self._refresh_preview()

    def _on_language_changed(self, label: str) -> None:
        code = language_code(label)
        if code == self.settings.language:
            return
        if not self._commit_sbs_suffix(show_error=True):
            self.language_display.set(language_label(self.settings.language))
            return
        self.settings.language = code
        self.sbs_suffix_display.set(suffix_label(self.settings.sbs_suffix, code))
        save_settings(self.settings)
        self._rebuild_for_language()

    def _image_filetypes(self) -> list[tuple[str, str]]:
        patterns = " ".join(f"*{ext}" for ext in sorted(SUPPORTED_IMAGE_EXTENSIONS))
        if self.settings.language == "en":
            return [("Image files", patterns), ("All files", "*.*")]
        return [("Bilddateien", patterns), ("Alle Dateien", "*.*")]

    def _stereo_filetypes(self) -> list[tuple[str, str]]:
        patterns = " ".join(f"*{ext}" for ext in sorted(SUPPORTED_STEREO_SINGLE_EXTENSIONS))
        if self.settings.language == "en":
            return [("Stereo files", patterns), ("All files", "*.*")]
        return [("Stereodateien", patterns), ("Alle Dateien", "*.*")]

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
            command=self._image_control_command(command),
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
            command=self._image_control_command(command),
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
            command=self._image_control_command(command),
            fg_color=GOLD_DARK,
            hover_color=GOLD_LIGHT,
            border_color=BORDER,
            checkmark_color=TEXT_PRIMARY,
            text_color=TEXT_PRIMARY,
            text_color_disabled=TEXT_DISABLED,
            corner_radius=4,
            font=self._font(13),
        )
        self._lock_widgets.append(box)
        self._checkbox_widgets.append(box)
        return box

    def _option_menu(self, parent, *, values: list[str], variable, command=None,
                     menu_class=None, **options):
        menu = (menu_class or ctk.CTkOptionMenu)(
            parent,
            values=values,
            variable=variable,
            command=self._image_control_command(command),
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
            **options,
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
        self._bind_view_controls()

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
        self.save_series_input_button = self._secondary_button(
            self.sidebar, self._t('save_series_input'), self._save_series_input)
        self.save_series_input_button.grid(row=row, column=0, sticky='ew', padx=20, pady=(0, 8)); row += 1
        attach_tooltip(self.save_series_input_button, self._t('series_input_tooltip'))

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
        row = self._build_exposure_controls(self.sidebar, row)
        row = self._build_look_controls(self.sidebar, row)

        self.tiff_sbs_box = self._checkbox(
            self.sidebar, self._t("tiff_sbs"), self.tiff_sbs, self._persist_settings,
        )
        self.tiff_sbs_box.grid(row=row, column=0, sticky="w", padx=20, pady=(0, 8)); row += 1
        attach_tooltip(self.tiff_sbs_box, self._t("tiff_tooltip"))

        self.deviation_filename_box = self._checkbox(
            self.sidebar, self._t("deviation_filename"),
            self.append_deviation_to_filename, self._persist_settings,
        )
        self.deviation_filename_box.grid(row=row, column=0, sticky="w", padx=20, pady=(0, 8)); row += 1

        self.custom_sbs_suffix_box = self._checkbox(
            self.sidebar, self._t("custom_sbs_suffix"), self.use_custom_sbs_suffix, self._on_export_options_changed,
        )
        self.custom_sbs_suffix_box.grid(row=row, column=0, sticky="w", padx=20, pady=(0, 4)); row += 1
        self.sbs_suffix_menu = ctk.CTkComboBox(
            self.sidebar, variable=self.sbs_suffix_display,
            values=suffix_labels(self.settings.language), command=self._on_sbs_suffix_selected,
            fg_color=SECONDARY_BG, border_color=BORDER,
            button_color=HOVER_BG, button_hover_color=BORDER,
            dropdown_fg_color=SECONDARY_BG, dropdown_hover_color=HOVER_BG,
            text_color=TEXT_PRIMARY, text_color_disabled=TEXT_DISABLED, dropdown_text_color=TEXT_PRIMARY,
            corner_radius=CONTROL_RADIUS, font=self._font(13), dropdown_font=self._font(13),
        )
        self.sbs_suffix_menu.grid(row=row, column=0, sticky="ew", padx=(42, 20), pady=(0, 8)); row += 1
        self._lock_widgets.append(self.sbs_suffix_menu)
        self.sbs_suffix_menu.bind("<KeyRelease>", self._on_sbs_suffix_edited, add="+")
        self.sbs_suffix_menu.bind("<FocusOut>", self._on_sbs_suffix_edited, add="+")
        self.sbs_suffix_menu.bind("<FocusIn>", lambda _e: self._reset_keyboard_modes(), add="+")
        self.sbs_suffix_menu.bind("<Return>", self._on_sbs_suffix_return, add="+")
        self.sbs_suffix_menu.bind("<KP_Enter>", self._on_sbs_suffix_return, add="+")
        self.sbs_suffix_menu.bind("<Escape>", self._on_sbs_suffix_escape, add="+")
        for sequence in ("<Tab>", "<Shift-Tab>", "<ISO_Left_Tab>"):
            self.sbs_suffix_menu.bind(sequence, self._on_sbs_suffix_return, add="+")

        self.save_anaglyph_box = self._checkbox(
            self.sidebar, self._t("save_anaglyph"), self.save_anaglyph, self._on_export_options_changed,
        )
        self.save_anaglyph_box.grid(row=row, column=0, sticky="w", padx=20, pady=(0, 8)); row += 1
        self.gray_anaglyph_box = self._checkbox(
            self.sidebar, self._t("gray_anaglyph"), self.gray_anaglyph, self._persist_settings,
        )
        self.gray_anaglyph_box.grid(row=row, column=0, sticky="w", padx=(42, 20), pady=(0, 8)); row += 1
        self.save_cross_box = self._checkbox(
            self.sidebar, self._t("save_cross"), self.save_cross, self._persist_settings,
        )
        self.save_cross_box.grid(row=row, column=0, sticky="w", padx=20, pady=(0, 8)); row += 1

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
        preview_modes.grid_columnconfigure((0, 1, 2), weight=1)
        for col, (text, value) in enumerate(((self._t("preview_color"), "Farbig"), (self._t("preview_gray"), "Graustufen"), (self._t("preview_cross"), "Kreuzblick"))):
            radio = ctk.CTkRadioButton(
                preview_modes,
                text=text,
                variable=self.preview_mode,
                width=1,
                value=value,
                command=self._image_control_command(self._on_preview_mode_changed),
                fg_color=GOLD_DARK,
                hover_color=GOLD_LIGHT,
                border_color=BORDER,
                text_color=TEXT_PRIMARY,
                font=self._font(13),
            )
            radio.grid(row=0, column=col, sticky="w", padx=(0 if col == 0 else 4, 4))
            self._lock_widgets.append(radio)
            self._radio_widgets.append(radio)

        self.deviation_points_box = self._checkbox(self.sidebar, self._t('show_deviation_points'),
            self.show_deviation_points, self._on_deviation_option_changed)
        self.deviation_points_box.grid(row=row,column=0,sticky='w',padx=20,pady=(0,8)); row += 1

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
                command=self._image_control_command(self._on_grid_mode_changed),
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
        self.defaults_button = self._secondary_button(self.sidebar, self._t('program_defaults'),
                                                       self.restore_program_defaults)
        self.defaults_button.grid(row=row,column=0,sticky='ew',padx=20,pady=(0,16))

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
            width=16,
            height=STATUS_ROW_HEIGHT,
            text_color=TRAFFIC_GRAY,
            font=self._font(20),
            anchor="center",
        )
        self.traffic_label.grid_propagate(False)
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

        help_footer = ctk.CTkFrame(self.sidebar_bottom, fg_color="transparent")
        help_footer.grid(row=6, column=0, sticky="ew", padx=20, pady=(1, 12))
        help_footer.grid_columnconfigure(0, weight=1)
        footer_font = self._font(12, "bold")
        self.help_footer_label = ctk.CTkLabel(
            help_footer,
            text=self._t("help_footer"),
            text_color=GOLD_LIGHT,
            font=footer_font,
            anchor="w",
            cursor="hand2",
        )
        self.help_footer_label.grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.help_footer_label.bind("<Button-1>", self.show_shortcuts_help)
        self.help_footer_label.bind("<Enter>", lambda _e: self.help_footer_label.configure(text_color=TEXT_PRIMARY))
        self.help_footer_label.bind("<Leave>", lambda _e: self.help_footer_label.configure(text_color=GOLD_LIGHT))
        self.favorite_filter_label = ctk.CTkLabel(
            help_footer, text=self._t('favorite_filter'), text_color=TEXT_DISABLED,
            font=footer_font, anchor='e',
        )
        self.favorite_filter_label.grid(row=0, column=1, sticky='e')
        self.favorite_filter_label.bind('<Button-1>', self._toggle_favorite_filter)
        self.favorite_filter_label.bind('<Enter>', lambda _e: self._update_favorite_filter(hover=True))
        self.favorite_filter_label.bind('<Leave>', lambda _e: self._update_favorite_filter())

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

    def _status_state(self):
        if getattr(self, "current_job_kind", None) == "batch":
            state = getattr(self, "_batch_progress_state", None)
        else:
            state = self.current.state if self.current is not None else None
        if state is None:
            return PairState()
        return state

    def _traffic_color(self) -> str:
        disparity = self._status_state().disparity
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
        self._status_caption_widgets = {}

        def add_label(name, row, *, height=STATUS_ROW_HEIGHT, muted=False,
                      bold=False, symbol_slot=False, paired=False, two_lines=False):
            # Only the input and deviation share their row with a symbol. Other
            # rows use the complete sidebar width instead of a permanent gutter.
            holder = ctk.CTkFrame(self.status_frame, height=height, fg_color="transparent")
            holder.grid(row=row, column=0,
                        columnspan=1 if symbol_slot and name != "deviation" else 2,
                        sticky="ew", padx=(0, 18) if name == "deviation" else
                        ((0, 8) if symbol_slot else 0))
            holder.grid_propagate(False)
            holder.grid_rowconfigure(0, weight=1)
            holder.grid_columnconfigure(0, weight=1)
            if paired:
                caption = ctk.CTkLabel(holder, text="", height=height, width=1,
                    text_color=TEXT_SECONDARY, font=self._font(13), anchor="w", justify="left")
                caption.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
                caption.grid_propagate(False)
                self._status_caption_widgets[name] = caption
                caption._status_full_text = ""
                holder.grid_columnconfigure(1, weight=0)
            label = ctk.CTkLabel(holder, text="", width=1, height=height,
                text_color=TEXT_SECONDARY if muted else TEXT_PRIMARY,
                font=self._font(12 if muted else 13, "bold" if bold else "normal"),
                justify="right" if paired else "left", anchor="e" if paired else "w",
                wraplength=292 if two_lines else 0)
            label.grid(row=0, column=1 if paired else 0, sticky="nsew")
            label.grid_propagate(False)
            if paired:
                # Keep numeric values together and align their right edges.
                # Column minima are updated from real scaled font metrics.
                label._status_holder = holder
                holder.bind("<Configure>", lambda _event, name=name: self._resize_status_pair(name), add="+")
            self._status_line_widgets[name] = label
            if name == "input":
                self._status_input_full_text = ""
                holder.bind("<Configure>", lambda _event: self._fit_status_input(), add="+")

        def add_spacer(row, height=4):
            spacer = ctk.CTkFrame(self.status_frame, height=height, fg_color="transparent")
            spacer.grid(row=row, column=0, sticky="ew")

        # Fixed allocations keep footer/buttons still while values, warnings,
        # file names and calculation state change. Font sizes remain 13/12 px.
        add_label("input", 0, height=38, symbol_slot=True, two_lines=True)
        add_spacer(1)
        add_label("analysis_model", 2, height=38, paired=True)
        add_label("vertical_error", 3, paired=True)
        add_label("vertical_shift", 4, paired=True)
        add_label("rotation", 5, paired=True)
        add_label("vergence", 6, paired=True)
        add_spacer(7)
        add_label("deviation", 8, symbol_slot=True)
        add_label("near_far", 9)
        add_label("warning", 10, height=STATUS_WARNING_HEIGHT, muted=True, bold=True,
                  two_lines=True)
        self._status_line_widgets["warning"].configure(text_color=GOLD_LIGHT)
        add_spacer(11)
        add_label("floating_title", 12, bold=True)
        add_label("floating_values", 13, muted=True)

    def _set_status_pair(self, name, caption, value):
        label = self._status_line_widgets[name]
        self._status_caption_widgets[name]._status_full_text = caption
        self._status_caption_widgets[name].configure(text=caption)
        label.configure(text=value)
        self._resize_status_pair(name)

    def _resize_status_pair(self, name):
        label = self._status_line_widgets[name]
        value = label.cget("text")
        # CTk widths are logical, Tk font measurements are physical pixels.
        # A fixed holder prevents long values from changing the sidebar width.
        lines = value.splitlines() or [""]
        width = max(int(label._label.tk.call("font", "measure",
                    label._label.cget("font"), line)) for line in lines)
        scale = label._get_widget_scaling()
        label._status_holder.grid_columnconfigure(1, minsize=width + round(2 * scale))
        caption = self._status_caption_widgets[name]
        text = caption._status_full_text
        available = label._status_holder.winfo_width() - width - round(10 * scale)
        caption_width = max(int(caption._label.tk.call("font", "measure",
            caption._label.cget("font"), line)) for line in (text.splitlines() or [""]))
        # Older sidecars can show both V and H here. Keep both values visible;
        # shorten the parenthetical caption when the values need its space.
        if available > 0 and caption_width > available and " (" in text:
            text = text.split(" (", 1)[0] + ":"
        if caption.cget("text") != text:
            caption.configure(text=text)

    def _fit_status_input(self):
        """Keep arbitrary file names in two fixed lines."""
        label = self._status_line_widgets["input"]
        scale = label._get_widget_scaling()
        width = max(1, label.winfo_width() - round(4 * scale))
        if width < 20:
            return
        font = label._label.cget("font")
        def measure(text):
            return int(label._label.tk.call("font", "measure", font, text))
        def prefix(text, available):
            lo, hi = 0, len(text)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if measure(text[:mid]) <= available:
                    lo = mid
                else:
                    hi = mid - 1
            return lo
        lines = self._status_input_full_text.splitlines()
        if not lines:
            lines = [""]
        if len(lines) == 1 and measure(lines[0]) > width:
            cut = prefix(lines[0], width)
            # Prefer a natural filename boundary to leaving just an extension
            # or a few letters alone on the second line.
            boundaries = [i + 1 for i, ch in enumerate(lines[0][:cut]) if ch in "_ /\\-"]
            natural = next((i for i in reversed(boundaries) if i >= cut // 2), None)
            cut = natural or cut
            lines = [lines[0][:cut].rstrip(), lines[0][cut:].lstrip()]
        if len(lines) > 2:
            lines = [lines[0], " ".join(lines[1:])]
        visible = [line if measure(line) <= width else
                   line[:prefix(line, max(0, width - measure("…")))] + "…" for line in lines]
        label.configure(text="\n".join(visible), wraplength=0)

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

        state = self._status_state()

        input_section, analysis, deviation, floating = build_status_sections(
            state, input_text=self._input_status_text(), language=self.settings.language
        )

        input_value = input_section.rows[0].value if input_section.rows else "–"
        self._status_input_full_text = f"{input_section.name}: {input_value}"
        self._fit_status_input()

        if analysis and len(analysis.rows) >= 6:
            self._set_status_pair("analysis_model",
                f"{analysis.rows[0].label}:\n{analysis.rows[1].label}:",
                f"{analysis.rows[0].value}\n{analysis.rows[1].value}")
            for name, item in zip(("vertical_error", "vertical_shift", "rotation", "vergence"),
                                  analysis.rows[2:]):
                self._set_status_pair(name, f"{item.label}:", item.value)
        else:
            for name in ("analysis_model", "vertical_error", "vertical_shift", "rotation", "vergence"):
                self._set_status_pair(name, "", "")

        deviation_item = next((item for item in deviation.rows if item.role == "deviation"), None) if deviation else None
        if deviation_item is not None:
            labels["deviation"].configure(text=f"{deviation_item.label}: {deviation_item.value}")
            self.traffic_label.configure(text_color=self._traffic_color())
            self.traffic_label.grid(row=8, column=1, sticky="e", pady=0)
        else:
            labels["deviation"].configure(text="")
            self.traffic_label.grid_forget()

        normal_items = [item for item in deviation.rows if item.role == "normal"] if deviation else []
        measurement_pending = self.current is not None and (
            self._show_calculation_status
            or self._measurement_after_id is not None
            or self._measurement_job_id is not None
        )
        labels["near_far"].configure(
            text_color=GOLD_LIGHT if measurement_pending else TEXT_PRIMARY,
            font=self._font(13, "bold" if measurement_pending else "normal"),
        )
        if measurement_pending:
            labels["near_far"].configure(text=self._t("status_calculating"))
        elif len(normal_items) >= 2:
            labels["near_far"].configure(
                text=f"{normal_items[0].label}: {normal_items[0].value} · "
                     f"{normal_items[1].label}: {normal_items[1].value}"
            )
        else:
            labels["near_far"].configure(text="")

        warnings = [item.value for item in deviation.rows if item.role == "warning" and item.value] if deviation else []
        # Keep the warning row allocated even when empty. This removes the last
        # source of vertical layout jumps in the status/footer area.
        # This line break is presentation only; saved/text reports retain the
        # complete single-line wording rather than breaking a table row.
        labels["warning"].configure(text=warnings[0].replace(" – ", " –\n", 1) if warnings else "")

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
                text=(getattr(self, '_folder_feedback', '') or ("" if self.current_job_kind == "batch" else
                      sidecar_status_text(self.current.sidecar if self.current else None, self.settings.language)))
            )
        if self._state_save_error:
            labels["warning"].configure(text=self._t("state_save_warning"))
        self._update_favorite_star()

    def _update_favorite_star(self, hover: bool = False) -> None:
        if not hasattr(self, "favorite_label"):
            return
        active = bool(self._status_state().favorite)
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

        if hasattr(self, "save_anaglyph"):
            self._set_checkbox_enabled(self.gray_anaglyph_box, not busy and bool(self.save_anaglyph.get()))
        if hasattr(self, "sbs_suffix_menu"):
            enabled = not busy and bool(self.use_custom_sbs_suffix.get())
            if not enabled:
                self._release_sbs_suffix_focus()
            self.sbs_suffix_menu.configure(
                state="normal" if enabled else "disabled",
                text_color=TEXT_PRIMARY if enabled else TEXT_DISABLED,
            )

        custom_active = not self.use_input_subfolder.get()
        custom_color = TEXT_PRIMARY if (custom_active and not busy) else TEXT_DISABLED
        if hasattr(self, "custom_output_label"):
            self.custom_output_label.configure(text_color=custom_color)
        if hasattr(self, "output_path_label"):
            self.output_path_label.configure(text_color=custom_color)

        self.previous_button.configure(
            state="normal" if can_navigate and self._navigation_index(-1) is not None else "disabled"
        )
        self.next_button.configure(
            state="normal" if can_navigate and self._navigation_index(1) is not None else "disabled"
        )
        self._update_favorite_filter()
        self.save_button.configure(state="normal" if has_source and not self.batch_mode and not busy else "disabled")
        self.save_series_input_button.configure(state='normal' if has_source and not busy else 'disabled')

        if busy:
            self._set_start_button_cancel()
        else:
            self._update_start_button_text()
            self._set_start_button_normal()

        self._update_grid_control_state()
        self._update_favorite_star()
        self._refresh_look_controls()
        self._refresh_exposure_controls()

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

    def _start_activity(self, *, delay=0) -> None:
        if self._spinner_stop_job:
            self.after_cancel(self._spinner_stop_job)
            self._spinner_stop_job = None
        if self._spinner_job:
            self.after_cancel(self._spinner_job)
            self._spinner_job = None
        if delay:
            self.activity_canvas.delete("all")
            self._busy_started_at = None
            self._spinner_job = self.after(delay, self._start_activity)
            return
        if self.busy_state == "idle":
            return
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
            look_enabled=self.settings.look_enabled, look_preset_id=self.settings.look_preset_id,
            look_path=self.settings.look_path, look_strength=self.settings.look_strength,
        )

    def _processing_defaults(self) -> ProcessingDefaults:
        look = self._current_look_option()
        return ProcessingDefaults(
            left_orientation=self.left_orientation.get(),
            right_orientation=self.right_orientation.get(),
            left_mirror=bool(self.left_mirror.get()),
            right_mirror=bool(self.right_mirror.get()),
            swap_eyes=bool(self.swap_eyes.get()),
            aspect=self.output_aspect.get(),
            color_enabled=bool(self.color_match_enabled.get()),
            look_enabled=look.enabled, look_preset_id=look.preset_id,
            look_path=look.path, look_strength=look.strength,
        )

    def _source_defaults(self, source: StereoSource) -> ProcessingDefaults:
        defaults = self._new_source_defaults()
        if self.current is not None and self.current.source.input_root == source.input_root:
            return replace(defaults, **asdict(self.current.state.input_transform))
        return defaults

    def _processing_options(
        self,
        *,
        keep_loaded_pair: bool = False,
        use_batch_defaults: bool = False,
        restart_alignment: bool = False,
    ) -> ProcessingOptions:
        defaults = self._source_defaults(self.current.source) if use_batch_defaults else self._processing_defaults()
        return ProcessingOptions(
            analysis_method=self.analysis_method.get(),
            save_sidecar=True,
            keep_loaded_pair=keep_loaded_pair,
            defaults=defaults,
            restart_alignment=restart_alignment,
        )

    def _persist_settings(self) -> None:
        self.settings.analysis_method = self.analysis_method.get()
        self.settings.use_input_output_subfolder = bool(self.use_input_subfolder.get())
        self.settings.append_deviation_to_filename = bool(self.append_deviation_to_filename.get())
        self.settings.gray_anaglyph = bool(self.gray_anaglyph.get())
        self.settings.save_cross = bool(self.save_cross.get())
        self.settings.tiff_sbs = bool(self.tiff_sbs.get())
        self.settings.save_anaglyph = bool(self.save_anaglyph.get())
        self.settings.use_custom_sbs_suffix = bool(self.use_custom_sbs_suffix.get())
        option = getattr(self, 'show_deviation_points', None)
        if option is not None:
            self.settings.show_deviation_points = bool(option.get())
        try:
            save_settings(self.settings)
        except (OSError, ValueError) as exc:
            # A preference write must not interrupt the current image callback
            # halfway through and leave its checkbox ahead of the actual state.
            if getattr(self, '_settings_save_error', None) != str(exc):
                self._settings_save_error = str(exc)
                log_failure("Save program settings", exc)
                messagebox.showerror(APP_NAME, self._t('settings_save_failed', text=str(exc)))
            return
        self._settings_save_error = None

    def _commit_sbs_suffix(self, *, show_error=False) -> bool:
        value = suffix_value(self.sbs_suffix_display.get(), self.settings.language)
        try:
            validate_sbs_suffix(value)
        except ValueError:
            if show_error and self.use_custom_sbs_suffix.get():
                messagebox.showerror(APP_NAME, self._t("invalid_sbs_suffix"))
                self.sbs_suffix_menu.focus_set()
            return not self.use_custom_sbs_suffix.get()
        if value != self.settings.sbs_suffix:
            self.settings.sbs_suffix = value
            self._persist_settings()
        return True

    def _on_sbs_suffix_selected(self, _value=None) -> None:
        if self._commit_sbs_suffix(show_error=True):
            self.focus_set()

    def _on_sbs_suffix_edited(self, _event=None) -> None:
        self._commit_sbs_suffix()

    def _on_sbs_suffix_return(self, _event=None):
        if self._commit_sbs_suffix(show_error=True):
            self.focus_set()
        return "break"

    def _on_sbs_suffix_escape(self, _event=None):
        # Valid edits are saved as they are typed; discard only invalid text.
        self._commit_sbs_suffix()
        self.sbs_suffix_display.set(suffix_label(self.settings.sbs_suffix, self.settings.language))
        self.focus_set()
        return "break"

    def _release_sbs_suffix_focus(self) -> None:
        menu = getattr(self, "sbs_suffix_menu", None)
        if menu is not None and self.focus_get() is menu._entry:
            self.focus_set()

    def _inline_editor(self, widget):
        if widget is None:
            return False
        return any(widget is getattr(getattr(self, name, None), "_entry", None)
                   for name in ("sbs_suffix_menu", "_exposure_entry"))

    def _release_inline_editor_focus(self):
        self._release_sbs_suffix_focus()
        entry = getattr(getattr(self, "_exposure_entry", None), "_entry", None)
        if entry is not None and self.focus_get() is entry:
            self._commit_exposure_entry(True)

    def _image_control_command(self, command):
        if command is None:
            return None
        def dispatch(*args, **kwargs):
            # Release before opening a dialog, so Tk cannot restore the editor
            # as the dialog's previous focus when it closes.
            self._release_inline_editor_focus()
            return command(*args, **kwargs)
        return dispatch

    def _on_control_pointer(self, event) -> None:
        if not self._inline_editor(event.widget):
            self._release_inline_editor_focus()

    def _on_export_options_changed(self) -> None:
        self._commit_sbs_suffix()
        self._persist_settings()
        self._refresh_control_states()

    def _effective_sbs_suffix(self) -> str:
        return self.settings.sbs_suffix if self.use_custom_sbs_suffix.get() else "_sbs"

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
        try:
            path = Path(selected)
            source = source_from_selected_stereo_file(path)
            sources = discover_stereo_file_sources(path.parent)
            index = next((i for i, item in enumerate(sources) if item.left_path == path), 0)
            self._set_source_collection(sources or [source], index, batch=False)
        except Exception as exc:
            messagebox.showerror(APP_NAME, self.tr.message(str(exc)))

    def choose_batch_pair(self) -> None:
        selected = filedialog.askdirectory(title=self._t("batch_pair_dialog"), initialdir=self._dialog_initial_dir())
        if not selected:
            return
        folder = Path(selected)
        try:
            sources = discover_pair_sources(folder)
        except Exception as exc:
            messagebox.showerror(APP_NAME, self.tr.message(str(exc)))
            return
        if not sources:
            messagebox.showerror(APP_NAME, self._t("no_pair_files"))
            return
        self._set_source_collection(sources, 0, batch=True)

    def choose_batch_stereo(self) -> None:
        selected = filedialog.askdirectory(title=self._t("batch_stereo_dialog"), initialdir=self._dialog_initial_dir())
        if not selected:
            return
        folder = Path(selected)
        try:
            sources = discover_stereo_file_sources(folder)
        except Exception as exc:
            messagebox.showerror(APP_NAME, self.tr.message(str(exc)))
            return
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
            self._favorite_indices,
        )
        if self.current is not None and not self._flush_state_save(explicit=True):
            return
        self._drop_prefetch()
        self._previous_decoded = self._previous_views = None
        self._browse_step = 1
        self.sources = list(sources)
        self.source_index = target_index
        self._favorite_indices = None
        self.batch_mode = bool(batch)
        self.settings.last_input_location = str(sources[self.source_index].input_root)
        self._persist_settings()
        self._load_source_index(
            self.source_index,
            rollback_context=rollback,
        )

    def _navigation_index(self, step, *, from_index=None):
        if from_index is None:
            from_index = self.source_index
        if from_index is None:
            return None
        start = from_index + step
        favorites = getattr(self, '_favorite_indices', None)
        if favorites is None:
            return start if 0 <= start < len(self.sources) else None
        stop = len(self.sources) if step > 0 else -1
        return next((index for index in range(start, stop, step) if index in favorites), None)

    def _navigate_source(self, step):
        if self.busy_state == 'idle':
            index = self._navigation_index(step)
            if index is not None and self._flush_state_save(explicit=True):
                self._browse_step = step
                self._load_source_index(index, inherit_look=True)
        return 'break'

    def previous_source(self, event=None):
        return self._navigate_source(-1)

    def next_source(self, event=None):
        return self._navigate_source(1)

    def _drop_prefetch(self):
        for item in self._prefetched:
            item.token.cancel()
            item.future.cancel()
        self._prefetched.clear()

    def _prefetch_neighbor(self):
        index = self._navigation_index(self._browse_step)
        if index is None or self.current is None:
            self._drop_prefetch()
            return
        loaded = self.current.loaded_pair
        if loaded.left.nbytes + loaded.right.nbytes > DECODED_CACHE_LIMIT:
            self._drop_prefetch()
            return
        indices = (index, self._navigation_index(self._browse_step, from_index=index))
        bounds, mode = self._preview_bounds(), self._effective_preview_mode()
        targets = []
        for index in indices:
            if index is None:
                continue
            source = self.sources[index]
            if source.kind == 'heif' or (self._previous_decoded and source == self._previous_decoded[0]):
                continue
            defaults = self._browse_defaults(source, inherit_look=True)
            targets.append((source, defaults, bounds, mode))

        reusable = {}
        for item in self._prefetched:
            key = item.source, item.defaults, item.bounds, item.mode
            if key in targets:
                if not item.future.done():
                    reusable[key] = item
                    continue
                try:
                    if item.future.result()[2] is not None:
                        reusable[key] = item
                        continue
                except Exception:
                    pass  # A failed speculative job must not affect navigation.
            item.token.cancel()
            item.future.cancel()

        self._prefetched = []
        for source, defaults, bounds, mode in targets:
            key = source, defaults, bounds, mode
            item = reusable.get(key)
            if item is None:
                prior = self._prefetched[-1].future if self._prefetched else None
                token = CancellationToken()
                future = self._prefetch_pool.submit(self._prepare_neighbor, *key, token, prior)
                item = PreviewPrefetch(*key, token, future)
            self._prefetched.append(item)

    @classmethod
    def _prepare_neighbor(cls, source, defaults, bounds, mode, token, prior=None):
        token.raise_if_cancelled()
        budget = DECODED_CACHE_LIMIT
        if prior is not None:
            try:
                budget -= prior.result()[3]
            except Exception:
                pass
        input_signature = browse_file_signature(source)
        decoded = preload_browsable_source(source, max_bytes=budget)
        if decoded is None:
            return None, None, None, 0
        token.raise_if_cancelled()
        session = browse_source(source, defaults, decoded=decoded)
        signature = input_signature, look_signature(session.state.look)
        loaded = session.loaded_pair
        decoded = loaded, session.source_stamp
        decoded_bytes = loaded.left.nbytes + loaded.right.nbytes
        if decoded_bytes > budget:
            return signature, None, None, 0
        prepared = cls._prepare_session_preview(session, bounds, token, mode)
        native = prepared.native_result
        views = native[4]
        left, right = mask_preview_pair(*views[2][session.state.color.enabled], session.state, session.state.look)
        frame = FittedBrowseFrame(left, right, preview_image(left, right, mode), mode)
        token.raise_if_cancelled()

        base = views[6]
        fits = tuple(eye for pair in views[2].values() for eye in pair)
        fitted_bytes = (decoded_bytes + sum(eye.nbytes for eye in (base.left, base.right, left, right, *fits))
                        + frame.image.width * frame.image.height * 4)
        if fitted_bytes > budget:
            return signature, decoded, None, decoded_bytes
        # Retain the native master only when both neighbors fit the browse cache budget.
        aligned = views[7][:2] if views[7] is not None else ()
        full_bytes = fitted_bytes + sum(eye.nbytes for eye in (*native[1:3], *aligned))
        if full_bytes > budget:
            native = (native[0], None, None, native[3], (*views[:7], None))
            full_bytes = fitted_bytes
        return signature, decoded, PreparedSessionPreview(session, native, frame), full_bytes

    @staticmethod
    def _prefetch_result(prefetch):
        try:
            signature, decoded, prepared, _size = prefetch.future.result()
            if prepared is not None:
                current = (browse_file_signature(prefetch.source), look_signature(prepared.session.state.look))
                if signature == current:
                    return decoded, prepared
            return decoded, None
        except Exception:
            # Fall back to the normal loader if speculative work failed.
            return None, None

    def _remember_previous_view(self, source):
        old = self.current
        if old is None or old.source == source or old.source not in self.sources:
            return
        self._previous_decoded = self._previous_views = None
        loaded = old.loaded_pair
        size = loaded.left.nbytes + loaded.right.nbytes
        if size > DECODED_CACHE_LIMIT:
            return
        self._previous_decoded = old.source, (loaded, old.source_stamp)
        if not self._has_fitted_native_view():
            return
        views = self._native_views
        base = views[6]
        size += base.left.nbytes + base.right.nbytes
        size += sum(eye.nbytes for pair in views[2].values() for eye in pair)
        if size <= DECODED_CACHE_LIMIT:
            # Keep the small fitted eyes and the reduced base. The native
            # master and detail texture can be prepared after the return.
            self._previous_views = (*views[:5], None, base, None)

    def _previous_browse_preview(self, source, defaults, bounds, decoded):
        views = self._previous_views
        if views is None or views[4] != bounds:
            return None
        try:
            session = browse_source(source, defaults, decoded=decoded, require_decoded=True)
        except (OSError, ValueError):
            return None
        if session is None:
            return None
        key = native_key(session)
        color = session.state.color
        if key[0][1] != views[0][1] or color.strength != views[1]:
            return None
        fitted_color = views[3]
        if color.valid and (color.basis != fitted_color.basis or color.parameters != fitted_color.parameters):
            return None
        return PreparedSessionPreview(session, (key, None, None, fitted_color, (key[0], *views[1:])))

    def _browse_defaults(self, source, *, inherit_look):
        defaults = self._source_defaults(source)
        look = LookState()
        if inherit_look and self.current is not None and self.current.source.input_root == source.input_root:
            look = self.current.state.look
        return replace(defaults, look_enabled=look.enabled, look_preset_id=look.preset_id,
                       look_path=look.path, look_strength=look.strength)

    def _load_source_index(
        self,
        index: int,
        *,
        inherit_look: bool = False,
        rollback_context: tuple[list[StereoSource], int | None, bool, str, set[int] | None] | None = None,
    ) -> None:
        if not (0 <= index < len(self.sources)):
            return
        self._take_geometry_draft()
        self._cancel_look_hover(refresh=False)
        self._folder_feedback = ''
        if rollback_context is None:
            rollback_context = (
                list(self.sources),
                self.source_index,
                bool(self.batch_mode),
                str(self.settings.last_input_location or ""),
                self._favorite_indices,
            )
        self._load_rollback_context = rollback_context
        source = self.sources[index]
        self.source_index = index
        self.measure_cross_active = False
        self.measure_cross_x = None
        self.measure_cross_y = None
        self._stop_measure_repeat()

        defaults = self._browse_defaults(source, inherit_look=inherit_look)
        bounds = self._preview_bounds()
        mode = self._effective_preview_mode()

        cached = self._previous_decoded
        key = source, defaults, bounds, mode
        prefetch = next((item for item in self._prefetched
                         if (item.source, item.defaults, item.bounds, item.mode) == key), None)
        if prefetch is None:
            self._drop_prefetch()
        else:
            self._prefetched.remove(prefetch)

        decoded = cached[1] if cached and cached[0] == source else None
        prepared = self._previous_browse_preview(source, defaults, bounds, decoded) if decoded is not None else None
        if prepared is None and prefetch is not None and prefetch.future.done():
            prefetched_decoded, prepared = self._prefetch_result(prefetch)
            decoded = prefetched_decoded or decoded
            prefetch = None
        if prepared is not None:
            if self._spinner_stop_job is not None:
                self.after_cancel(self._spinner_stop_job)
                self._finish_activity()
            self._prepare_for_job("load")
            self._adopt_session_preview("load", prepared)
            return

        def job(token, _progress):
            loaded = decoded
            if prefetch is not None:
                while not prefetch.future.done():
                    if token.cancelled:
                        prefetch.token.cancel()
                        token.raise_if_cancelled()
                    wait((prefetch.future,), timeout=.05)
                token.raise_if_cancelled()
                prefetched_decoded, prepared = self._prefetch_result(prefetch)
                if prepared is not None:
                    return prepared
                loaded = prefetched_decoded or loaded
            token.raise_if_cancelled()
            session = browse_source(source, defaults, decoded=loaded)
            return self._prepare_session_preview(session, bounds, token, mode)

        self._start_worker("load", self._t("loading"), job)

    @staticmethod
    def _prepare_session_preview(session, bounds, token, mode='Farbig'):
        token.raise_if_cancelled()
        native = prepare_native_preview(session.loaded_pair, deepcopy(session.state),
                                        native_key(session), bounds, token, mode)
        base = native[4][6]
        h, w = base.master_shape
        dx, dy = clamp_offset_for_size(w, h, session.state.effective_offset_x_px,
                                      session.state.effective_offset_y_px)
        session.state.manual.delta_x_px = dx - session.state.auto_offset_x_px
        session.state.manual.delta_y_px = dy
        key = native_key(session)
        native = (key, *native[1:4], (key[0], *native[4][1:]))
        return PreparedSessionPreview(session, native)

    def _install_session_preview(self, prepared, *, preserve_inspection=False) -> None:
        view = getattr(self, '_inspection_view', None)
        previous_size = self._view_image_size() if preserve_inspection and view is not None and view.active else None
        previous_scale, previous_center = (view.scale, view.center) if previous_size else (None, None)
        self._reset_view_for_source()
        left = prepared.native_result[1]
        if previous_size and left is not None:
            size = left.shape[1], left.shape[0]
            viewport = self._view_viewport()
            if previous_scale > view.fit_scale(size, viewport):
                view.scale = previous_scale
                if previous_center is not None:
                    view.center = (previous_center[0] * size[0] / previous_size[0],
                                   previous_center[1] * size[1] / previous_size[1])
                view.layout(size, viewport)
        # Adopt one complete result. The first visible frame already has the
        # master crop; no reduced proxy is replaced after the ready signal.
        if self._native_after_id is not None:
            self.after_cancel(self._native_after_id)
            self._native_after_id = None
        self._detail_session_id = id(prepared.session)
        self._detail_center = None
        self._native_cache = prepared.native_result[:3] if prepared.native_result[1] is not None else None
        self._native_views = prepared.native_result[4]
        self._native_fit_cache = None
        self._native_failed_key = None
        self._native_deferred = False
        if len(self._native_views) > 6:
            self._preview_base = self._native_views[6]
            self._preview_base_session_id = id(prepared.session)

    def _restore_load_rollback(self) -> None:
        context = self._load_rollback_context
        self._load_rollback_context = None
        if context is None:
            return
        sources, index, batch_mode, last_input, favorite_indices = context
        self.sources = list(sources)
        self.source_index = index
        self.batch_mode = bool(batch_mode)
        self._favorite_indices = favorite_indices
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
        self._sync_look_from_current()
        self._sync_exposure_controls()
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
        if not create_if_missing and self.current.sidecar.status != SidecarStatus.VALID:
            return
        self._state_dirty = True
        self._state_dirty_can_create_sidecar = self._state_dirty_can_create_sidecar or bool(create_if_missing)
        if self._save_after_id:
            try:
                self.after_cancel(self._save_after_id)
            except Exception:
                pass
            self._save_after_id = None

        if immediate:
            self._flush_state_save()
        else:
            self._save_after_id = self.after(220, self._flush_state_save)

    def _flush_state_save(self, *, explicit: bool = False) -> bool:
        if self._save_after_id:
            try:
                self.after_cancel(self._save_after_id)
            except Exception:
                pass
            self._save_after_id = None
        if self.current is None or not self._state_dirty:
            return True
        reusable = self.current.sidecar.status == SidecarStatus.VALID
        try:
            if reusable or self._state_dirty_can_create_sidecar:
                save_browsed_state(self.current)
                updated = load_sidecar(self.current.source.sidecar_path, expected_source=self.current.source_stamp)
                if updated.status != SidecarStatus.VALID:
                    raise OSError(updated.message or "Saved settings could not be verified.")
                self.current.sidecar = updated
        except Exception as exc:
            # Keep the current state dirty. Export/navigation/close must retry
            # successfully before reading a sidecar or discarding this session.
            self._state_save_error = str(exc)
            source = getattr(self.current, "source", None)
            log_failure("Save image settings", exc, source=getattr(source, "sidecar_path", None))
            self._render_status()
            if explicit:
                messagebox.showerror(APP_NAME, self._t("state_save_failed", text=str(exc)))
            return False
        self._state_save_error = None
        self._state_dirty = False
        self._state_dirty_can_create_sidecar = False
        self._render_status()
        return True

    def _on_input_transform_changed(self, _value=None) -> None:
        self.left_orientation_display.set(orientation_label(self.left_orientation.get(), self.settings.language))
        self.right_orientation_display.set(orientation_label(self.right_orientation.get(), self.settings.language))
        if self.current is None or self.busy_state != "idle":
            return
        state = self.current.state
        transform = InputTransformState(
            left_orientation=self.left_orientation.get(),
            right_orientation=self.right_orientation.get(),
            left_mirror=bool(self.left_mirror.get()),
            right_mirror=bool(self.right_mirror.get()),
            swap_eyes=bool(self.swap_eyes.get()),
        )
        if transform == state.input_transform:
            return
        self._take_geometry_draft()
        state.input_transform = transform
        state.invalidate_for_input_transform()
        self._sync_vars_from_current()
        self._schedule_state_save()
        self._refresh_preview(rebuild_base=True)
        self._render_status()
        self._refresh_control_states()

    def _save_series_input(self) -> None:
        if self.current is None or self.busy_state != 'idle' or not self._flush_state_save(explicit=True):
            return
        try:
            save_series_input(self.current.source, self.current.state.input_transform)
        except OSError as exc:
            messagebox.showerror(APP_NAME, self._t('state_save_failed', text=str(exc)))
            return
        self._folder_feedback = self._t('series_input_saved')
        self._render_status()

    def _on_aspect_changed(self, _value=None) -> None:
        self.output_aspect_display.set(aspect_label(self.output_aspect.get(), self.settings.language))
        self.settings.default_aspect = self.output_aspect.get()
        self._persist_settings()
        if self.current is None or self.busy_state != "idle":
            return
        state = self.current.state
        from .preferences import mark_preference
        mark_preference(state, 'aspect')
        if state.framing.aspect != self.output_aspect.get():
            state.framing.aspect = self.output_aspect.get()
            state.framing.pan_x_permille = 0
            state.framing.pan_y_permille = 0
            state.invalidate_disparity_for_framing("aspect_changed")
            self._schedule_disparity_refresh()
        self._schedule_state_save()
        self._refresh_preview()
        self._render_status()

    def _on_color_match_changed(self) -> None:
        self.settings.color_match_enabled = bool(self.color_match_enabled.get())
        self._persist_settings()
        if self.current is None or self.busy_state != "idle":
            return
        self.current.state.color.enabled = bool(self.color_match_enabled.get())
        from .preferences import mark_preference
        mark_preference(self.current.state, 'color')
        self.current.state.color.strength = 1.0
        self._schedule_state_save()
        self._refresh_preview()

    def _on_favorite_clicked(self, _event=None):
        if self.current is None or self.busy_state != "idle":
            return "break"
        self.current.state.favorite = not self.current.state.favorite
        self._schedule_state_save(immediate=True)
        self._update_favorite_star()
        if getattr(self, '_favorite_indices', None) is not None and self.source_index is not None:
            if self.current.state.favorite:
                self._favorite_indices.add(self.source_index)
            else:
                self._favorite_indices.discard(self.source_index)
                if not self._favorite_indices:
                    self._favorite_indices = None
            self._refresh_control_states()
        return "break"

    def _update_favorite_filter(self, hover=False):
        label = getattr(self, 'favorite_filter_label', None)
        if label is None:
            return
        enabled = self.busy_state == 'idle' and self.current is not None and len(self.sources) > 1
        if self._favorite_indices is not None and (enabled or self.busy_state == 'load'):
            color = GOLD_LIGHT
        elif enabled:
            color = TEXT_PRIMARY if hover else TEXT_SECONDARY
        else:
            color = TEXT_DISABLED
        label.configure(text_color=color, cursor='hand2' if enabled else '')

    def _toggle_favorite_filter(self, _event=None):
        if self.busy_state != 'idle' or self.current is None or self.source_index is None or len(self.sources) < 2:
            return 'break'
        if self._favorite_indices is not None:
            self._favorite_indices = None
        else:
            if not self._flush_state_save(explicit=True):
                return 'break'
            favorites = {i for i, source in enumerate(self.sources)
                         if (self.current.state.favorite if i == self.source_index else is_saved_favorite(source))}
            if not favorites:
                messagebox.showinfo(APP_NAME, self._t('favorite_filter_empty'))
                return 'break'
            self._favorite_indices = favorites
            if self.source_index not in favorites:
                index = self._navigation_index(1)
                self._load_source_index(max(favorites) if index is None else index)
        self._refresh_control_states()
        return 'break'

    def reset_manual_to_auto(self) -> None:
        if self.current is None or self.busy_state != "idle":
            return
        if self.current.state.geometry.active:
            if self._flush_state_save(explicit=True):
                self._start_single_analysis(geometry=GeometryAdjustment(), reset_manual_edits=True)
            return
        self.current.state.reset_manual_to_auto()
        self._schedule_disparity_refresh()
        self._schedule_state_save(immediate=True)
        self._refresh_preview()
        self._render_status()

    def _adjust_manual_offset(self, dx: int = 0, dy: int = 0) -> None:
        if self.current is None or self.busy_state != "idle":
            return
        state = self.current.state
        state.manual.delta_x_px += int(dx)
        state.manual.delta_y_px += int(dy)
        base = self._ensure_preview_base(self.current)
        if base.master_shape is not None:
            h, w = base.master_shape
            x, y = clamp_offset_for_size(w, h, state.effective_offset_x_px, state.effective_offset_y_px)
            state.manual.delta_x_px = x - state.auto_offset_x_px
            state.manual.delta_y_px = y
        state.color.valid = False
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
            self._schedule_disparity_refresh()
            self._schedule_state_save()
            self._refresh_preview()
            self._schedule_status_refresh()

    def _framing_step_permille(self, axis: str = "x") -> int:
        if self.current is None:
            return 0
        # Use the same pre-framing overlap as the renderer. The displayed
        # pair is already cropped and cannot describe the available pan range.
        base = self._ensure_preview_base(self.current)
        state = self.current.state
        left, _right, _ = crop_shifted_pair_to_overlap(
            base.left, base.right,
            int(round(state.effective_offset_x_px * base.scale)),
            int(round(state.effective_offset_y_px * base.scale)),
        )
        height, width = left.shape[:2]
        zoom_index = max(0, min(len(CROP_ZOOM_LEVELS) - 1, int(state.framing.crop_zoom_index)))
        crop_w, crop_h, max_x, max_y = framing_crop_geometry(
            width,
            height,
            state.framing.aspect,
            CROP_ZOOM_LEVELS[zoom_index],
            base.original_aspect,
        )
        _ = crop_w, crop_h
        max_shift = max_x if axis == "x" else max_y
        if max_shift <= 0.5:
            return 0
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
            self._schedule_disparity_refresh()
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
    def _cancel_disparity_refresh(self) -> None:
        if self._measurement_after_id is not None:
            self.after_cancel(self._measurement_after_id)
            self._measurement_after_id = None
        self.measurement_worker.cancel_all()
        self._measurement_job_id = None
        self._measurement_session = None
        self._measurement_basis = None

    def _schedule_disparity_refresh(self) -> None:
        self._cancel_disparity_refresh()
        if (self.current is not None and self.busy_state == "idle"
                and self.current.state.alignment.valid
                and (self.current.state.disparity.stale or self._needs_endpoint_refresh())):
            self._measurement_after_id = self.after(450, self._run_disparity_refresh)
        self._render_status()

    def _run_disparity_refresh(self) -> None:
        from .processing import current_disparity_basis, refresh_current_disparity
        self._measurement_after_id = None
        if self.current is None or self.busy_state != "idle":
            self._render_status()
            return
        state = self.current.state
        if not state.alignment.valid or not (state.disparity.stale or self._needs_endpoint_refresh()):
            self._render_status()
            return
        if self._measurement_running_id and self.measurement_worker.is_running(self._measurement_running_id):
            self._measurement_after_id = self.after(100, self._run_disparity_refresh)
            return
        snapshot = deepcopy(state)
        loaded = self.current.loaded_pair
        self._measurement_session = self.current
        self._measurement_basis = current_disparity_basis(snapshot)
        def job(token, _progress):
            refresh_current_disparity(loaded, snapshot, cancellation=token)
            return snapshot.disparity
        self._measurement_job_id = self.measurement_worker.start(job, name="StereoFine-measurement").job_id
        self._measurement_running_id = self._measurement_job_id

    def _poll_disparity_refresh(self) -> None:
        from .processing import current_disparity_basis, disparity_basis_matches
        try:
            while True:
                message = self.measurement_worker.messages.get_nowait()
                if (message.job_id != self._measurement_job_id or self.current is not self._measurement_session
                        or self.current is None or self.busy_state != "idle"
                        or not disparity_basis_matches(current_disparity_basis(self.current.state), self._measurement_basis)):
                    continue
                if message.kind == WorkerMessageKind.RESULT:
                    self.current.state.disparity = message.payload
                    self._measurement_job_id = None
                    self._schedule_state_save(create_if_missing=False)
                    self._render_status()
                    if getattr(self, '_preview_pil', None) is not None:
                        self._update_preview_display()
                elif message.kind in {WorkerMessageKind.ERROR, WorkerMessageKind.CANCELLED}:
                    self._measurement_job_id = None
                    if message.kind == WorkerMessageKind.ERROR:
                        self.current.state.disparity.valid = False
                        self.current.state.disparity.status = "error"
                    self._render_status()
        except queue.Empty:
            pass

    def _invalidate_preview_base(self) -> None:
        self._preview_base = None
        self._preview_base_session_id = None
        self._preview_left_current = None
        self._preview_right_current = None

    def _load_start_image(self) -> None:
        try:
            loaded = load_full_sbs(Path("stereofine.jpg"), jpeg_data=start_image_bytes())
            state = PairState()
            self._invalidate_preview_base()
            base = self._build_fitted_preview_base(loaded, state)
            self._display_base_preview(base, state, apply_adjustments=False)
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

    def _build_fitted_preview_base(self, loaded: LoadedStereoPair, state: PairState) -> PreviewBasePair:
        bound_w, bound_h = self._preview_bounds()
        return build_preview_base(
            loaded, state,
            max_width=min(PREVIEW_RENDER_MAX_WIDTH, max(320, int(bound_w))),
            max_height=min(PREVIEW_RENDER_MAX_HEIGHT, max(240, int(bound_h))),
            apply_color=False,
        )

    def _ensure_preview_base(self, session: BrowsedSource) -> PreviewBasePair:
        session_id = id(session)
        if (self._preview_base is None or self._preview_base_session_id != session_id
                or self._preview_base.source_token != id(session.loaded_pair)
                or self._preview_base.geometry_key != preview_geometry_key(session.state)):
            self._preview_base = self._build_fitted_preview_base(session.loaded_pair, session.state)
            self._preview_base_session_id = session_id
        return self._preview_base

    def _build_preview_anaglyph(self) -> None:
        if self._preview_left_current is None or self._preview_right_current is None:
            return

        # As in the proven v41 data flow, the current preview pair already
        # contains the Floating-Window masks.  Build the anaglyph from that
        # authoritative pair using StereoFine's current colorimetric mixer.
        mode = self._effective_preview_mode()
        self._preview_pil = preview_image(self._preview_left_current, self._preview_right_current, mode)
        self._update_preview_display()

    def _render_session_preview(self, session: BrowsedSource, *, fitted_frame=None) -> None:
        if session is self.current:
            applied = (self._apply_native_preview() if fitted_frame is None else
                       self._apply_native_preview(fitted_frame=fitted_frame))
            if applied:
                if (self._native_cache is None or self._native_cache[0] != native_key(session)
                        or self._native_views_need_resize()):
                    self._request_native_preview()
                return
        if (session is self.current
                and getattr(self, "_inspection_view", None) is not None and self._inspection_view.active):
            self._show_inspection_preview()
            return
        base = self._ensure_preview_base(session)
        state = session.state
        if getattr(self, '_look_hover_state', None) is not None and session is self.current:
            state = deepcopy(state)
            state.look = deepcopy(self._look_hover_state)
        self._display_base_preview(base, state, apply_adjustments=True)
        self._request_native_preview()

    def _display_base_preview(self, base: PreviewBasePair, state: PairState, *, apply_adjustments: bool) -> None:
        pair = render_preview_from_base(
            base,
            state,
            apply_color=apply_adjustments,
            apply_floating_window=apply_adjustments,
            bounds=self._preview_bounds(),
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
        draft = self._geometry_draft
        draft_changed = self._geometry_draft_has_changes()
        if not draft_changed:
            if self.detail_active:
                self._show_detail_preview()
                return
            if self._inspection_view.active:
                self._show_inspection_preview()
                return
            source_image = self._preview_pil
        else:
            try:
                source_image = self._geometry_draft_image(draft)
            except (ValueError, OSError) as exc:
                self.preview_label.configure(text=self._t("preview_error", text=self.tr.message(str(exc))),
                                             text_color=TEXT_PRIMARY, image=None)
                return
        if source_image is None:
            return

        max_width, max_height = self._preview_bounds()
        source_w, source_h = source_image.size
        scale = min(max_width / max(1, source_w), max_height / max(1, source_h))
        display_size = (
            max(1, int(round(source_w * scale))),
            max(1, int(round(source_h * scale))),
        )
        image = self._preview_display_cache.scaled(source_image, display_size, resampling)

        # Overlays belong to the visible preview and therefore stay crisp and
        # correctly scaled while the main window changes size.
        if not self.measure_cross_active and self.grid_mode.get() != "Aus":
            if self._effective_preview_mode() == "Kreuzblick":
                split = image.width // 2
                image = image.copy()
                for box in ((0, 0, split, image.height), (split, 0, image.width, image.height)):
                    image.paste(draw_grid_overlay(image.crop(box), self.grid_spacing.get(), self.grid_mode.get()), box)
            else:
                image = draw_grid_overlay(image, self.grid_spacing.get(), self.grid_mode.get())
        if self.measure_cross_active:
            if self._measure_display_size and self.measure_cross_x is not None and self.measure_cross_y is not None:
                old_w, old_h = self._measure_display_size
                if old_w > 0 and old_h > 0 and (old_w, old_h) != display_size:
                    self.measure_cross_x *= display_size[0] / old_w
                    self.measure_cross_y *= display_size[1] / old_h
            self._preview_display_size = display_size
            self._measure_display_size = display_size
            self._clamp_measure_cross(display_size)
            image = draw_measure_cross_overlay(image, self.measure_cross_x, self.measure_cross_y)
        else:
            self._preview_display_size = display_size

        if not draft_changed:
            native_size = self._view_image_size()
            if self.current is not None and native_size is not None:
                image = self._decorate_view(image,(0,0,*native_size),native_size)
        if draft is not None:
            image = self._decorate_geometry_draft(image, draft)

        border = preview_border_px(display_size[0])
        self.preview_label.grid_configure(padx=border, pady=border)
        scaling = self.preview_label._get_widget_scaling()
        logical_size = (image.width / scaling, image.height / scaling)
        new_image = ctk.CTkImage(light_image=image, dark_image=image, size=logical_size)
        self.preview_label.configure(text="", image=new_image)
        self._preview_ctk_image = new_image

    def _refresh_preview(self, *, rebuild_base: bool = False, fitted_frame=None) -> None:
        if rebuild_base:
            self._invalidate_preview_base()
        if self._geometry_draft is not None:
            self._geometry_draft.preview = self._geometry_draft.image = None
            if self._geometry_draft_has_changes():
                self._update_preview_display()
                return
        if self.current is not None:
            try:
                if fitted_frame is None:
                    self._render_session_preview(self.current)
                else:
                    self._render_session_preview(self.current, fitted_frame=fitted_frame)
            except Exception as exc:
                self.preview_label.configure(text=self._t("preview_error", text=self.tr.message(str(exc))), text_color=TEXT_PRIMARY, image=None)
        else:
            self._load_start_image()

    def _effective_preview_mode(self) -> str:
        if self.measure_cross_active and self.preview_mode.get() == "Kreuzblick":
            return self._last_anaglyph_preview_mode
        return self.preview_mode.get()

    def _on_preview_mode_changed(self) -> None:
        if self.preview_mode.get() == 'Kreuzblick':
            self._end_point_measurement()
        if self.preview_mode.get() != "Kreuzblick":
            self._last_anaglyph_preview_mode = self.preview_mode.get()
        if self._geometry_draft_has_changes():
            self._update_preview_display()
        elif self._preview_left_current is not None and self._preview_right_current is not None:
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
    def _prepare_for_job(self, kind: str) -> None:
        if 'c' in getattr(self, '_shortcut_keys_down', ()):
            self._cancel_mode_release('look')
            self._release_shortcut_key('c')
        if kind == "save":
            self._stop_detail_repeat()
            self._stop_measure_repeat()
        else:
            self._end_detail_preview()
        self._cancel_disparity_refresh()

    def _start_worker(self, kind: str, button_text: str, function) -> None:
        if self.busy_state != "idle":
            return
        self._prepare_for_job(kind)
        self.busy_state = kind
        self.current_job_kind = kind
        self._render_status()
        # ``button_text`` is retained for call-site clarity/history, but the
        # primary action itself is always the active cancellation affordance
        # while work is running. Progress is shown by preview/status/spinner.
        _ = button_text
        self._refresh_control_states()
        if kind == "load":
            self._start_activity(delay=BROWSE_ACTIVITY_DELAY_MS)
        else:
            self._start_activity()
        job = self.worker.start(function, name=f"StereoFine-{kind}")
        self.current_job_id = job.job_id

    def start_processing(self, event=None):
        if self.current is None or self.busy_state != "idle" or self._geometry_draft is not None:
            return "break"
        if not self._flush_state_save(explicit=True):
            return "break"
        if self.batch_mode:
            self._start_batch_run()
        else:
            self._start_single_analysis()
        return "break"

    def _start_single_analysis(self, *, geometry=None, reset_manual_edits: bool = False):
        source = self.current.source
        options = replace(self._processing_options(keep_loaded_pair=True, restart_alignment=True),
                          save_sidecar=False, geometry=geometry, reset_manual_edits=reset_manual_edits,
                          expected_source_stamp=self.current.source_stamp if geometry is not None else None,
                          parallel_features=batch_worker_count(self.current.loaded_pair) > 1)
        bounds = self._preview_bounds()
        mode = self._effective_preview_mode()
        missing_preview = self._t("internal_preview_error")

        def job(token, _progress):
            processed = process_source(source, options, cancellation=token)
            if processed.loaded_pair is None:
                raise RuntimeError(missing_preview)
            sidecar = load_sidecar(processed.source.sidecar_path, expected_source=processed.source_stamp)
            session = BrowsedSource(processed.source, processed.loaded_pair,
                                    processed.source_stamp, processed.state, sidecar)
            return self._prepare_session_preview(session, bounds, token, mode)

        self._show_calculation_status = geometry is not None
        self._start_worker("analysis", self._t("alignment_running"), job)

    def _start_batch_run(self) -> None:
        if not self.sources:
            return
        if not self.analysis_only.get() and not self._commit_sbs_suffix(show_error=True):
            return
        root = self.sources[0].input_root
        paired = self.sources[0].kind == "pair"
        discover = discover_pair_sources if paired else discover_stereo_file_sources
        try:
            sources = discover(root)
        except Exception as exc:
            messagebox.showerror(APP_NAME, self.tr.message(str(exc)))
            return
        if not sources:
            messagebox.showerror(APP_NAME, self._t("no_pair_files" if paired else "no_stereo_files"))
            return
        self._inspection_view.reset()
        self._end_point_measurement()
        self._batch_progress_index = None
        self._batch_progress_total = None
        self._batch_progress_source_name = None
        self._batch_progress_state = None
        output_folder = None if self.analysis_only.get() else self._effective_output_folder(root)
        if not self.analysis_only.get() and output_folder is None:
            messagebox.showinfo(APP_NAME, self._t("select_output_folder"))
            return
        options = BatchRunOptions(
            processing=self._processing_options(keep_loaded_pair=False, use_batch_defaults=True),
            analysis_workers=batch_worker_count(self.current.loaded_pair),
            analysis_only=bool(self.analysis_only.get()),
            favorites_only=bool(self.favorites_only.get()),
            output_folder=output_folder,
            gray_anaglyph=bool(self.gray_anaglyph.get()),
            save_cross=bool(self.save_cross.get()),
            tiff_sbs=bool(self.tiff_sbs.get()),
            save_anaglyph=bool(self.save_anaglyph.get()),
            sbs_suffix=self._effective_sbs_suffix(),
            preview_mode=self.preview_mode.get(),
            language=self.settings.language,
            append_deviation_to_filename=bool(self.append_deviation_to_filename.get()),
        )

        self._drop_prefetch()
        self._previous_decoded = self._previous_views = None
        if sources != self.sources:
            self.sources = sources
            self.source_index = next((i for i, source in enumerate(sources) if source == self.current.source), None)
            if self._favorite_indices is not None:
                self._favorite_indices = {i for i, source in enumerate(sources) if is_saved_favorite(source)} or None
        batch_sources = tuple(sources)

        def job(token, progress):
            return run_batch(batch_sources, options, cancellation=token, progress=progress)

        text = self._t("analysis_running") if self.analysis_only.get() else self._t("batch_running")
        self._start_worker("batch", text, job)

    def save_current_result(self, event=None):
        if self._geometry_draft is not None:
            return self._commit_geometry_draft() if event is not None else "break"
        if self.current is None or self.batch_mode or self.busy_state != "idle":
            return "break"
        if not self._flush_state_save(explicit=True):
            return "break"
        if not self._commit_sbs_suffix(show_error=True):
            return "break"
        output_folder = self._effective_output_folder(self.current.source.input_root)
        if output_folder is None:
            messagebox.showinfo(APP_NAME, self._t("select_output_folder"))
            return "break"
        options = BatchRunOptions(
            processing=replace(self._processing_options(keep_loaded_pair=False),
                               expected_source_stamp=self.current.source_stamp),
            output_folder=output_folder,
            gray_anaglyph=bool(self.gray_anaglyph.get()),
            save_cross=bool(self.save_cross.get()),
            tiff_sbs=bool(self.tiff_sbs.get()),
            save_anaglyph=bool(self.save_anaglyph.get()),
            sbs_suffix=self._effective_sbs_suffix(),
            preview_mode=self.preview_mode.get(),
            language=self.settings.language,
            append_deviation_to_filename=bool(self.append_deviation_to_filename.get()),
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
                    self._finish_worker_cancelled(message.payload)
                elif message.kind == WorkerMessageKind.ERROR:
                    self._finish_worker_error(message.payload)
        except queue.Empty:
            pass
        finally:
            self._poll_disparity_refresh()
            self.after(20, self._poll_worker_messages)

    def _handle_progress(self, payload: Any) -> None:
        if self.current_job_kind == 'folder_settings':
            dialog = getattr(self, '_folder_dialog', None)
            if dialog is not None:
                dialog.update_progress(payload)
            return
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
            self._batch_progress_state = getattr(payload, "state", None)
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
        if self._show_calculation_status:
            self._show_calculation_status = False
            self._render_status()
        if kind == "batch":
            self._batch_progress_index = None
            self._batch_progress_total = None
            self._batch_progress_source_name = None
            self._batch_progress_state = None
        self._refresh_control_states()
        self._stop_activity()
        return kind

    def _adopt_session_preview(self, kind, payload) -> None:
        if kind == "load":
            self._load_rollback_context = None
            self._remember_previous_view(payload.session.source if isinstance(payload, PreparedSessionPreview)
                                         else payload.source)
        fitted_frame = None
        if isinstance(payload, PreparedSessionPreview):
            fitted_frame = payload.fitted_frame
            self._install_session_preview(payload, preserve_inspection=kind == "analysis")
            payload = payload.session
        self.current = payload
        self._state_dirty = False
        self._state_dirty_can_create_sidecar = False
        self._sync_vars_from_current()
        if fitted_frame is None:
            self._refresh_preview()
        else:
            self._refresh_preview(fitted_frame=fitted_frame)
        self._render_status()
        self._refresh_control_states()
        if kind == "load":
            self._schedule_disparity_refresh()
            self._prefetch_neighbor()
        else:
            play_ready_sound(asset_path("ready.wav"))
        self._release_inline_editor_focus()

    def _finish_worker_success(self, payload: Any) -> None:
        kind = self._finish_busy_common()
        if kind == 'folder_settings':
            from .folder_dialog import finish_folder_settings
            finish_folder_settings(self, payload)
            return
        if kind == 'analysis' and isinstance(payload, PreparedSessionPreview):
            # The worker result is only provisional until analysis AND its view
            # are ready. A late cancellation must leave the old .sfin untouched.
            try:
                color = deepcopy(payload.native_result[3])
                color.enabled = payload.session.state.color.enabled
                payload.session.state.color = color
                save_browsed_state(payload.session, save_orientation=True)
                payload.session.sidecar = load_sidecar(payload.session.source.sidecar_path,
                                                       expected_source=payload.session.source_stamp)
            except Exception as exc:
                log_failure("Save completed analysis", exc, source=payload.session.source.sidecar_path)
                messagebox.showerror(APP_NAME, self._t('state_save_failed', text=str(exc)))
                self._refresh_preview()
                return
        if kind in {"load", "analysis"} and isinstance(payload, (PreparedSessionPreview, BrowsedSource)):
            self._adopt_session_preview(kind, payload)
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
            # A single-image export does not change the source pixels. Adopt
            # its saved state without replacing the session or its view caches.
            if kind == "save":
                if not self._adopt_saved_result(payload):
                    # Per-image export failures are returned as a batch result,
                    # not a worker exception. Resume a view finished during the
                    # failed save just as the worker-error path does.
                    self._refresh_preview()
                return
            if self.sources:
                self._load_source_index(self._batch_return_index(), inherit_look=True)

    def _batch_return_index(self) -> int:
        if self.source_index is not None:
            return self.source_index
        return min(self._favorite_indices or {0})

    def _adopt_saved_result(self, payload: BatchRunResult) -> bool:
        if self.current is None or payload.failed or len(payload.items) != 1:
            return False
        processed = payload.items[0].processed
        if processed.source != self.current.source or processed.source_stamp != self.current.source_stamp:
            return False
        saved = load_sidecar(processed.source.sidecar_path, expected_source=processed.source_stamp)
        if saved.status != SidecarStatus.VALID:
            return False
        previous_key = native_key(self.current)
        previous_window = deepcopy(self.current.state.floating_window)
        self.current.state = processed.state
        self.current.sidecar = saved
        self._state_dirty = False
        self._state_dirty_can_create_sidecar = False
        self._state_save_error = None
        self._sync_vars_from_current()
        self._render_status()
        if (self._native_deferred or native_key(self.current) != previous_key
                or self.current.state.floating_window != previous_window):
            self._refresh_preview()
        elif self._native_cache is None or self._native_cache[0] != native_key(self.current):
            self._request_native_preview()
        return True

    def _finish_worker_cancelled(self, payload=None) -> None:
        kind = self._finish_busy_common()
        if kind == 'folder_settings' and payload is not None:
            from .folder_dialog import finish_folder_settings
            finish_folder_settings(self, payload)
            return
        if kind == "load":
            self._restore_load_rollback()
        elif kind == "batch" and self.source_index is None and self.sources:
            self._load_source_index(self._batch_return_index(), inherit_look=True)
        elif kind in {"batch", "save", "analysis"} and self.current is not None:
            # Resume a result completed during work, or request the latest
            # state again if its render was interrupted by the busy period.
            self._refresh_preview()
            self._render_status()
        messagebox.showinfo(APP_NAME, self._t("processing_cancelled"))

    def _finish_worker_error(self, payload: Any) -> None:
        kind = self._finish_busy_common()
        log_failure('Worker '+str(kind), payload.get('exception') if isinstance(payload, dict) else payload,
                    detail=payload.get('traceback', '') if isinstance(payload, dict) else '')
        if kind == 'folder_settings':
            dialog = getattr(self, '_folder_dialog', None)
            if dialog is not None:
                dialog.destroy(); self._folder_dialog = None
        if kind == "load":
            self._restore_load_rollback()
        elif kind == "batch" and self.source_index is None and self.sources:
            self._load_source_index(self._batch_return_index(), inherit_look=True)
        elif kind in {"batch", "save", "analysis"} and self.current is not None:
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
    def _shortcut_handler(self, callback):
        def dispatch(event):
            # Let Tk's entry bindings edit text without also changing the image.
            widget = getattr(event, "widget", None)
            try:
                if (getattr(event, 'keysym', '') not in {'F1', 'F11'}
                        and widget.winfo_class() in {"Entry", "TEntry", "TCombobox", "Text", "Spinbox", "TSpinbox"}
                        and widget.cget("state") != "disabled"):
                    return None
            except (AttributeError, tk.TclError):
                pass
            key = getattr(event, 'keysym', '').lower()
            if self._geometry_draft is not None and key and key not in {
                'a', 'g', 'h', 'r', 'x', 'f1', 'f11', 'escape', 'return', 'kp_enter',
                'left', 'right', 'up', 'down',
            }:
                return "break"
            if key in {'f1', 'f11'}:
                self._release_inline_editor_focus()
            return callback(event)
        return dispatch

    def _bind_shortcuts(self) -> None:
        self.bind("<ButtonPress>", self._on_control_pointer, add="+")
        self.bind("<MouseWheel>", self._on_control_pointer, add="+")
        self.bind("<FocusOut>", self._on_keyboard_focus_out, add="+")
        self.bind("<Unmap>", self._on_keyboard_unmap, add="+")
        bind_all = lambda sequence, callback: self.bind_all(sequence, self._shortcut_handler(callback))
        bind = lambda sequence, callback: self.bind(sequence, self._shortcut_handler(callback))
        bind_all("<F11>", self._on_f11)
        bind_all("<KeyRelease-F11>", lambda e: self._release_shortcut_key("f11"))
        bind("<Escape>", self._on_escape)
        bind("<Prior>", self.previous_source)
        bind("<Next>", self.next_source)
        bind_all("<space>", self.start_processing)
        bind_all("<Return>", self.save_current_result)
        bind_all("<KP_Enter>", self.save_current_result)
        bind_all("<Control-r>", self._on_ctrl_r)
        bind_all("<Control-R>", self._on_ctrl_r)
        bind_all("<a>", self._on_a)
        bind_all("<A>", self._on_a)
        bind_all("<KeyRelease-a>", lambda e: self._release_shortcut_key("a"))
        bind_all("<KeyRelease-A>", lambda e: self._release_shortcut_key("a"))
        for key in ('c', 'C'):
            bind(f'<KeyPress-{key}>', self._on_look_key_press)
            bind(f'<KeyRelease-{key}>', self._on_look_key_release)
        for key in ('h', 'H'):
            bind_all(f'<KeyPress-{key}>', self._toggle_geometry_draft)
            bind_all(f'<KeyRelease-{key}>', self._on_geometry_key_release)
        for key in ('x', 'X'):
            bind_all(f'<KeyPress-{key}>', self._on_x)
            bind_all(f'<KeyRelease-{key}>', lambda e: self._release_shortcut_key('x'))
        bind_all("<f>", self._on_f)
        bind_all("<F>", self._on_f)
        bind_all("<KeyRelease-f>", lambda e: self._release_shortcut_key("f"))
        bind_all("<KeyRelease-F>", lambda e: self._release_shortcut_key("f"))
        bind_all("<g>", self._on_g)
        bind_all("<G>", self._on_g)
        bind_all("<KeyRelease-g>", self._on_g_release)
        bind_all("<KeyRelease-G>", self._on_g_release)
        bind_all("<s>", self._on_s)
        bind_all("<S>", self._on_s)
        bind_all("<KeyRelease-s>", lambda e: self._release_shortcut_key("s"))
        bind_all("<KeyRelease-S>", lambda e: self._release_shortcut_key("s"))
        bind_all("<F1>", self._on_f1)
        bind_all("<KeyRelease-F1>", lambda e: self._release_shortcut_key("f1"))

        for key in ("z", "Z"):
            bind_all(f"<KeyPress-{key}>", self._on_detail_press)
            bind_all(f"<KeyRelease-{key}>", self._on_detail_release)
        bind_all("<KeyPress-m>", self._on_measure_press)
        bind_all("<KeyPress-M>", self._on_measure_press)
        bind_all("<KeyRelease-m>", self._on_measure_release)
        bind_all("<KeyRelease-M>", self._on_measure_release)
        for key in ("Left", "Right", "Up", "Down"):
            bind_all(f"<KeyRelease-{key}>", self._on_arrow_release)

        bind_all("<Left>", lambda e: self._on_arrow("left", e))
        bind_all("<Right>", lambda e: self._on_arrow("right", e))
        bind_all("<Up>", lambda e: self._on_arrow("up", e))
        bind_all("<Down>", lambda e: self._on_arrow("down", e))
        bind_all("<Alt-Left>", lambda e: self._on_alt_arrow("left", e))
        bind_all("<Alt-Right>", lambda e: self._on_alt_arrow("right", e))
        bind_all("<Alt-Up>", lambda e: self._on_alt_arrow("up", e))
        bind_all("<Alt-Down>", lambda e: self._on_alt_arrow("down", e))

        for edge, key in (("left", "l"), ("right", "r"), ("top", "t"), ("bottom", "b")):
            bind_all(f"<KeyPress-{key}>", lambda e, edge=edge: self._set_floating_key(edge, e))
            bind_all(f"<KeyPress-{key.upper()}>", lambda e, edge=edge: self._set_floating_key(edge, e))
            bind_all(f"<KeyRelease-{key}>", lambda e, edge=edge: self._clear_floating_key(edge, e))
            bind_all(f"<KeyRelease-{key.upper()}>", lambda e, edge=edge: self._clear_floating_key(edge, e))

    def _on_keyboard_focus_out(self, _event=None) -> None:
        # Focus events also occur between controls inside this window. Wait
        # until Tk has assigned the next focus before deciding whether it left.
        if self._keyboard_focus_after_id is None:
            self._keyboard_focus_after_id = self.after_idle(self._reset_keyboard_if_unfocused)

    def _reset_keyboard_if_unfocused(self) -> None:
        self._keyboard_focus_after_id = None
        try:
            focused = self.focus_get()
            if focused is not None and focused.winfo_toplevel() is self:
                return
        except tk.TclError:
            pass
        self._reset_keyboard_modes()

    def _on_keyboard_unmap(self, event) -> None:
        if event.widget is self:
            self._reset_keyboard_modes()

    def _reset_keyboard_modes(self) -> None:
        """Forget held keys whose release may have happened in another window."""
        if self._keyboard_focus_after_id is not None:
            self.after_cancel(self._keyboard_focus_after_id)
            self._keyboard_focus_after_id = None
        self._end_detail_preview()
        for timer in self._mode_release_ids.values():
            self.after_cancel(timer)
        self._mode_release_ids.clear()
        for timer in self._detail_arrow_releases.values():
            self.after_cancel(timer)
        self._detail_arrow_releases.clear()
        self._detail_arrows_down.clear()
        self._detail_blocked_arrows.clear()
        self._floating_key_edge = None
        self._g_key_down = False
        self._shortcut_keys_down.clear()
        was_measuring = self.measure_cross_active
        self.measure_cross_active = False
        self._stop_measure_repeat()
        if was_measuring:
            if self.preview_mode.get() == "Kreuzblick":
                self._build_preview_anaglyph()
            else:
                self._update_preview_display()

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
        if self._geometry_draft is not None:
            return self._step_geometry_draft(direction)
        if 'c' in getattr(self, '_shortcut_keys_down', ()):
            self._look_key_used = True
            pending = self._detail_arrow_releases.pop(direction, None)
            if pending is not None:
                self.after_cancel(pending)
            self._detail_arrows_down.add(direction)
            if direction in {'left', 'right'}:
                self._cycle_look(-1 if direction == 'left' else 1)
            elif self._step_look_strength(1 if direction == 'up' else -1):
                self._show_look_notice()
            return 'break'
        if self._handle_detail_arrow(direction):
            return "break"
        if self._handle_measure_arrow(direction):
            return "break"
        if self._floating_key_edge is not None:
            self._detail_arrows_down.add(direction)
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
        if self._geometry_draft is not None:
            return "break"
        if self._handle_detail_arrow(direction):
            return "break"
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
        if self._geometry_draft is not None:
            self._geometry_draft.adjustment = GeometryAdjustment()
            self._refresh_preview()
        else:
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

    def _on_look_key_press(self, event=None):
        if self._is_ctrl(event) or self._is_alt(event):
            return None
        if self.current is None or self.busy_state != 'idle' or self.look_menu.popup is not None:
            return 'break'
        self._cancel_mode_release('look')
        if self._claim_shortcut_key('c', event):
            self._look_key_used = False
        return 'break'

    def _on_look_key_release(self, _event=None):
        if 'c' not in self._shortcut_keys_down:
            return None

        def released():
            self._release_shortcut_key('c')
            if self._look_key_used:
                self._block_mode_arrows()
            elif self.current is not None and self.busy_state == 'idle':
                self.look_checkbox.toggle()
                self._show_look_notice()

        self._release_key_mode('look', released)
        return 'break'

    def _on_a(self, event=None):
        if self.busy_state != "idle" or not self._claim_shortcut_key("a", event):
            return "break"
        modes = ("Farbig", "Graustufen", "Kreuzblick")
        self.preview_mode.set(modes[(modes.index(self.preview_mode.get()) + 1) % len(modes)])
        self._on_preview_mode_changed()
        return "break"

    def _on_x(self, event=None):
        if self.busy_state == 'idle' and self._claim_shortcut_key('x', event):
            mode = self._last_anaglyph_preview_mode if self.preview_mode.get() == 'Kreuzblick' else 'Kreuzblick'
            self.preview_mode.set(mode)
            self._on_preview_mode_changed()
        return 'break'

    def _on_f(self, event=None):
        if self.busy_state != "idle" or not self._claim_shortcut_key("f", event):
            return "break"
        return self._on_favorite_clicked(event)

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
        self._cancel_mode_release(edge)
        if self._is_ctrl(event):
            if edge == "right":
                return self._on_ctrl_r(event)
            return "break"
        if self._geometry_draft is None and self.busy_state == "idle" and self.current is not None:
            self._floating_key_edge = edge
        return "break"

    def _clear_floating_key(self, edge: str, _event=None):
        def released():
            if self._floating_key_edge == edge:
                self._floating_key_edge = None
                self._block_mode_arrows()
        self._release_key_mode(edge, released)
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
        self._cancel_mode_release("measure")
        if not self._measure_can_run():
            return "break"
        if not self.measure_cross_active:
            self.measure_cross_active = True
            if self.preview_mode.get() == "Kreuzblick":
                self._build_preview_anaglyph()
            else:
                self._update_preview_display()
        return "break"

    def _on_measure_release(self, _event=None):
        self._release_key_mode("measure", self._end_measure_preview)
        return "break"

    def _end_measure_preview(self):
        if self.measure_cross_active:
            self.measure_cross_active = False
            self._block_mode_arrows()
            self._stop_measure_repeat()
            if self.preview_mode.get() == "Kreuzblick":
                self._build_preview_anaglyph()
            else:
                self._update_preview_display()
        return "break"

    def _on_arrow_release(self, _event=None):
        direction = getattr(_event, 'keysym', '').lower()
        self._detail_arrow_release(direction)
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
        return pan_speed(held_seconds)

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
        self._detail_arrows_down.add(direction)
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
        self._schedule_titlebar_restore()
        return "break"

    def _schedule_titlebar_restore(self) -> None:
        if sys.platform != "win32":
            return
        if self._titlebar_restore_job is not None:
            self.after_cancel(self._titlebar_restore_job)
            self._titlebar_restore_job = None
        if not self.fullscreen:
            # Tk restores its native window frame asynchronously. Reapply the
            # dark attribute after that transition without hiding/refocusing it.
            self._titlebar_restore_job = self.after(100, self._restore_titlebar)

    def _restore_titlebar(self) -> None:
        from .theme import restore_dark_titlebar
        self._titlebar_restore_job = None
        if not self.fullscreen and self.winfo_exists():
            restore_dark_titlebar(self)

    def _on_escape(self, _event=None):
        menu = getattr(self, 'look_menu', None)
        if menu is not None and menu.popup is not None:
            menu.close_popup()
            return 'break'
        menu = getattr(self, '_view_context_menu', None)
        if menu is not None and menu.winfo_exists() and menu.winfo_ismapped():
            menu.unpost()
            return 'break'
        if self._shortcut_help_window is not None and self._shortcut_help_window.winfo_exists():
            self._close_shortcuts_help()
            return "break"
        if self._discard_geometry_draft():
            return "break"
        tool = getattr(self, '_measure_tool_var', None)
        if tool is not None and tool.get():
            self._end_point_measurement()
            self._update_preview_display()
            return 'break'
        view = getattr(self, '_inspection_view', None)
        if view is not None and view.active:
            return self._fit_inspection()
        if self.fullscreen:
            self.toggle_fullscreen()
        return "break"

    def _on_f1(self, event=None):
        if self.busy_state != "idle" or not self._claim_shortcut_key("f1", event):
            return "break"
        return self.show_shortcuts_help(event)

    def show_shortcuts_help(self, _event=None):
        if self.busy_state != 'idle':
            return 'break'
        if self._shortcut_help_window is not None and self._shortcut_help_window.winfo_exists():
            self._close_shortcuts_help()
            return 'break'
        self.look_menu.close_popup()
        from .controls_guide import ControlsGuide
        self._shortcut_help_window = ControlsGuide(self)
        return 'break'

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
        if not self._commit_sbs_suffix(show_error=True):
            return
        if not self._flush_state_save():
            if not messagebox.askyesno(APP_NAME, self._t('close_unsaved', text=self._state_save_error)):
                return
        self._cancel_disparity_refresh()
        self.worker.cancel_all()
        self._native_worker.cancel_all()
        self._persist_settings()
        self.destroy()

    def destroy(self):
        # A running decoder can still hold a source file open on Windows.
        self._drop_prefetch()
        self._prefetch_pool.shutdown(wait=True, cancel_futures=True)
        super().destroy()


    def report_callback_exception(self, exc_type, exc, tb):
        log_failure("Tk callback", exc, detail="".join(traceback.format_exception(exc_type, exc, tb)))
        super().report_callback_exception(exc_type, exc, tb)


def run() -> None:
    try:
        import cv2

        cv2.setNumThreads(min(cv2.getNumThreads(), 4 if sys.platform == 'win32' else 8))
        app = StereoFineApp()
        app.mainloop()
    except Exception as exc:
        log_failure("Program startup or main loop", exc, detail=traceback.format_exc())
        raise


