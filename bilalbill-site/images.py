"""Create deterministic, locally generated social covers and WebP thumbnails."""

from __future__ import annotations

import io
import re
import textwrap

from PIL import Image, ImageDraw, ImageFont


def _font(size: int) -> ImageFont.ImageFont:
    for candidate in (
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def make_cover_images(title: str, site_name: str = "bilalbill") -> tuple[bytes, bytes]:
    """Return a 1200x630 PNG social cover and a 400x210 WebP thumbnail."""
    image = Image.new("RGB", (1200, 630), "#102a43")
    draw = ImageDraw.Draw(image)
    for x in range(image.width):
        blend = x / max(1, image.width - 1)
        red = int(16 + blend * 7)
        green = int(42 + blend * 70)
        blue = int(67 + blend * 65)
        draw.line((x, 0, x, image.height), fill=(red, green, blue))

    draw.rounded_rectangle((70, 65, 1130, 565), radius=36, outline="#73e0c1", width=4)
    draw.text((120, 115), site_name[:40], fill="#73e0c1", font=_font(32))
    clean_title = " ".join(re.sub(r"\s+", " ", title).split())
    lines = textwrap.wrap(clean_title, width=34)[:4]
    draw.multiline_text(
        (120, 200),
        "\n".join(lines),
        fill="#ffffff",
        font=_font(54),
        spacing=18,
        stroke_width=0,
    )
    thumbnail = image.resize((400, 210), Image.Resampling.LANCZOS)
    full_buffer = io.BytesIO()
    thumbnail_buffer = io.BytesIO()
    image.save(full_buffer, format="PNG", optimize=True)
    thumbnail.save(thumbnail_buffer, format="WEBP", quality=82, method=4)
    return full_buffer.getvalue(), thumbnail_buffer.getvalue()
