"""Coalesced native rendering and momentary pixel-for-pixel inspection.

One running job and one cached display pair bound memory independently of key
repeat. Jobs own their state copy and never touch Tk or the current sidecar.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import queue

import customtkinter as ctk
import numpy as np
from PIL import Image

from .anaglyph import make_anaglyph
from .color_profiles import transform_rgb
from .inputs import master_to_uint8
from .preview import draw_grid_overlay, draw_measure_cross_overlay
from .render import _stable_digest, render_final_pair
from .worker import WorkerManager, WorkerMessageKind

DETAIL_STEP_PX = 32


def native_key(session):
    state = session.state
    return (id(session), _stable_digest({
        'input': asdict(state.input_transform),
        'correction': state.alignment.correction,
        'x': state.effective_offset_x_px, 'y': state.effective_offset_y_px,
        'framing': asdict(state.framing),
        'color': (state.color.enabled, state.color.strength),
        'window': asdict(state.floating_window),
    }))


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
        self._native_worker = WorkerManager()
        self._native_job_id = None
        self._native_requested_key = None
        self._native_cache = None
        self._native_after_id = None
        self._native_poll_id = None
        self._native_failed_key = None
        self._native_running_key = None

    def destroy(self):
        self._native_worker.cancel_all()
        for timer in [self._native_after_id, self._native_poll_id, self._detail_release_id,
                      *self._detail_arrow_releases.values()]:
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
        if self._native_cache is not None and self._native_cache[0] == key:
            self._apply_native_preview()
            return
        self._native_requested_key = key
        if self._native_after_id is not None:
            self.after_cancel(self._native_after_id)
        self._native_after_id = self.after(0 if immediate else 180, self._start_native_preview)

    def _start_native_preview(self):
        self._native_after_id = None
        if (self.current is None or self.busy_state != 'idle' or self._native_job_id
                or not (self.detail_active or self.current.state.color.enabled)):
            return
        key = native_key(self.current)
        if key == self._native_failed_key:
            return
        loaded, state = self.current.loaded_pair, deepcopy(self.current.state)

        def render(token, _progress):
            left, right, _ = render_final_pair(loaded, state)
            token.raise_if_cancelled()
            left = master_to_uint8(transform_rgb(left, loaded.icc_profile))
            right = master_to_uint8(transform_rgb(right, loaded.icc_profile))
            return key, left, right, state.color

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
                    key, left, right, color = message.payload
                    if self.current is not None and self.busy_state == 'idle' and key == native_key(self.current):
                        self._native_cache = (key, left, right)
                        self.current.state.color = color
                        self._apply_native_preview()
                elif message.kind == WorkerMessageKind.ERROR:
                    self._native_failed_key = self._native_running_key
                    if self.current is not None and self._native_running_key == native_key(self.current):
                        exc = message.payload['exception']
                        self.preview_label.configure(text=self._t('preview_error', text=str(exc)), image=None)
        except queue.Empty:
            pass
        if self._native_job_id:
            self._native_poll_id = self.after(30, self._poll_native_preview)
        elif self.current is not None and (self.detail_active or self.current.state.color.enabled):
            key = native_key(self.current)
            if self._native_cache is None or self._native_cache[0] != key:
                self._start_native_preview()

    def _apply_native_preview(self):
        if (self.current is None or self._native_cache is None
                or self._native_cache[0] != native_key(self.current)):
            return False
        if self.detail_active:
            self._show_detail_preview()
        else:
            _, left, right = self._native_cache
            maxw, maxh = self._preview_bounds()
            scale = min(1.0, 1600 / left.shape[1], 1000 / left.shape[0],
                        maxw / left.shape[1], maxh / left.shape[0])
            size = (max(1, round(left.shape[1] * scale)), max(1, round(left.shape[0] * scale)))
            self._preview_left_current = np.asarray(Image.fromarray(left).resize(size, Image.Resampling.LANCZOS))
            self._preview_right_current = np.asarray(Image.fromarray(right).resize(size, Image.Resampling.LANCZOS))
            self._preview_pair_shape = size
            self._build_preview_anaglyph()
        return True

    def _show_detail_preview(self):
        if (not self.detail_active or self._native_cache is None or self.current is None
                or self._native_cache[0] != native_key(self.current)):
            return
        _, left, right = self._native_cache
        maxw, maxh = self._preview_bounds()  # physical Tk pixels
        mode = self._effective_preview_mode()
        eye_width = maxw // 2 if mode == 'Kreuzblick' else maxw
        box, self._detail_center = detail_box(left.shape, (eye_width, maxh), self._detail_center)
        x, y, x1, y1 = box
        a, b = left[y:y1, x:x1], right[y:y1, x:x1]
        if mode == 'Kreuzblick':
            eyes = [Image.fromarray(b), Image.fromarray(a)]
            if not self.measure_cross_active and self.grid_mode.get() != 'Aus':
                eyes = [draw_grid_overlay(eye, self.grid_spacing.get(), self.grid_mode.get(),
                                         reference_size=(left.shape[1], left.shape[0]), origin=(x, y)) for eye in eyes]
            image = Image.fromarray(np.concatenate([np.asarray(eye) for eye in eyes], axis=1))
        else:
            image = Image.fromarray(make_anaglyph(a, b, gray=mode == 'Graustufen'))
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
            if self._native_cache is not None and self._detail_center is not None:
                x, y = self._detail_center
                dx, dy = {'left': (-1, 0), 'right': (1, 0), 'up': (0, -1), 'down': (0, 1)}[direction]
                self._detail_center = (x + dx * DETAIL_STEP_PX, y + dy * DETAIL_STEP_PX)
                self._show_detail_preview()
            return True
        return direction in self._detail_blocked_arrows
