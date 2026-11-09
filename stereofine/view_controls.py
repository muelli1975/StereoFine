"""Mouse inspection, measured image coordinates, and preview-only overlays."""
from __future__ import annotations

from copy import deepcopy
import sys
import tkinter as tk
from functools import lru_cache
from pathlib import Path

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFont

from .endpoints import current_markers, crop_geometry
from .inspection import InspectionView, image_point, measured_deviation
from .look_controls import preview_look
from .native_preview import detail_texture_key, native_key, native_geometry_key, preview_image
from .preview import draw_grid_overlay, draw_measure_cross_overlay
from .preview_render import render_preview_from_base
from .numbers import endpoint_values
from .label_layout import place_labels


@lru_cache(maxsize=16)
def overlay_font(size):
    bundled = Path(ctk.__file__).resolve().parent/'assets/fonts/Roboto/Roboto-Regular.ttf'
    for name in (str(bundled), 'arial.ttf', 'DejaVuSans.ttf'):
        try: return ImageFont.truetype(name, size)
        except OSError: pass
    return ImageFont.load_default(size=size)


def overlay_text(draw, xy, text, font, *, fill=(255, 255, 255, 225)):
    x, y = xy
    draw.text((x+2, y+2), text, font=font, fill=(0, 0, 0, 195), stroke_width=2)
    draw.text((x, y), text, font=font, fill=fill)


class ViewControlsMixin:
    def _init_view_controls(self):
        self.show_deviation_points = ctk.BooleanVar(value=self.settings.show_deviation_points)
        self._inspection_view = InspectionView()
        self._view_source_box = None
        self._view_native_size = None
        self._view_pan_pointer = None
        self._inspection_proxy = None
        self._fit_notice_job = None
        self._fit_notice = False
        self._look_notice_job = None
        self._look_notice = False
        self._measure_tool_var = tk.BooleanVar(value=False)
        self._point_measurements = []
        self._point_measure_hover = None
        self._point_measure_geometry = None
        self._point_measure_session = None

    def _bind_view_controls(self):
        # Bind only the preview surfaces; sidebar sliders retain their own wheel.
        widgets = (self.preview_frame, self.preview_label,
                   self.preview_label._label, self.preview_label._canvas)
        pan_button, menu_button = (3, 2) if sys.platform == 'darwin' else (2, 3)
        for widget in widgets:
            widget.bind('<Control-MouseWheel>', self._on_view_wheel, add='+')
            widget.bind('<Control-Button-4>', lambda e: self._on_view_wheel(e, 1), add='+')
            widget.bind('<Control-Button-5>', lambda e: self._on_view_wheel(e, -1), add='+')
            widget.bind(f'<ButtonPress-{pan_button}>', self._on_view_pan_start, add='+')
            widget.bind(f'<B{pan_button}-Motion>', self._on_view_pan_move, add='+')
            widget.bind(f'<ButtonRelease-{pan_button}>', self._on_view_pan_end, add='+')
            widget.bind(f'<Button-{menu_button}>', self._on_view_context, add='+')
            widget.bind('<Button-1>', self._on_view_measure_click, add='+')
            widget.bind('<Double-Button-1>', self._on_view_double_click, add='+')
            widget.bind('<Motion>', self._on_view_measure_motion, add='+')
        for sequence in ('<Control-plus>', '<Control-equal>', '<Control-KP_Add>'):
            self.bind_all(sequence, self._shortcut_handler(lambda e: self._zoom_inspection(1.2)))
        for sequence in ('<Control-minus>', '<Control-KP_Subtract>'):
            self.bind_all(sequence, self._shortcut_handler(lambda e: self._zoom_inspection(1/1.2)))
        self.bind_all('<Control-0>', self._shortcut_handler(self._fit_inspection))
        for key in ('d', 'D'):
            self.bind_all(f'<KeyPress-{key}>', self._shortcut_handler(self._on_deviation_shortcut))
            self.bind_all(f'<KeyRelease-{key}>', lambda e: self._release_shortcut_key('d'))

    def _on_deviation_shortcut(self, event=None):
        if self.busy_state == 'idle' and self._claim_shortcut_key('d', event):
            self.show_deviation_points.set(not self.show_deviation_points.get())
            self._on_deviation_option_changed()
        return 'break'

    def _on_deviation_option_changed(self):
        self._persist_settings()
        self._update_preview_display()
        self._schedule_disparity_refresh()

    def _needs_endpoint_refresh(self):
        option = getattr(self, 'show_deviation_points', None)
        return bool(option is not None and option.get() and self.current is not None
                    and self.current.state.disparity.valid
                    and self.current.state.disparity.endpoints.get('version', 0) < 2)

    def _view_image_size(self):
        if self.current is None:
            return None
        if self._native_cache is not None and self._native_cache[0] == native_key(self.current):
            return self._native_cache[1].shape[1], self._native_cache[1].shape[0]
        base = self._preview_base
        if base is not None and base.master_shape is not None:
            _, _, (x, y, x1, y1) = crop_geometry(self.current.state, base.master_shape, base.original_aspect)
            return x1-x, y1-y
        return None

    def _view_viewport(self):
        w, h = self._preview_bounds()
        return (max(1, w//2), h) if self._effective_preview_mode() == 'Kreuzblick' else (w, h)

    def _event_image_position(self, event):
        size = self._preview_display_size
        if size is None:
            return None
        label = self.preview_label._label
        x = event.x_root-label.winfo_rootx()-(label.winfo_width()-size[0])/2
        y = event.y_root-label.winfo_rooty()-(label.winfo_height()-size[1])/2
        return (x, y) if 0 <= x < size[0] and 0 <= y < size[1] else None

    def _on_view_wheel(self, event, direction=None):
        if direction is None:
            direction = 1 if event.delta > 0 else -1
        return self._zoom_inspection(1.2 if direction > 0 else 1/1.2, event)

    def _zoom_inspection(self, factor, event=None):
        if self.current is None or self.busy_state != 'idle' or self.detail_active:
            return 'break'
        size = self._view_image_size()
        if size is None:
            return 'break'
        anchor = (.5, .5)
        if event is not None:
            self.preview_frame.focus_set()
            point = self._event_image_position(event)
            if point is not None:
                w, h = self._preview_display_size
                if self._effective_preview_mode() == 'Kreuzblick':
                    w = max(1, w/2)
                anchor = (point[0] % w)/w, point[1]/h
        was_active = self._inspection_view.active
        if event is not None and factor < 1 and not was_active:
            return 'break'
        self._fit_notice = False
        if not was_active and self._preview_pil is not None:
            self._inspection_proxy = (self._inspection_proxy_key(self._effective_preview_mode()), self._preview_pil)
        self._inspection_view.zoom(factor, size, self._view_viewport(), anchor)
        if was_active and not self._inspection_view.active:
            return self._fit_inspection(wheel=event is not None)
        self._update_preview_display()
        return 'break'

    def _fit_inspection(self, _event=None, *, notice=True, wheel=False):
        if self.busy_state != 'idle':
            return 'break'
        self._inspection_view.reset()
        self._view_pan_pointer = None
        if self._fit_notice_job is not None:
            self.after_cancel(self._fit_notice_job)
        self._fit_notice = bool(notice and self.current is not None)
        self._fit_notice_job = self.after(1000 if wheel else 2000, self._clear_fit_notice) if self._fit_notice else None
        if not self._apply_native_preview():
            self._refresh_preview()
        return 'break'

    def _clear_fit_notice(self):
        self._fit_notice_job = None
        self._fit_notice = False
        self._update_preview_display()

    def _show_look_notice(self):
        if self._look_notice_job is not None:
            self.after_cancel(self._look_notice_job)
        self._look_notice = True
        self._look_notice_job = self.after(2000, self._clear_look_notice)
        self._update_preview_display()

    def _look_notice_text(self):
        if not self.look_enabled.get():
            return self._t('look_notice_off')
        return self._t('look_notice', name=self.look_choice.get(), value=round(self.look_strength.get()))

    def _clear_look_notice(self):
        self._look_notice_job = None
        self._look_notice = False
        self._update_preview_display()

    def _reset_view_for_source(self):
        if not hasattr(self, '_inspection_view'):
            self._inspection_view = InspectionView()
        self._inspection_view.reset()
        self._inspection_proxy = None
        self._fit_notice = False
        if getattr(self, '_look_notice_job', None) is not None:
            self.after_cancel(self._look_notice_job)
            self._look_notice_job = None
            self._look_notice = False
        self._view_source_box = None
        self._end_point_measurement()

    def _on_view_pan_start(self, event):
        if self.busy_state == 'idle' and self._inspection_view.active and not self.detail_active:
            self.preview_frame.focus_set()
            self._view_pan_pointer = event.x_root, event.y_root
        return 'break'

    def _on_view_pan_move(self, event):
        if self._view_pan_pointer is not None and self.busy_state == 'idle':
            last = self._view_pan_pointer
            self._view_pan_pointer = event.x_root, event.y_root
            size = self._view_image_size()
            if size:
                self._inspection_view.pan(event.x_root-last[0], event.y_root-last[1], size, self._view_viewport())
                self._update_preview_display()
        return 'break'

    def _on_view_pan_end(self, _event=None):
        self._view_pan_pointer = None
        return 'break'

    def _on_view_context(self, event):
        if self.current is None or self.busy_state != 'idle':
            return 'break'
        self.preview_frame.focus_set()
        previous = getattr(self, '_view_context_menu', None)
        if previous is not None and previous.winfo_exists():
            previous.destroy()
        from customtkinter.windows.widgets.core_widget_classes import DropdownMenu
        from .theme import SECONDARY_BG, HOVER_BG, TEXT_PRIMARY, TEXT_DISABLED, GOLD_LIGHT
        menu = DropdownMenu(self, values=[], fg_color=SECONDARY_BG, hover_color=HOVER_BG,
                            text_color=TEXT_PRIMARY, font=self._font(13))
        menu.configure(disabledforeground=TEXT_DISABLED)
        self._view_context_menu = menu
        menu.add_checkbutton(label=self._t('deviation_meter'), variable=self._measure_tool_var,
                             command=self._toggle_point_measurement,
                             selectcolor=GOLD_LIGHT,
                             state='disabled' if self._effective_preview_mode() == 'Kreuzblick' else 'normal')
        menu.open(event.x_root, event.y_root)
        return 'break'

    def _toggle_point_measurement(self):
        if self._effective_preview_mode() == 'Kreuzblick':
            self._measure_tool_var.set(False)
        self._point_measurements = []
        self._point_measure_hover = None
        self._point_measure_geometry = native_geometry_key(self.current) if self.current else None
        self.preview_label.configure(cursor='crosshair' if self._measure_tool_var.get() else '')
        self._update_preview_display()

    def _end_point_measurement(self):
        if not hasattr(self, '_measure_tool_var'):
            return
        self._measure_tool_var.set(False)
        self._point_measurements = []
        self._point_measure_hover = None
        if hasattr(self, 'preview_label'):
            self.preview_label.configure(cursor='')

    def _on_view_measure_click(self, event):
        if not self._measure_tool_var.get() or self.busy_state != 'idle':
            return None
        if self._effective_preview_mode() == 'Kreuzblick':
            self._end_point_measurement()
            return 'break'
        self.preview_frame.focus_set()
        xy = self._event_image_position(event)
        if xy is None or self._view_source_box is None:
            return 'break'
        point = image_point(xy, self._preview_display_size, self._view_source_box)
        if point is not None:
            if len(self._point_measurements) == 2:
                self._point_measurements = []
            self._point_measurements.append(point)
            self._point_measure_hover = point
            self._update_preview_display()
        return 'break'

    def _on_view_double_click(self, event):
        if self.busy_state != 'idle':
            return 'break'
        if self._measure_tool_var.get():
            # Tk dispatches Double-Button instead of the second Button event.
            return self._on_view_measure_click(event)
        if self._inspection_view.active and not self.detail_active:
            return self._fit_inspection()
        return 'break'

    def _on_view_measure_motion(self, event):
        if not self._measure_tool_var.get() or len(self._point_measurements) != 1:
            return
        xy = self._event_image_position(event)
        if xy is not None and self._view_source_box is not None:
            self._point_measure_hover = image_point(xy, self._preview_display_size, self._view_source_box)
            self._update_preview_display()

    def _inspection_proxy_key(self, mode):
        state = self.current.state
        return detail_texture_key(native_key(self.current), state.floating_window, mode,
                                  preview_look(self), state.exposure)

    def _inspection_proxy_frame(self, mode):
        key = self._inspection_proxy_key(mode)
        cached = getattr(self, '_inspection_proxy', None)
        if cached is not None and cached[0] == key:
            return cached[1]
        state = self.current.state
        if self._has_fitted_native_view():
            left, right = self._native_views[2][state.color.enabled]
            left, right = self._mask_preview_pair(left, right)
        else:
            if preview_look(self) is not state.look:
                state = deepcopy(state)
                state.look = preview_look(self)
            pair = render_preview_from_base(self._ensure_preview_base(self.current), state,
                                            bounds=self._preview_bounds())
            left, right = pair.left, pair.right
        image = preview_image(left, right, mode)
        self._inspection_proxy = key, image
        return image

    def _show_inspection_preview(self):
        if self.current is None:
            return
        native = self._native_cache is not None and self._native_cache[0] == native_key(self.current)
        mode = self._effective_preview_mode()
        texture = self._detail_texture_cache
        cached = native and texture is not None and texture[0] == self._detail_texture_signature()
        if cached:
            size = self._view_image_size()
            box, display = self._inspection_view.layout(size, self._view_viewport())
            image = texture[1].copy()
        else:
            if native:
                self._request_detail_texture()
            else:
                self._request_native_preview(immediate=True)
            proxy = self._inspection_proxy_frame(mode)
            size = self._view_image_size()
            if size is None:
                return
            box, display = self._inspection_view.layout(size, self._view_viewport())
            image = self._resize_inspection_proxy(proxy, box, size, display, mode)

        self._decorate_inspection_preview(image, box, size, display, mode)

    @staticmethod
    def _resize_inspection_proxy(proxy, box, size, display, mode):
        eye_width = proxy.width // 2 if mode == 'Kreuzblick' else proxy.width
        x0, y0, x1, y1 = box
        source_box = (x0 * eye_width / size[0], y0 * proxy.height / size[1],
                      x1 * eye_width / size[0], y1 * proxy.height / size[1])
        if mode != 'Kreuzblick':
            return proxy.resize(display, Image.Resampling.BILINEAR, box=source_box)
        frame = Image.new('RGB', (display[0] * 2, display[1]))
        for eye in (0, 1):
            x = eye * eye_width
            eye_box = (source_box[0] + x, source_box[1], source_box[2] + x, source_box[3])
            frame.paste(proxy.resize(display, Image.Resampling.BILINEAR, box=eye_box), (eye * display[0], 0))
        return frame

    def _decorate_inspection_preview(self, image, box, size, display, mode):
        grid_scale = display[0]/(box[2]-box[0]), display[1]/(box[3]-box[1])
        if self.grid_mode.get() != 'Aus' and not self.measure_cross_active:
            if mode == 'Kreuzblick':
                for x in (0, display[0]):
                    eye_box = (x, 0, x+display[0], display[1])
                    eye = draw_grid_overlay(image.crop(eye_box), self.grid_spacing.get(), self.grid_mode.get(),
                        reference_size=size, origin=box[:2], scale=grid_scale)
                    image.paste(eye, eye_box)
            else:
                image = draw_grid_overlay(image, self.grid_spacing.get(), self.grid_mode.get(),
                    reference_size=size, origin=box[:2], scale=grid_scale)
        if self.measure_cross_active:
            self._clamp_measure_cross(image.size)
            image = draw_measure_cross_overlay(image, self.measure_cross_x, self.measure_cross_y,
                                               reference_width=size[0]*display[0]/(box[2]-box[0]))
            self._measure_display_size = image.size
        image = self._decorate_view(image, box, size)
        self._preview_display_size = image.size
        scaling = self.preview_label._get_widget_scaling()
        photo = ctk.CTkImage(light_image=image, dark_image=image,
                             size=(image.width/scaling, image.height/scaling))
        self.preview_label.configure(text='', image=photo)
        self._preview_ctk_image = photo

    def _decorate_view(self, image, source_box, native_size, *, detail=False):
        if (self.current is None or not hasattr(self, '_inspection_view')
                or getattr(self, 'current_job_kind', None) == 'batch'):
            return image
        self._view_source_box, self._view_native_size = source_box, native_size
        option = getattr(self, 'show_deviation_points', None)
        tool = getattr(self, '_measure_tool_var', None)
        points_on = bool(option is not None and option.get())
        tool_on = bool(tool is not None and tool.get())
        view = getattr(self, '_inspection_view', None)
        hud_on = detail or bool(view is not None and view.active) or getattr(self, '_fit_notice', False)
        look_notice = getattr(self, '_look_notice', False)
        if not points_on and not tool_on and not hud_on and not look_notice:
            return image
        scaling = self.preview_label._get_widget_scaling()
        font = overlay_font(max(14, round(16*scaling)))
        point_font = overlay_font(max(18, round(20*scaling)))
        overlay = Image.new('RGBA', image.size)
        draw = ImageDraw.Draw(overlay)
        cross = self._effective_preview_mode() == 'Kreuzblick'
        ew = image.width/2 if cross else image.width
        x0, y0, x1, y1 = source_box
        def project(point, eye=0, normalized=False):
            px, py = point
            if normalized: px, py = px*native_size[0], py*native_size[1]
            return (px-x0)/(x1-x0)*ew + eye*ew, (py-y0)/(y1-y0)*image.height
        if points_on:
            texts = endpoint_values(self.current.state, self.settings.language)
            labels = [[] for _ in range(2 if cross else 1)]
            for name, marker in current_markers(self.current.state).items():
                text = ('N' if name == 'near' else 'F') + ('?' if marker.get('tentative') else '')
                text += f' ({texts[name]})'
                positions = ([project(marker['right'], 0, True), project(marker['left'], 1, True)]
                             if cross else [project([(a+b)/2 for a,b in zip(marker['left'],marker['right'])], 0, True)])
                for eye, (px, py) in enumerate(positions):
                    if not (eye*ew <= px < (eye+1)*ew and 0 <= py < image.height): continue
                    draw.line((px-5, py, px+5, py), fill=(0,0,0,190), width=4)
                    draw.line((px, py-5, px, py+5), fill=(0,0,0,190), width=4)
                    draw.line((px-5, py, px+5, py), fill=(255,255,255,215), width=2)
                    draw.line((px, py-5, px, py+5), fill=(255,255,255,215), width=2)
                    labels[eye].append((px, py, text))
            for eye, entries in enumerate(labels):
                fitted, sizes = [], []
                for px, py, text in entries:
                    marker, value = text.split(' ', 1)
                    # Keep the normal size where it fits. In a very narrow
                    # preview split the label into two lines before shrinking.
                    for candidate, face in ((text, point_font), (marker+'\n'+value, point_font),
                                            (marker+'\n'+value, overlay_font(12)), (marker, overlay_font(12))):
                        x, y, right, bottom = draw.multiline_textbbox((0, 0), candidate, font=face)
                        if right+5 <= ew-12 and bottom+5 <= image.height-12:
                            fitted.append((px, py, candidate, face))
                            sizes.append((px, py, right+5, bottom+5))
                            break
                positions = place_labels(sizes, (eye*ew, 0, (eye+1)*ew, image.height))
                for (px, py, text, face), (rect, leader) in zip(fitted, positions):
                    tx, ty, tx1, ty1 = rect
                    if leader:
                        target = (max(tx, min(tx1, px)), max(ty, min(ty1, py)))
                        draw.line((px, py, *target), fill=(0, 0, 0, 190), width=3)
                        draw.line((px, py, *target), fill=(255, 255, 255, 190), width=1)
                    overlay_text(draw, (tx, ty), text, face)
        if tool_on:
            geometry = native_geometry_key(self.current)
            if geometry != self._point_measure_geometry:
                self._point_measurements = []
                self._point_measure_hover = None
                self._point_measure_geometry = geometry
            points = self._point_measurements
            targets = points if len(points) == 2 else points+([self._point_measure_hover] if points and self._point_measure_hover else [])
            if len(targets) == 2:
                a,b = [project(p) for p in targets]
                draw.line((*a,*b), fill=(0,0,0,190), width=5)
                draw.line((*a,*b), fill=(255,255,255,220), width=2)
                for px,py in (a,b): draw.ellipse((px-4,py-4,px+4,py+4),fill=(255,255,255,225))
                value = measured_deviation(targets[0],targets[1],native_size[0])
                text = f'Δ {abs(value):.2f} ‰'
                if self.settings.language == 'de': text=text.replace('.',',')
            else:
                text = self._t('measure_choose_end' if points else 'measure_choose_start')
            overlay_text(draw,(12*scaling,10*scaling),text,font)
        notices = []
        if hud_on:
            if detail: text=self._t('view_zoom',value='100')
            elif view is not None and view.active: text=self._t('view_zoom',value=f'{view.scale*100:.0f}')
            else: text=self._t('view_fitted')
            notices.append(text)
        if look_notice:
            notices.append(self._look_notice_text())
        for row, text in enumerate(notices):
            tw = draw.textlength(text, font=font)
            x = 12*scaling
            y = image.height-font.size-15*scaling-row*(font.size+14*scaling)
            draw.rounded_rectangle((x-6,y-3,x+tw+7,y+font.size+7),radius=4,fill=(0,0,0,145))
            overlay_text(draw,(x,y),text,font)
        return Image.alpha_composite(image.convert('RGBA'),overlay).convert('RGB')
