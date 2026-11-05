"""Coalesced native rendering and momentary pixel-for-pixel inspection.

One running job and one cached display pair bound memory independently of key
repeat. Jobs own their state copy and never touch Tk or the current sidecar.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import queue
import time

import customtkinter as ctk
import numpy as np
from PIL import Image

from .anaglyph import make_anaglyph
from .color_profiles import transform_rgb
from .inputs import master_to_uint8
from .geometry import apply_floating_window_masks
from .preview import draw_grid_overlay, draw_measure_cross_overlay
from .render import _stable_digest, render_final_pair, match_final_pair_color
from .state import reproducible_alignment_correction
from .worker import WorkerManager, WorkerMessageKind

MEASURE_REPEAT_MS = 16
MEASURE_HOLD_DELAY_MS = 200
MEASURE_START_SPEED_PX_PER_SEC = 320.0
MEASURE_MAX_SPEED_PX_PER_SEC = 900.0
MEASURE_ACCEL_TIME_SEC = 0.55
MEASURE_MAX_DT_SEC = 0.050


def pan_speed(held_seconds):
    t = max(0.0, min(1.0, held_seconds / MEASURE_ACCEL_TIME_SEC))
    t = t * t * (3.0 - 2.0 * t)
    return MEASURE_START_SPEED_PX_PER_SEC + (MEASURE_MAX_SPEED_PX_PER_SEC - MEASURE_START_SPEED_PX_PER_SEC) * t


def native_geometry_key(session):
    state = session.state
    return (id(session), _stable_digest({
        'input': asdict(state.input_transform),
        # Fresh analysis also keeps diagnostics that .sfin deliberately drops.
        # Cache identity must use the same reproducible geometry as the sidecar;
        # otherwise adopting an unchanged export discards the fitted master view.
        'correction': reproducible_alignment_correction(state.alignment.correction),
        'x': state.effective_offset_x_px, 'y': state.effective_offset_y_px,
        'framing': asdict(state.framing),
    }))


def native_key(session):
    return (native_geometry_key(session), session.state.color.enabled, session.state.color.strength)


def fit_display_pair(left, right, bounds):
    scale = min(1.0, 1600 / left.shape[1], 1000 / left.shape[0],
                bounds[0] / left.shape[1], bounds[1] / left.shape[0])
    size = (max(1, round(left.shape[1] * scale)), max(1, round(left.shape[0] * scale)))
    return tuple(np.asarray(Image.fromarray(eye).resize(size, Image.Resampling.LANCZOS))
                 for eye in (left, right))


def detail_texture_key(key, window, mode):
    return key, tuple(asdict(window).items()), mode


def prepare_detail_texture(key, left, right, window, mode, token):
    token.raise_if_cancelled()
    a, b = apply_floating_window_masks(left, right, window.left_permille,
        window.right_permille, window.top_permille, window.bottom_permille)
    pixels = (np.concatenate([b, a], axis=1) if mode == 'Kreuzblick' else
              make_anaglyph(a, b, gray=mode == 'Graustufen'))
    token.raise_if_cancelled()
    return detail_texture_key(key, window, mode), Image.fromarray(pixels)


def prepare_native_preview(loaded, state, key, bounds, token, mode='Farbig'):
    """Prepare both fitted views from one master crop, retaining one native pair.

    Only the small fitted variants are kept for instant colour toggles. Native
    pixels and colour fitting retain the full working depth and ICC conversion.
    """
    left, right, _ = render_final_pair(loaded, state, apply_color=False, apply_floating_window=False)
    token.raise_if_cancelled()
    plain = tuple(master_to_uint8(transform_rgb(eye, loaded.icc_profile)) for eye in (left, right))
    plain_fit = fit_display_pair(*plain, bounds)
    native = plain if not state.color.enabled else None
    del plain
    left, right, _ = match_final_pair_color(left, right, state)
    token.raise_if_cancelled()
    matched = tuple(master_to_uint8(transform_rgb(eye, loaded.icc_profile)) for eye in (left, right))
    matched_fit = fit_display_pair(*matched, bounds)
    if state.color.enabled:
        native = matched
    token.raise_if_cancelled()
    try:
        texture = prepare_detail_texture(key, *native, state.floating_window, mode, token)
    except MemoryError:
        # This cache is an acceleration, not a requirement for displaying or
        # exporting the native pair on machines with little free memory.
        texture = None
    views = (key[0], state.color.strength, {False: plain_fit, True: matched_fit}, state.color, bounds, texture)
    return key, *native, state.color, views


def detail_box(shape, bounds, center):
    height, width = shape[:2]
    w, h = min(width, max(1, int(bounds[0]))), min(height, max(1, int(bounds[1])))
    cx, cy = center if center is not None else (width / 2, height / 2)
    x = max(0, min(width - w, round(cx - w / 2)))
    y = max(0, min(height - h, round(cy - h / 2)))
    return (x, y, x + w, y + h), (x + w / 2, y + h / 2)


class NativePreviewMixin:
    def _init_native_preview(self):
        self.detail_active = False
        self._detail_center = None
        self._detail_session_id = None
        self._detail_arrows_down = set()
        self._detail_blocked_arrows = set()
        self._detail_release_id = None
        self._detail_arrow_releases = {}
        self._detail_repeat_job = None
        self._detail_repeat_direction = None
        self._detail_hold_started_at = None
        self._detail_last_tick_at = None
        self._native_worker = WorkerManager()
        self._native_job_id = None
        self._native_requested_key = None
        self._native_cache = None
        self._native_fit_cache = None
        self._native_views = None
        self._native_deferred = False
        self._mode_release_ids = {}
        self._native_after_id = None
        self._native_poll_id = None
        self._native_failed_key = None
        self._native_running_key = None
        self._held_preview_signature = None
        self._detail_texture_cache = None
        self._detail_texture_worker = WorkerManager()
        self._detail_texture_job_id = None
        self._detail_texture_after_id = None
        self._detail_texture_poll_id = None
        self._detail_texture_running_key = None
        self._detail_texture_failed_key = None

    def destroy(self):
        self._native_worker.cancel_all()
        self._detail_texture_worker.cancel_all()
        for timer in [self._native_after_id, self._native_poll_id, self._detail_release_id, self._detail_repeat_job,
                      self._detail_texture_after_id, self._detail_texture_poll_id,
                      *self._detail_arrow_releases.values(), *self._mode_release_ids.values()]:
            if timer is not None:
                try:
                    self.after_cancel(timer)
                except Exception:
                    pass
        super().destroy()

    def _request_native_preview(self, *, immediate=False):
        if self.current is None or self.busy_state != 'idle':
            return
        key = native_key(self.current)
        if self._detail_session_id != id(self.current):
            self._detail_session_id = id(self.current)
            self._detail_center = None
            self._native_cache = None
            self._native_views = None
        if (self._native_cache is not None and self._native_cache[0] == key
                and not self._native_views_need_resize()):
            self._apply_native_preview()
            return
        self._native_requested_key = key
        if self._native_after_id is not None:
            self.after_cancel(self._native_after_id)
        self._native_after_id = self.after(0 if immediate else 180, self._start_native_preview)

    def _start_native_preview(self):
        self._native_after_id = None
        if self.current is None or self.busy_state != 'idle' or self._native_job_id:
            return
        key = native_key(self.current)
        if key == self._native_failed_key:
            return
        loaded, state = self.current.loaded_pair, deepcopy(self.current.state)
        bounds = self._preview_bounds()
        mode = self._effective_preview_mode()

        def render(token, _progress):
            return prepare_native_preview(loaded, state, key, bounds, token, mode)

        self._native_running_key = key
        self._native_job_id = self._native_worker.start(render, name='StereoFine-native-preview').job_id
        if self._native_poll_id is None:
            self._native_poll_id = self.after(30, self._poll_native_preview)

    def _poll_native_preview(self):
        self._native_poll_id = None
        try:
            while True:
                message = self._native_worker.messages.get_nowait()
                if message.job_id != self._native_job_id:
                    continue
                if message.kind == WorkerMessageKind.STARTED:
                    continue
                self._native_job_id = None
                if message.kind == WorkerMessageKind.RESULT:
                    key, left, right, color, views = message.payload
                    if self.current is not None and key[0] == native_geometry_key(self.current):
                        self._native_cache = (key, left, right)
                        self._native_views = views
                        self._native_failed_key = None
                        self._native_deferred = self.busy_state != 'idle'
                        if not self._native_deferred:
                            self._apply_native_preview()
                elif message.kind == WorkerMessageKind.ERROR:
                    self._native_failed_key = self._native_running_key
                    if (self.current is not None and self._native_running_key == native_key(self.current)
                            and not self._preview_is_held()):
                        exc = message.payload['exception']
                        self.preview_label.configure(text=self._t('preview_error', text=str(exc)), image=None)
        except queue.Empty:
            pass
        if self._native_job_id:
            self._native_poll_id = self.after(30, self._poll_native_preview)
        elif self.current is not None and self.busy_state == 'idle':
            key = native_key(self.current)
            if (not self._has_fitted_native_view() or self._native_views_need_resize()
                    or self._native_cache is None or self._native_cache[0] != key):
                self._start_native_preview()

    def _has_fitted_native_view(self):
        return (self.current is not None and self._native_views is not None
                and self._native_views[:2] == (native_geometry_key(self.current), self.current.state.color.strength))

    def _native_views_need_resize(self):
        return self._has_fitted_native_view() and self._native_views[4] != self._preview_bounds()

    def _preview_signature(self):
        return (native_key(self.current), tuple(asdict(self.current.state.floating_window).items()),
                self._preview_bounds(), self.detail_active,
                self._detail_center if self.detail_active else None)

    def _hold_current_preview(self):
        if self.current is not None and getattr(self, '_preview_pil', None) is not None:
            self._held_preview_signature = self._preview_signature()

    def _preview_is_held(self):
        if self._held_preview_signature is not None:
            if self.current is not None and self._held_preview_signature == self._preview_signature():
                return True
            self._held_preview_signature = None
        return False

    def _apply_native_preview(self):
        if self.current is None:
            return False
        if self._preview_is_held():
            return True
        fitted = self._has_fitted_native_view()
        native = self._native_cache is not None and self._native_cache[0] == native_key(self.current)
        if not fitted and not native:
            return False
        self._native_deferred = False
        if fitted:
            if len(self._native_views) > 5:
                texture = self._native_views[5]
                if texture is not None and texture[0] == self._detail_texture_signature():
                    self._detail_texture_cache = texture
            color = deepcopy(self._native_views[3])
            color.enabled = self.current.state.color.enabled
            color.strength = self.current.state.color.strength
            self.current.state.color = color
        if self.detail_active:
            if not native:
                self._request_native_preview(immediate=True)
                return True
            self._show_detail_preview()
        else:
            if fitted and (not native or not self._native_views_need_resize()):
                a, b = self._native_views[2][self.current.state.color.enabled]
                self._preview_left_current, self._preview_right_current = self._mask_preview_pair(a, b)
                self._preview_pair_shape = (a.shape[1], a.shape[0])
                self._build_preview_anaglyph()
                return True
            _, left, right = self._native_cache
            maxw, maxh = self._preview_bounds()
            scale = min(1.0, 1600 / left.shape[1], 1000 / left.shape[0],
                        maxw / left.shape[1], maxh / left.shape[0])
            size = (max(1, round(left.shape[1] * scale)), max(1, round(left.shape[0] * scale)))
            fit_key = (self._native_cache[0], size)
            if self._native_fit_cache is None or self._native_fit_cache[0] != fit_key:
                self._native_fit_cache = (fit_key, *[
                    np.asarray(Image.fromarray(eye).resize(size, Image.Resampling.LANCZOS))
                    for eye in (left, right)])
            _, a, b = self._native_fit_cache
            self._preview_left_current, self._preview_right_current = self._mask_preview_pair(a, b)
            self._preview_pair_shape = size
            self._build_preview_anaglyph()
        return True

    def _cancel_mode_release(self, mode):
        pending = self._mode_release_ids.pop(mode, None)
        if pending is not None:
            self.after_cancel(pending)

    def _block_mode_arrows(self):
        self._detail_blocked_arrows.update(self._detail_arrows_down)
        self._detail_arrows_down.clear()

    def _release_key_mode(self, mode, callback):
        self._cancel_mode_release(mode)
        def released():
            self._mode_release_ids.pop(mode, None)
            callback()
        self._mode_release_ids[mode] = self.after_idle(released)

    def _mask_preview_pair(self, left, right, **kwargs):
        fw = self.current.state.floating_window
        return apply_floating_window_masks(left, right, fw.left_permille, fw.right_permille,
                                           fw.top_permille, fw.bottom_permille, **kwargs)

    def _detail_texture_signature(self):
        return detail_texture_key(native_key(self.current), self.current.state.floating_window,
                                  self._effective_preview_mode())

    def _request_detail_texture(self):
        if (self._detail_texture_after_id is None and self._detail_texture_job_id is None
                and self._detail_texture_failed_key != self._detail_texture_signature()):
            self._detail_texture_after_id = self.after(0, self._start_detail_texture)

    def _start_detail_texture(self):
        self._detail_texture_after_id = None
        if (not self.detail_active or self.current is None or self._native_cache is None
                or self._native_cache[0] != native_key(self.current) or self._detail_texture_job_id):
            return
        key, left, right = self._native_cache
        window = deepcopy(self.current.state.floating_window)
        mode = self._effective_preview_mode()
        self._detail_texture_running_key = detail_texture_key(key, window, mode)
        def render(token, _progress):
            return prepare_detail_texture(key, left, right, window, mode, token)
        self._detail_texture_job_id = self._detail_texture_worker.start(render,
            name='StereoFine-detail-texture').job_id
        self._detail_texture_poll_id = self.after(16, self._poll_detail_texture)

    def _poll_detail_texture(self):
        self._detail_texture_poll_id = None
        try:
            while True:
                message = self._detail_texture_worker.messages.get_nowait()
                if message.job_id != self._detail_texture_job_id or message.kind == WorkerMessageKind.STARTED:
                    continue
                self._detail_texture_job_id = None
                if message.kind == WorkerMessageKind.RESULT and self.current is not None:
                    if message.payload[0] == self._detail_texture_signature():
                        self._detail_texture_cache = message.payload
                        if self.detail_active:
                            self._show_detail_preview()
                elif message.kind == WorkerMessageKind.ERROR:
                    self._detail_texture_failed_key = self._detail_texture_running_key
        except queue.Empty:
            pass
        if self._detail_texture_job_id:
            self._detail_texture_poll_id = self.after(16, self._poll_detail_texture)
        elif self.detail_active and self.current is not None:
            if self._detail_texture_cache is None or self._detail_texture_cache[0] != self._detail_texture_signature():
                self._request_detail_texture()

    def _show_detail_preview(self, *, previous_center=None):
        if (not self.detail_active or self._native_cache is None or self.current is None
                or self._native_cache[0] != native_key(self.current)):
            return
        _, left, right = self._native_cache
        maxw, maxh = self._preview_bounds()  # physical Tk pixels
        mode = self._effective_preview_mode()
        eye_width = maxw // 2 if mode == 'Kreuzblick' else maxw
        box, self._detail_center = detail_box(left.shape, (eye_width, maxh), self._detail_center)
        # A pan at an image edge (or below one screen pixel) may leave the
        # visible region unchanged. Explicit refreshes still redraw overlays,
        # mode changes and resized views even at the same position.
        if previous_center is not None and box == detail_box(left.shape, (eye_width, maxh), previous_center)[0]:
            return
        x, y, x1, y1 = box
        texture = self._detail_texture_cache
        cached = texture is not None and texture[0] == self._detail_texture_signature()
        if not cached:
            self._request_detail_texture()
            a, b = left[y:y1, x:x1], right[y:y1, x:x1]
            a, b = self._mask_preview_pair(a, b, reference_size=(left.shape[1], left.shape[0]), origin=(x, y))
        if mode == 'Kreuzblick':
            eyes = ([texture[1].crop(box), texture[1].crop((x+left.shape[1], y, x1+left.shape[1], y1))]
                    if cached else [Image.fromarray(b), Image.fromarray(a)])
            if not self.measure_cross_active and self.grid_mode.get() != 'Aus':
                eyes = [draw_grid_overlay(eye, self.grid_spacing.get(), self.grid_mode.get(),
                                         reference_size=(left.shape[1], left.shape[0]), origin=(x, y)) for eye in eyes]
            image = Image.new('RGB', (eyes[0].width*2, eyes[0].height))
            image.paste(eyes[0], (0, 0)); image.paste(eyes[1], (eyes[0].width, 0))
        else:
            image = (texture[1].crop(box) if cached else
                     Image.fromarray(make_anaglyph(a, b, gray=mode == 'Graustufen')))
            if not self.measure_cross_active and self.grid_mode.get() != 'Aus':
                image = draw_grid_overlay(image, self.grid_spacing.get(), self.grid_mode.get(),
                                          reference_size=(left.shape[1], left.shape[0]), origin=(x, y))
        self._preview_display_size = image.size
        if self.measure_cross_active:
            self._clamp_measure_cross(image.size)
            image = draw_measure_cross_overlay(image, self.measure_cross_x, self.measure_cross_y,
                                               reference_width=left.shape[1])
            self._measure_display_size = image.size
        # CTkImage sizes are logical units; its backing PIL image is physical.
        # Dividing here prevents a second enlargement at 125/150/200% DPI.
        scaling = self.preview_label._get_widget_scaling()
        logical_size = (image.width / scaling, image.height / scaling)
        new_image = ctk.CTkImage(light_image=image, dark_image=image, size=logical_size)
        self.preview_label.configure(text='', image=new_image)
        self._preview_ctk_image = new_image

    def _on_detail_press(self, _event=None):
        if self._detail_release_id is not None:
            self.after_cancel(self._detail_release_id)
            self._detail_release_id = None
        if self.current is None or self.busy_state != 'idle':
            return 'break'
        if not self.detail_active:
            self.detail_active = True
            # Retry only on a fresh physical Z press. Automatic polling and
            # key repeat must not loop on a failing render.
            self._native_failed_key = None
            self._detail_texture_failed_key = None
            self._stop_measure_repeat()
            self._request_native_preview(immediate=True)
            if self._native_cache is None or self._native_cache[0] != native_key(self.current):
                self.preview_label.configure(text=self._t('detail_loading'), image=None)
                self.preview_label._label.configure(image='')
        return 'break'

    def _on_detail_release(self, _event=None):
        # X11 may insert synthetic release/press pairs during key repeat.
        if self._detail_release_id is None:
            self._detail_release_id = self.after_idle(self._end_detail_preview)
        return 'break'

    def _end_detail_preview(self):
        self._detail_release_id = None
        self._stop_detail_repeat()
        if self.detail_active:
            self.detail_active = False
            self._detail_blocked_arrows.update(self._detail_arrows_down)
            self._detail_arrows_down.clear()
            if not self._apply_native_preview():
                self._refresh_preview()

    def _detail_arrow_release(self, direction):
        if direction not in self._detail_arrows_down and direction not in self._detail_blocked_arrows:
            return
        def released():
            self._detail_arrow_releases.pop(direction, None)
            self._detail_arrows_down.discard(direction)
            self._detail_blocked_arrows.discard(direction)
            if self._detail_repeat_direction == direction:
                self._stop_detail_repeat()
        pending = self._detail_arrow_releases.pop(direction, None)
        if pending is not None:
            self.after_cancel(pending)
        self._detail_arrow_releases[direction] = self.after_idle(released)

    def _handle_detail_arrow(self, direction):
        pending = self._detail_arrow_releases.pop(direction, None)
        if pending is not None:
            self.after_cancel(pending)
        if self.detail_active:
            self._detail_arrows_down.add(direction)
            if self._detail_repeat_direction != direction:
                self._stop_detail_repeat()
                now = time.perf_counter()
                self._detail_repeat_direction = direction
                self._detail_hold_started_at = now
                self._detail_last_tick_at = now
                self._move_detail(direction, 1.)
                self._detail_repeat_job = self.after(MEASURE_REPEAT_MS, self._detail_repeat_tick)
            return True
        return direction in self._detail_blocked_arrows

    def _move_detail(self, direction, pixels):
        if not self.detail_active or self._native_cache is None or self._detail_center is None:
            return
        x, y = self._detail_center
        dx, dy = {'left': (-1, 0), 'right': (1, 0), 'up': (0, -1), 'down': (0, 1)}[direction]
        self._detail_center = (x + dx * pixels, y + dy * pixels)
        self._show_detail_preview(previous_center=(x, y))

    def _stop_detail_repeat(self):
        if self._detail_repeat_job is not None:
            self.after_cancel(self._detail_repeat_job)
        self._detail_repeat_job = None
        self._detail_repeat_direction = None
        self._detail_hold_started_at = None
        self._detail_last_tick_at = None

    def _detail_repeat_tick(self):
        self._detail_repeat_job = None
        if not self.detail_active or self._detail_repeat_direction is None:
            return
        now = time.perf_counter()
        held = max(0., now - self._detail_hold_started_at)
        delay = MEASURE_HOLD_DELAY_MS / 1000.
        if held >= delay:
            dt = max(.001, min(MEASURE_MAX_DT_SEC, now - self._detail_last_tick_at))
            self._move_detail(self._detail_repeat_direction, pan_speed(held - delay) * dt)
        self._detail_last_tick_at = now
        self._detail_repeat_job = self.after(MEASURE_REPEAT_MS, self._detail_repeat_tick)
