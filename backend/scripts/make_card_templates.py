"""Draw the layout A card templates (issue #218) from scratch.

Writes assets/Card_Template_<Rarity>.png for the four rarities and
assets/Card_Template_Holo.png: 597 x 845 RGBA frames with transparent cutouts at
image._PORTRAIT_SLOT and image._LOGO_SLOT. The slot rectangles and colours come
from backend/image.py, so the renderer and the templates agree.

The Holo template is the Legendary one under a strong rainbow on the frame and
pillars, with only a faint tint on the name bar, type line and rules box so the
text stays readable. The frame's outer edge keeps the legendary gold.

Run from the repo root:  python backend/scripts/make_card_templates.py
"""
import os
import sys

_BACKEND = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from PIL import Image, ImageChops, ImageDraw  # noqa: E402

import image  # noqa: E402

_BODY = (21, 21, 26, 255)
_PLATE_TOP = (46, 46, 54)
_PLATE_BOTTOM = (27, 27, 33)
_PILLAR_BOTTOM = (18, 18, 22)
_TYPE_OUTLINE = (74, 74, 85, 255)
_CREAM = (233, 226, 210, 255)
_HATCH_ALPHA = 30
_HOLO_STRONG = 150     # rainbow alpha over the frame body, pillars and portrait border
_HOLO_EDGE = 40        # over the outer edge, so the rarity gold still reads
_HOLO_PANEL = 22       # over the name bar, type line and rules box
_OUT_DIR = os.path.normpath(os.path.join(_BACKEND, "..", "assets"))


def _gradient(size, top, bottom):
    w, h = size
    col = Image.new("RGBA", (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        col.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)) + (255,))
    return col.resize((w, h))


def _rounded_mask(size, radius):
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    return mask


def _plate(img, box, top, bottom, outline, radius, width=2):
    """A gradient plate with a rounded outline."""
    x0, y0, x1, y1 = box
    size = (x1 - x0, y1 - y0)
    img.paste(_gradient(size, top, bottom), (x0, y0), _rounded_mask(size, radius))
    ImageDraw.Draw(img).rounded_rectangle((x0, y0, x1 - 1, y1 - 1), radius=radius,
                                          outline=outline, width=width)


def _hatch(size, colour):
    w, h = size
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    fill = colour + (_HATCH_ALPHA,)
    for off in range(-h, w + h, 18):
        d.line((off, 0, off + h, h), fill=fill, width=4)
        d.line((off, h, off + h, 0), fill=fill, width=4)
    return layer


def _cut(img, box):
    x0, y0, x1, y1 = box
    img.paste((0, 0, 0, 0), (x0, y0, x1, y1))


def draw_template(rarity: str):
    """The template for one rarity as a 597 x 845 RGBA image."""
    colour = image._RARITY_COLORS[rarity]
    deep = image._RARITY_DEEP[rarity]
    size = image._CARD_SIZE
    card_mask = _rounded_mask(size, image._CARD_RADIUS)

    img = Image.new("RGBA", size, (0, 0, 0, 0))
    body = Image.new("RGBA", size, _BODY)
    body.alpha_composite(_hatch(size, colour))
    img.paste(body, (0, 0), card_mask)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=image._CARD_RADIUS,
                        outline=colour + (255,), width=image._FRAME_WIDTH)

    _plate(img, image._NAME_BAR, _PLATE_TOP, _PLATE_BOTTOM, colour + (255,), radius=34)
    for pillar in (image._LEFT_PILLAR, image._RIGHT_PILLAR):
        _plate(img, pillar, deep, _PILLAR_BOTTOM, colour + (255,), radius=6)
    d.rectangle(tuple(v - (1 if i >= 2 else 0) for i, v in enumerate(image._PORTRAIT_FRAME)),
                fill=colour + (255,))
    _plate(img, image._TYPE_LINE, _PLATE_TOP, _PLATE_BOTTOM, _TYPE_OUTLINE, radius=8)
    x0, y0, x1, y1 = image._RULES_BOX
    d.rounded_rectangle((x0, y0, x1 - 1, y1 - 1), radius=8, fill=_CREAM)

    _cut(img, image._PORTRAIT_SLOT)
    _cut(img, image._LOGO_SLOT)
    return img


def _holo_alpha_mask():
    """Per-pixel rainbow strength: strong on the frame and pillars, faint on the text
    panels and on the outer edge."""
    size = image._CARD_SIZE
    mask = Image.new("L", size, _HOLO_STRONG)
    d = ImageDraw.Draw(mask)
    w = image._FRAME_WIDTH
    d.rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=image._CARD_RADIUS,
                        outline=_HOLO_EDGE, width=w)
    for box, radius in ((image._NAME_BAR, 34), (image._TYPE_LINE, 8), (image._RULES_BOX, 8)):
        x0, y0, x1, y1 = box
        d.rounded_rectangle((x0, y0, x1 - 1, y1 - 1), radius=radius, fill=_HOLO_PANEL)
    return mask


def draw_holo_template():
    """The Holo Legendary template: Legendary under a strong rainbow."""
    img = draw_template("legendary")
    rainbow = image._rainbow(img.size, saturation=0.7, alpha=255, angle=35, bands=2.0)
    rainbow.putalpha(ImageChops.multiply(_holo_alpha_mask(), img.getchannel("A")))
    img.alpha_composite(rainbow)
    return img


def main(out_dir: str = _OUT_DIR) -> list[str]:
    written = []
    for rarity, name in image._CARD_TEMPLATES.items():
        path = os.path.join(out_dir, name)
        draw_template(rarity).save(path, optimize=True)
        written.append(path)
    path = os.path.join(out_dir, image._HOLO_TEMPLATE)
    draw_holo_template().save(path, optimize=True)
    written.append(path)
    return written


if __name__ == "__main__":
    for p in main():
        print(p)
