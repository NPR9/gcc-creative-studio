# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Deterministic image operations for Asset Multiplication.

Everything here is plain Pillow so it is fast, testable and never changes
copy: the image model renders the picture, this module sets the type.
"""

import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from src.workflows_executor.creative.size_library import SafeZone, SizeSpec

SCRIM_COLOR = (0, 0, 0)
TEXT_COLOR = (255, 255, 255)
CTA_FILL = (255, 255, 255)
CTA_TEXT = (0, 32, 96)

# Bundled fallback with full Latin coverage (à è ì ò ù ä ö ü ß ñ ç ...).
# Pillow's built-in font lacks accented letters, so it is never used for copy.
BUNDLED_FONT = Path(__file__).with_name("fonts") / "DejaVuSans-Bold.ttf"


@dataclass(frozen=True)
class OverlayText:
    headline: str | None = None
    cta: str | None = None


def open_image(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


def to_png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def crop_and_resize(image: Image.Image, width: int, height: int) -> Image.Image:
    """Centre-crop to the target ratio, then resize to exact pixels."""
    src_w, src_h = image.size
    target = width / height
    if src_w / src_h > target:
        new_w = round(src_h * target)
        left = (src_w - new_w) // 2
        box = (left, 0, left + new_w, src_h)
    else:
        new_h = round(src_w / target)
        top = (src_h - new_h) // 2
        box = (0, top, src_w, top + new_h)
    return image.crop(box).resize((width, height), Image.Resampling.LANCZOS)


def load_font(
    size: int, font_path: str | None = None
) -> ImageFont.FreeTypeFont:
    """Brand font when configured, else the bundled DejaVu Sans Bold."""
    return ImageFont.truetype(font_path or str(BUNDLED_FONT), size)


def _text_width(draw: ImageDraw.ImageDraw, text: str, font) -> float:
    left, _, right, _ = draw.textbbox((0, 0), text, font=font)
    return right - left


def wrap_text(
    draw: ImageDraw.ImageDraw, text: str, font, max_width: float
) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if not current or _text_width(draw, candidate, font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: float,
    max_height: float,
    start_size: int,
    font_path: str | None = None,
    max_lines: int = 3,
    min_size: int = 12,
):
    """Largest font size at which the text fits the box in <= max_lines."""
    size = start_size
    while size >= min_size:
        font = load_font(size, font_path)
        lines = wrap_text(draw, text, font, max_width)
        line_height = size * 1.2
        fits_width = all(
            _text_width(draw, ln, font) <= max_width for ln in lines
        )
        if (
            len(lines) <= max_lines
            and fits_width
            and len(lines) * line_height <= max_height
        ):
            return font, lines, line_height
        size -= 2
    font = load_font(min_size, font_path)
    return font, wrap_text(draw, text, font, max_width), min_size * 1.2


def _safe_box(width: int, height: int, zone: SafeZone):
    return (
        round(width * zone.left),
        round(height * zone.top),
        round(width * (1 - zone.right)),
        round(height * (1 - zone.bottom)),
    )


def apply_overlay(
    image: Image.Image,
    size: SizeSpec,
    text: OverlayText,
    logo: Image.Image | None = None,
    font_path: str | None = None,
) -> Image.Image:
    """Place logo, headline and CTA inside the safe zone.

    Standard formats: logo top-left, text block bottom-left over a vertical
    scrim. Wide strips (ratio >= 3, e.g. 728x90, 4:1, 8:1): text block on the
    left, vertically centred, logo on the right, over a horizontal scrim.
    """
    canvas = image.convert("RGBA")
    width, height = canvas.size
    left, top, right, bottom = _safe_box(width, height, size.safe_zone)
    box_w, box_h = right - left, bottom - top
    short_side = min(width, height)
    wide = size.ratio >= 3

    if logo is not None:
        logo_rgba = logo.convert("RGBA")
        max_w = box_w * (0.18 if wide else 0.22)
        max_h = box_h * (0.6 if wide else 0.2)
        scale = min(max_w / logo_rgba.width, max_h / logo_rgba.height)
        logo_rgba = logo_rgba.resize(
            (
                max(1, round(logo_rgba.width * scale)),
                max(1, round(logo_rgba.height * scale)),
            ),
            Image.Resampling.LANCZOS,
        )
        if wide:
            pos = (
                right - logo_rgba.width,
                top + (box_h - logo_rgba.height) // 2,
            )
        else:
            pos = (left, top)
        canvas.alpha_composite(logo_rgba, pos)

    if not (text.headline or text.cta):
        return canvas.convert("RGB")

    draw = ImageDraw.Draw(canvas)
    text_w = box_w * (0.5 if wide else 1.0)
    cta_font = load_font(
        max(10, round(short_side * (0.16 if wide else 0.04))), font_path
    )
    cta_w = cta_h = 0
    if text.cta:
        pad_x = round(cta_font.size * 0.75)
        pad_y = round(cta_font.size * 0.35)
        cta_w = _text_width(draw, text.cta, cta_font) + 2 * pad_x
        cta_h = cta_font.size + 2 * pad_y

    if wide and text.cta:
        # CTA sits to the right of the headline on a strip.
        headline_w = text_w - cta_w - box_w * 0.03
        headline_h = box_h
    else:
        headline_w = text_w
        headline_h = (box_h if wide else box_h * 0.34) - (
            cta_h * 1.4 if cta_h else 0
        )

    headline_lines: list[str] = []
    line_height = 0.0
    headline_font = None
    if text.headline:
        headline_font, headline_lines, line_height = fit_text(
            draw,
            text.headline,
            max_width=max(1, headline_w),
            max_height=max(1, headline_h),
            start_size=max(12, round(short_side * (0.3 if wide else 0.075))),
            font_path=font_path,
            max_lines=2 if wide else 3,
            min_size=10,
        )
    lines_h = round(len(headline_lines) * line_height)

    # Gradient scrim keeps text legible on any image.
    if wide:
        scrim_w = min(width, round(left + text_w + width * 0.08))
        scrim = Image.new("RGBA", (scrim_w, height), (0, 0, 0, 0))
        scrim_draw = ImageDraw.Draw(scrim)
        for x in range(scrim_w):
            alpha = round(170 * (1 - x / scrim_w))
            scrim_draw.line([(x, 0), (x, height)], fill=(*SCRIM_COLOR, alpha))
        canvas.alpha_composite(scrim, (0, 0))
    else:
        block_h = lines_h + (round(cta_h * 1.4) if cta_h else 0)
        scrim_top = max(0, bottom - block_h - round(height * 0.08))
        scrim = Image.new("RGBA", (width, height - scrim_top), (0, 0, 0, 0))
        scrim_draw = ImageDraw.Draw(scrim)
        span = max(1, scrim.height)
        for y in range(scrim.height):
            alpha = round(170 * (y / span))
            scrim_draw.line([(0, y), (width, y)], fill=(*SCRIM_COLOR, alpha))
        canvas.alpha_composite(scrim, (0, scrim_top))

    draw = ImageDraw.Draw(canvas)
    if wide:
        y = top + (box_h - lines_h) / 2
    else:
        y = bottom - lines_h - (round(cta_h * 1.4) if cta_h else 0)
    for line in headline_lines:
        draw.text((left, y), line, font=headline_font, fill=TEXT_COLOR)
        y += line_height

    if text.cta:
        if wide:
            cta_x = left + text_w - cta_w
            cta_y = top + (box_h - cta_h) / 2
        else:
            cta_x = left
            cta_y = y + (round(cta_h * 0.4) if headline_lines else 0)
        draw.rounded_rectangle(
            (cta_x, cta_y, cta_x + cta_w, cta_y + cta_h),
            radius=round(cta_h / 2),
            fill=CTA_FILL,
        )
        tx = cta_x + (cta_w - _text_width(draw, text.cta, cta_font)) / 2
        draw.text(
            (tx, cta_y + cta_h / 2),
            text.cta,
            font=cta_font,
            fill=CTA_TEXT,
            anchor="lm",
        )
    return canvas.convert("RGB")
