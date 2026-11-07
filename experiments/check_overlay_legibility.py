"""Compare actual preview drawing routines without changing application styles.

The points are synthetic legibility samples, not scene-depth measurements.
WCAG contrast is an orientation for the design, not a conformance audit.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageOps

from stereofine.anaglyph import make_anaglyph
from stereofine.endpoints import to_master
from stereofine.inspection import InspectionView
import stereofine.preview as preview
from stereofine.state import PairState
import stereofine.view_controls as views


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/overlay-legibility-13'
SCALES = (1., 1.25, 1.5, 2.)
SIZE = (360, 180)
STYLES = ('Current', 'NF palette', 'NF palette + outline')


def luminance(rgb):
    rgb = np.asarray(rgb, np.float64) / 255.
    linear = np.where(rgb <= .04045, rgb / 12.92, ((rgb + .055) / 1.055) ** 2.4)
    return linear @ np.array([.2126, .7152, .0722])


def contrast(a, b):
    a, b = luminance(a), luminance(b)
    return (np.maximum(a, b) + .05) / (np.minimum(a, b) + .05)


def stroke_analysis(white, white_alpha, dark_alpha):
    bg = np.repeat(np.arange(256, dtype=float)[:, None], 3, axis=1)
    core = white * white_alpha / 255. + bg * (1 - white_alpha / 255.)
    dark = bg * (1 - dark_alpha / 255.)
    minimum_light = luminance(np.full(3, white * white_alpha / 255.))
    maximum_dark = luminance(np.full(3, 255 - dark_alpha))
    worst = ((minimum_light + .05) / (maximum_dark + .05)
             if minimum_light > maximum_dark else 1.)
    return dict(minimum_on_equal_gray_backgrounds=float(contrast(core, dark).min()),
                minimum_with_independently_varying_backgrounds=float(worst),
                scope='Fully covered core versus fully covered dark surround, before antialiasing. '
                      'A shifted shadow does not supply this surround on every side.')


def backgrounds():
    w, h = SIZE
    yy, xx = np.indices((h, w))
    rng = np.random.default_rng(20261106)
    smooth = cv2.GaussianBlur(rng.random((h, w)).astype(np.float32), (0, 0), 4)
    smooth = (smooth - smooth.min()) / (np.ptp(smooth) or 1)
    noise = rng.random((h, w))
    clouds = np.repeat((220 + smooth[..., None]*35), 3, axis=2)
    foliage = np.stack([20 + 85*smooth + 40*noise,
                        45 + 110*smooth + 45*noise,
                        10 + 45*smooth + 25*noise], axis=-1)
    night = np.repeat((3 + smooth[..., None]*24), 3, axis=2)
    for x, y in ((65, 37), (172, 100), (280, 126)):
        cv2.circle(night, (x, y), 7, (240, 210, 160), -1)
    checks = np.repeat((((xx//3 + yy//3) % 2)*255)[..., None], 3, axis=2)
    bars = np.zeros((h, w, 3), np.uint8)
    bars[(xx//9) % 2 == 0] = (255, 0, 0)
    bars[(xx//9) % 2 == 1] = (0, 255, 255)
    source = ROOT/'assets/stereofine.jpg'
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    with Image.open(source) as im:
        left = ImageOps.fit(im.crop((0, 0, im.width//2, im.height)), SIZE)
        right = ImageOps.fit(im.crop((im.width//2, 0, im.width, im.height)), SIZE)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    ana = make_anaglyph(np.asarray(left), np.asarray(right))
    raw = {
        'White': np.full((h, w, 3), 255),
        'Black': np.zeros((h, w, 3)),
        'Mid gray': np.full((h, w, 3), 127),
        'Gradient': np.repeat(np.tile(np.linspace(0, 255, w), (h, 1))[..., None], 3, axis=2),
        'Fine pattern': checks,
        'Foliage-like texture': foliage,
        'Bright clouds': clouds,
        'Night texture': night,
        'Red-cyan pattern': bars,
        'Bundled photo': np.asarray(left),
        'Anaglyph': ana,
    }
    return {name: Image.fromarray(np.clip(data, 0, 255).astype(np.uint8))
            for name, data in raw.items()}, before


@contextmanager
def style_context(style, scale):
    """Patch rendering calls only during this isolated experiment."""
    old_line, old_text = cv2.line, cv2.putText
    old_overlay_text = views.overlay_text
    old_pil_line = ImageDraw.ImageDraw.line
    if style == 'Current':
        yield
        return
    outlined = style.endswith('outline')
    radius = max(1, round(scale))
    foreground = []

    def line(img, p1, p2, color, thickness=1, **kwargs):
        if tuple(color[:3]) == (0, 0, 0):
            if outlined:
                return img
            return old_line(img, p1, p2, (0, 0, 0, 190), thickness, **kwargs)
        width = max(1, round(thickness*scale)) if outlined else thickness
        if outlined:
            old_line(img, p1, p2, (0, 0, 0, 200), width+2*radius, **kwargs)
            foreground.append(('line', img, p1, p2, width, dict(kwargs)))
        return old_line(img, p1, p2, (255, 255, 255, 215), width, **kwargs)

    def text(img, label, org, face, font_scale, color, thickness=1, lineType=cv2.LINE_AA, **kwargs):
        if tuple(color[:3]) == (0, 0, 0):
            if outlined:
                return img
            return old_text(img, label, org, face, font_scale, (0, 0, 0, 195),
                            thickness, lineType, **kwargs)
        font_scale = font_scale*scale if outlined else font_scale
        width = max(1, round(thickness*scale)) if outlined else thickness
        if outlined:
            old_text(img, label, org, face, font_scale, (0, 0, 0, 200),
                     width+2*radius, lineType, **kwargs)
            foreground.append(('text', img, label, org, face, font_scale, width, lineType, dict(kwargs)))
        result = old_text(img, label, org, face, font_scale, (255, 255, 255, 225),
                          width, lineType, **kwargs)
        if outlined and label == str(max(preview.MEASURE_CROSS_STEPS_PERMILLE)):
            # All outlines first, all foreground strokes last: later tick
            # outlines must never punch dark holes into the existing axes.
            for command in foreground:
                if command[0] == 'line':
                    _, layer, a, b, thick, options = command
                    old_line(layer, a, b, (255, 255, 255, 215), thick, **options)
                else:
                    _, layer, s, position, f, fs, thick, aa, options = command
                    old_text(layer, s, position, f, fs, (255, 255, 255, 225), thick, aa, **options)
            foreground.clear()
        return result

    def outlined_text(draw, xy, label, font, **kwargs):
        draw.text(xy, label, font=font, fill=(255, 255, 255, 225),
                  stroke_width=radius, stroke_fill=(0, 0, 0, 200))

    def pil_line(draw, xy, fill=None, width=0, joint=None):
        if (outlined and fill in ((0, 0, 0, 190), (255, 255, 255, 215))
                and len(xy) == 4):
            x0, y0, x1, y1 = xy
            cx, cy = (x0+x1)/2, (y0+y1)/2
            xy = (cx+(x0-cx)*scale, cy+(y0-cy)*scale,
                  cx+(x1-cx)*scale, cy+(y1-cy)*scale)
            width = max(1, round(width*scale))
            if fill == (0, 0, 0, 190):
                fill = (0, 0, 0, 200)
        return old_pil_line(draw, xy, fill=fill, width=width, joint=joint)

    cv2.line, cv2.putText = line, text
    if outlined:
        views.overlay_text = outlined_text
        ImageDraw.ImageDraw.line = pil_line
    try:
        yield
    finally:
        cv2.line, cv2.putText = old_line, old_text
        views.overlay_text = old_overlay_text
        ImageDraw.ImageDraw.line = old_pil_line


def render(background, scale, style):
    size = tuple(round(v*scale) for v in SIZE)
    image = background.resize(size, Image.Resampling.LANCZOS)
    state = PairState()
    state.disparity.valid = True
    state.disparity.uncertain = True
    value = -2.21/1000
    marker = dict(left=[.76+value/2, .46], right=[.76-value/2, .46], tentative=True)
    state.disparity.endpoints = to_master({'markers': {'near': marker}}, state,
                                         (size[1], size[0]), size[0]/size[1])
    app = SimpleNamespace(current=SimpleNamespace(state=state),
        _inspection_view=InspectionView(), current_job_kind=None,
        show_deviation_points=SimpleNamespace(get=lambda: True),
        _measure_tool_var=SimpleNamespace(get=lambda: False), _fit_notice=False,
        preview_label=SimpleNamespace(_get_widget_scaling=lambda: scale),
        settings=SimpleNamespace(language='de'), _effective_preview_mode=lambda: 'Farbig')
    with style_context(style, scale):
        image = preview.draw_measure_cross_overlay(image, round(108*scale), round(112*scale),
                                                    reference_width=round(1200*scale))
        image = views.ViewControlsMixin._decorate_view(app, image, (0, 0, *size), size)
    return image


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    bgs, source_hash = backgrounds()
    images = {}
    for name, background in bgs.items():
        for scale in SCALES:
            for style in STYLES:
                im = render(background, scale, style)
                assert im.size == tuple(round(v*scale) for v in SIZE)
                images[name, scale, style] = im
    selected = ('White', 'Black', 'Mid gray', 'Fine pattern', 'Foliage-like texture',
                'Night texture', 'Bundled photo', 'Anaglyph')
    row_h, margin, top = 208, 18, 90
    sheet = Image.new('RGB', (SIZE[0]*3+margin*4, top+row_h*len(selected)+58), '#111111')
    d = ImageDraw.Draw(sheet)
    font, small = views.overlay_font(21), views.overlay_font(15)
    d.text((margin, 12), 'StereoFine: overlay legibility comparison (100%)', font=font, fill='#c6a95e')
    headings = ('A: current reticle + current N/F', 'B: reticle uses N/F palette', 'C: N/F palette + full outline')
    for col, text in enumerate(headings):
        d.text((margin+col*(SIZE[0]+margin), 55), text, font=small, fill='white')
    for row, name in enumerate(selected):
        y = top+row*row_h
        for col, style in enumerate(STYLES):
            x = margin+col*(SIZE[0]+margin)
            d.text((x, y), name, font=small, fill='#b8b8b8')
            sheet.paste(images[name, 1., style], (x, y+24))
    d.text((margin, sheet.height-45), 'Synthetic test marks, not measured scene depth. '
           'C also scales thin strokes and reticle numbers with display scaling.', font=small, fill='#b8b8b8')
    sheet.save(OUT/'StereoFine_Overlay_Comparison.png')
    for scale in SCALES:
        tile_w, tile_h = images['Fine pattern', scale, 'Current'].size
        strip = Image.new('RGB', (tile_w*3, tile_h+35), '#111111')
        dr = ImageDraw.Draw(strip)
        for col, style in enumerate(STYLES):
            dr.text((col*tile_w+8, 7), f'{style}, {scale:.0%}', font=small, fill='white')
            strip.paste(images['Fine pattern', scale, style], (col*tile_w, 35))
        strip.save(OUT/f'dpi_{round(scale*100)}.png')
    report = dict(backgrounds=list(bgs), scales=list(SCALES), styles=list(STYLES),
        rendered_combinations=len(images), original_asset_sha256=source_hash,
        actual_routines=['preview.draw_measure_cross_overlay', 'ViewControlsMixin._decorate_view'],
        sources=['https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html',
                 'https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html',
                 'https://www.w3.org/WAI/WCAG22/Techniques/general/G18'],
        ideal_stroke_contrast={
            'legacy_reticle': stroke_analysis(245, 132, 105),
            'NF_cross': stroke_analysis(255, 215, 190),
            'NF_text_palette': stroke_analysis(255, 225, 195),
            'outlined_text_candidate': stroke_analysis(255, 225, 200)},
        limitation='Rendering and contrast checks, not a human reading study or a formal '
                   'accessibility audit. No monitor, glasses or physical stereo-view test. '
                   'Candidate changes exist only inside this experiment.')
    (OUT/'results.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
