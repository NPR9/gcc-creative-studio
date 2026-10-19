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
"""Tests for deterministic crop, resize and text overlay."""

from PIL import Image, ImageDraw

from src.workflows_executor.creative import image_ops
from src.workflows_executor.creative.size_library import (
    SafeZone,
    SizeSpec,
    load_size_library,
)


def _image(w=1600, h=1600, color=(200, 150, 90)):
    img = Image.new("RGB", (w, h), color)
    ImageDraw.Draw(img).rectangle(
        (w // 3, h // 3, 2 * w // 3, 2 * h // 3), fill=(30, 120, 60)
    )
    return img


def test_crop_and_resize_hits_exact_pixels_for_every_library_size():
    for size in load_size_library().sizes:
        out = image_ops.crop_and_resize(
            _image(1344, 768), size.width, size.height
        )
        assert out.size == (size.width, size.height)


def test_crop_is_centred():
    img = Image.new("RGB", (300, 100), (255, 0, 0))
    ImageDraw.Draw(img).rectangle((100, 0, 199, 99), fill=(0, 0, 255))
    out = image_ops.crop_and_resize(img, 100, 100)
    assert out.getpixel((50, 50)) == (0, 0, 255)


def test_overlay_keeps_size_and_changes_bottom_band_only():
    size = load_size_library().get("square_1200")
    base = image_ops.crop_and_resize(_image(), size.width, size.height)
    out = image_ops.apply_overlay(
        base,
        size,
        image_ops.OverlayText("Prodotti essenziali", "Scopri di più"),
    )
    assert out.size == base.size
    assert out.getpixel((600, 20)) == base.getpixel((600, 20))  # top untouched
    assert out.getpixel((10, 1180)) != base.getpixel(
        (10, 1180)
    )  # scrim applied


def test_no_text_and_no_logo_returns_identical_image():
    size = load_size_library().get("square_1200")
    base = image_ops.crop_and_resize(_image(), size.width, size.height)
    out = image_ops.apply_overlay(base, size, image_ops.OverlayText())
    assert list(out.getdata()) == list(base.getdata())


def test_bundled_font_has_accented_glyphs():
    # Pillow's built-in font renders these as boxes; the bundled font must not.
    font = image_ops.load_font(40)
    draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    for ch in "àèéìòùäöüßñçÀÉÜ":
        mask = font.getmask(ch)
        assert mask.size[0] > 0, ch
    box_u = draw.textbbox((0, 0), "ù", font=font)
    box_tofu = draw.textbbox((0, 0), "￿", font=font)
    assert box_u != box_tofu


def test_long_headline_wraps_inside_safe_zone():
    size = load_size_library().get("landscape_1200x628")
    draw = ImageDraw.Draw(Image.new("RGB", (size.width, size.height)))
    font, lines, _ = image_ops.fit_text(
        draw,
        "Prodotti essenziali, affidabili e sempre convenienti per chi lavora su grandi volumi",
        max_width=1000,
        max_height=200,
        start_size=60,
    )
    assert 1 <= len(lines) <= 3
    for line in lines:
        left, _, right, _ = draw.textbbox((0, 0), line, font=font)
        assert right - left <= 1000


def test_wide_strip_with_logo_and_cta():
    size = SizeSpec(
        "leader", "Leaderboard", 728, 90, ("x",), SafeZone(0.1, 0.02, 0.1, 0.02)
    )
    base = image_ops.crop_and_resize(_image(), 728, 90)
    logo = Image.new("RGBA", (400, 120), (0, 45, 110, 255))
    out = image_ops.apply_overlay(
        base, size, image_ops.OverlayText("Für Profis", "Mehr erfahren"), logo
    )
    assert out.size == (728, 90)
    # Logo sits on the right of a wide strip.
    assert out.getpixel((700, 45)) == (0, 45, 110)


def test_logo_top_left_on_standard_formats():
    size = load_size_library().get("square_1200")
    base = image_ops.crop_and_resize(_image(), 1200, 1200)
    logo = Image.new("RGBA", (400, 120), (0, 45, 110, 255))
    out = image_ops.apply_overlay(base, size, image_ops.OverlayText(), logo)
    assert out.getpixel((80, 80)) == (0, 45, 110)


def test_png_roundtrip():
    img = _image(50, 40)
    assert image_ops.open_image(image_ops.to_png_bytes(img)).size == (50, 40)
