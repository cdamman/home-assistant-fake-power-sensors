"""Generate the brand assets for the Fake Power Sensors integration.

The icon is a Home Assistant blue rounded square holding a white lightning
bolt (the MDI "flash" outline) encircled by a dashed ring — the dashes hint at
the "fake"/simulated nature of the measurements.

Everything is rasterised at 8x and downscaled with LANCZOS for antialiasing.

Run from the repository root, with Pillow installed:

    python3 scripts/generate_brand_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path("custom_components/fake_power_sensors/brand")

HA_BLUE = (65, 189, 245, 255)  # #41BDF5, the Home Assistant accent colour
WHITE = (255, 255, 255, 255)

SS = 8  # supersampling factor
BASE = 512  # largest asset (icon@2x.png)

# MDI "flash" (M11,15H6L13,1V9H18L11,23V15Z) on its native 24x24 grid.
BOLT = [(11, 15), (6, 15), (13, 1), (13, 9), (18, 9), (11, 23)]


def render(size: int) -> Image.Image:
    """Render the icon at `size` pixels."""
    s = size * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Rounded square background, with a small margin so the corners breathe.
    margin = 0.04 * s
    draw.rounded_rectangle(
        (margin, margin, s - margin, s - margin),
        radius=0.20 * s,
        fill=HA_BLUE,
    )

    # Dashed ring around the bolt: 16 evenly spaced arcs.
    ring_r = 0.355 * s
    ring_w = max(1, int(round(0.042 * s)))
    box = (
        s / 2 - ring_r,
        s / 2 - ring_r,
        s / 2 + ring_r,
        s / 2 + ring_r,
    )
    dashes = 16
    step = 360 / dashes
    for index in range(dashes):
        start = index * step - 90
        draw.arc(box, start, start + step * 0.55, fill=WHITE, width=ring_w)

    # Lightning bolt, scaled to 0.50 of the canvas height and centred.
    height = 0.50 * s
    scale = height / 24
    width = 12 * scale  # the bolt spans x=6..18 on the 24 grid
    offset_x = (s - width) / 2 - 6 * scale
    offset_y = (s - 24 * scale) / 2
    draw.polygon(
        [(x * scale + offset_x, y * scale + offset_y) for x, y in BOLT],
        fill=WHITE,
    )

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    """Write icon.png (256x256) and icon@2x.png (512x512)."""
    OUT.mkdir(parents=True, exist_ok=True)
    master = render(BASE)
    master.save(OUT / "icon@2x.png", optimize=True)
    master.resize((256, 256), Image.LANCZOS).save(OUT / "icon.png", optimize=True)
    print("written:", *(p.name for p in sorted(OUT.iterdir())))


if __name__ == "__main__":
    main()
