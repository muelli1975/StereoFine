"""Keyboard geometry draft shown in the existing stereo preview."""
from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageDraw
import numpy as np

from .alignment import resize_pair_for_preview, warp_pair_symmetric
from .inputs import master_to_uint8
from .manual_geometry import GeometryAdjustment
from .native_preview import preview_image
from .preview_render import PreviewBasePair, PreviewPair, render_preview_from_base, scale_correction_for_preview
from .render import _oriented_pair
from .view_controls import overlay_font, overlay_text


@dataclass
class GeometryDraft:
    left: np.ndarray
    right: np.ndarray
    scale: float
    aspect: float
    adjustment: GeometryAdjustment
    preview: PreviewPair | None = None
    image: Image.Image | None = None
    mode: str | None = None
    redraw: str | None = None


class GeometryControlsMixin:
    _geometry_draft: GeometryDraft | None = None

    def _toggle_geometry_draft(self, event=None):
        self._cancel_mode_release('geometry')
        if not self._claim_shortcut_key('h', event) or self._discard_geometry_draft():
            return 'break'
        if self.current is None or self.busy_state != 'idle' or self.look_menu.popup is not None:
            return 'break'
        self._reset_keyboard_modes()
        # Resetting the keyboard modes also clears the current H press.
        self._claim_shortcut_key('h', event)
        self._end_point_measurement()
        self._view_pan_pointer = None
        self.preview_frame.focus_set()
        left, right = _oriented_pair(self.current.loaded_pair, self.current.state)
        aspect = left.shape[1] / left.shape[0]
        left, right, scale = resize_pair_for_preview(master_to_uint8(left), master_to_uint8(right), 960, 660)
        self._geometry_draft = GeometryDraft(left, right, scale, aspect, self.current.state.geometry)
        self._update_preview_display()
        return 'break'

    def _on_geometry_key_release(self, _event=None):
        self._release_key_mode('geometry', lambda: self._release_shortcut_key('h'))
        return 'break'

    def _geometry_draft_has_changes(self):
        draft = self._geometry_draft
        return draft is not None and draft.adjustment != self.current.state.geometry

    def _step_geometry_draft(self, direction):
        draft = self._geometry_draft
        pending = self._detail_arrow_releases.pop(direction, None)
        if pending is not None:
            self.after_cancel(pending)
        self._detail_arrows_down.add(direction)
        roll, perspective = {'left': (-1, 0), 'right': (1, 0),
                             'up': (0, 1), 'down': (0, -1)}[direction]
        adjustment = draft.adjustment.step(roll, perspective)
        if adjustment != draft.adjustment:
            draft.adjustment = adjustment
            draft.preview = draft.image = None
            if draft.redraw is None:
                def update():
                    draft.redraw = None
                    self._update_preview_display()
                draft.redraw = self.after(8, update)
        return 'break'

    def _take_geometry_draft(self):
        draft = self._geometry_draft
        if draft is not None:
            if draft.redraw is not None:
                self.after_cancel(draft.redraw)
            self._block_mode_arrows()
            self._geometry_draft = None
        return draft

    def _discard_geometry_draft(self):
        if self._take_geometry_draft() is None:
            return False
        self._refresh_preview()
        return True

    def _commit_geometry_draft(self):
        draft = self._geometry_draft
        if self.busy_state != 'idle' or not self._flush_state_save(explicit=True):
            return 'break'
        self._take_geometry_draft()
        if draft.adjustment == self.current.state.geometry:
            self._refresh_preview()
        else:
            self._start_single_analysis(geometry=draft.adjustment)
        return 'break'

    def _geometry_draft_image(self, draft):
        mode = self._effective_preview_mode()
        if draft.preview is None:
            state = self.current.state
            correction = scale_correction_for_preview(
                state.alignment.correction if state.alignment.valid else None, draft.scale)
            left, right = warp_pair_symmetric(draft.left, draft.right, correction,
                                              geometry=draft.adjustment, preview=True)
            base = PreviewBasePair(left, right, draft.scale, draft.aspect, icc_profile=self.current.loaded_pair.icc_profile)
            draft.preview = render_preview_from_base(base, state)
        if draft.image is None or draft.mode != mode:
            draft.image = preview_image(draft.preview.left, draft.preview.right, mode)
            draft.mode = mode
        return draft.image

    def _decorate_geometry_draft(self, image, draft):
        roll = f'{draft.adjustment.roll_tenths / 10:+.1f}'
        if self.settings.language == 'de':
            roll = roll.replace('.', ',')
        label = self._t('geometry_notice', roll=roll, perspective=f'{draft.adjustment.perspective:+d}')
        image = image.copy()
        size = max(11, min(16, image.width // 24))
        font = overlay_font(size)
        draw = ImageDraw.Draw(image, 'RGBA')
        overlay_text(draw, (10, 8), label, font)
        hints = (self._t('geometry_apply_hint'), self._t('geometry_discard_hint'))
        hint = ' · '.join(hints)
        if draw.textlength(hint, font=font) > image.width - 24:
            hint = '\n'.join(hints)
        overlay_text(draw, (10, size + 12), hint, font)
        return image
