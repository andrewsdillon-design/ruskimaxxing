"""Draw the RuskiMaxxing logo: an original double-headed eagle clutching a barbell.

Byzantine palette (imperial purple, gold, crimson, ivory). Every shape is drawn
here from scratch - no crowns, shield, orb or scepter from any national coat of
arms. Run: python packaging/make_logo.py  (needs Pillow) -> src/ruskimaxxing/assets/
"""

from pathlib import Path

from PIL import Image, ImageDraw

PURPLE, PURPLE_DARK = (74, 25, 66), (46, 12, 40)
GOLD, GOLD_DARK, GOLD_LIGHT = (201, 162, 39), (140, 104, 18), (240, 214, 120)
CRIMSON, IVORY = (139, 26, 26), (246, 239, 222)
S = 1024  # draw large, downsample for smooth edges
OUT = Path(__file__).resolve().parent.parent / "src" / "ruskimaxxing" / "assets"


def mirror(points):
    return [(S - x, y) for x, y in points]


def both(draw, points, **kw):
    draw.polygon(points, **kw)
    draw.polygon(mirror(points), **kw)


def draw_logo(size=512, background=True) -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = S // 2
    if background:
        d.ellipse((8, 8, S - 8, S - 8), fill=GOLD)
        d.ellipse((30, 30, S - 30, S - 30), fill=PURPLE_DARK)
        d.ellipse((44, 44, S - 44, S - 44), fill=PURPLE)
        d.ellipse((64, 64, S - 64, S - 64), outline=GOLD_DARK, width=4)

    # wings: three layered feather rows, spread up and out (left side, then mirrored)
    rows = [
        # (root x, root y, tip spread) - outer to inner
        [(470, 430), (140, 170), (118, 250), (170, 270), (110, 330), (170, 350), (120, 410), (190, 420),
         (150, 480), (230, 480), (210, 540), (300, 520), (470, 540)],
        [(470, 450), (200, 230), (190, 300), (235, 315), (200, 370), (250, 385), (220, 440), (290, 450),
         (270, 505), (470, 520)],
    ]
    both(d, rows[0], fill=GOLD, outline=GOLD_DARK, width=6)
    both(d, rows[1], fill=GOLD_LIGHT, outline=GOLD_DARK, width=5)
    for x0, y0, x1, y1 in [(250, 320, 440, 455), (230, 380, 440, 480), (240, 440, 440, 505)]:
        d.line((x0, y0, x1, y1), fill=GOLD_DARK, width=5)
        d.line((S - x0, y0, S - x1, y1), fill=GOLD_DARK, width=5)

    # necks and heads, looking outward
    neck = [(462, 430), (428, 330), (395, 290), (380, 262), (448, 245), (480, 320), (505, 420)]
    both(d, neck, fill=GOLD, outline=GOLD_DARK, width=6)
    head = [(372, 270), (335, 240), (322, 195), (340, 153), (385, 133), (430, 143), (455, 180), (455, 230),
            (440, 257)]
    both(d, head, fill=GOLD, outline=GOLD_DARK, width=6)
    beak = [(330, 163), (270, 161), (232, 183), (222, 217), (240, 241), (248, 213), (268, 203), (300, 207),
            (326, 221)]
    both(d, beak, fill=GOLD_LIGHT, outline=GOLD_DARK, width=6)
    both(d, [(262, 207), (300, 213), (326, 221), (300, 203)], fill=GOLD_DARK)  # mouth line
    for ex in (372, S - 372):
        d.ellipse((ex - 15, 169, ex + 15, 197), fill=CRIMSON, outline=PURPLE_DARK, width=4)
        d.line((ex - 26, 163, ex + 22, 157), fill=GOLD_DARK, width=6)  # brow

    # body
    d.ellipse((c - 88, 360, c + 88, 620), fill=GOLD, outline=GOLD_DARK, width=6)
    for y in range(405, 600, 36):  # breast feathers
        d.arc((c - 62, y - 20, c + 62, y + 24), 20, 160, fill=GOLD_DARK, width=5)

    # tail fan
    tail = [(c - 45, 590), (c - 110, 760), (c - 55, 735), (c, 790), (c + 55, 735), (c + 110, 760), (c + 45, 590)]
    d.polygon(tail, fill=GOLD, outline=GOLD_DARK, width=6)
    for dx in (-55, 0, 55):
        d.line((c, 600, c + dx, 750), fill=GOLD_DARK, width=5)

    # legs down to the bar
    leg = [(c - 45, 580), (c - 120, 660), (c - 100, 675), (c - 25, 605)]
    both(d, leg, fill=GOLD, outline=GOLD_DARK, width=5)

    # barbell: long bar, collars, two plates each side
    bar_y = 690
    d.rounded_rectangle((110, bar_y - 11, S - 110, bar_y + 11), radius=10, fill=IVORY, outline=GOLD_DARK, width=4)
    for x in (170, S - 170):  # collars
        d.rectangle((x - 12, bar_y - 22, x + 12, bar_y + 22), fill=GOLD_DARK)
    for x, h, w in ((205, 150, 42), (252, 118, 36)):
        for px in (x, S - x):
            d.rounded_rectangle((px - w // 2, bar_y - h, px + w // 2, bar_y + h), radius=8,
                                fill=CRIMSON, outline=GOLD, width=5)

    # talons gripping the bar
    for tx in (c - 115, c + 85):
        for k in range(3):
            x = tx + k * 13
            d.arc((x - 14, bar_y - 26, x + 14, bar_y + 20), 200, 20, fill=PURPLE_DARK, width=7)

    return img.resize((size, size), Image.LANCZOS)


MOBILE = Path(__file__).resolve().parent.parent / "src" / "ruskimaxxing_mobile" / "resources"
PHONE_SIZES = (16, 20, 29, 32, 40, 48, 58, 60, 64, 72, 76, 80, 87, 96, 120, 128, 144, 152, 167, 180, 192, 256,
               320, 480, 512, 640, 960, 1024, 1280, 1920)


def square(size: int) -> Image.Image:
    """Medallion on a solid purple square (app stores reject transparent corners)."""
    img = Image.new("RGBA", (size, size), PURPLE_DARK + (255,))
    logo = draw_logo(int(size * 0.9))
    img.alpha_composite(logo, ((size - logo.width) // 2, (size - logo.height) // 2))
    return img.convert("RGB")


def phone_icons():
    """icon-<n>.png (iOS / desktop), icon-square-<n>.png and icon-round-<n>.png (Android)."""
    MOBILE.mkdir(parents=True, exist_ok=True)
    for n in PHONE_SIZES:
        sq = square(n)
        sq.save(MOBILE / f"icon-{n}.png")
        sq.save(MOBILE / f"icon-square-{n}.png")
        if n in (48, 72, 96, 144, 192):  # Android launcher sizes
            draw_logo(n).save(MOBILE / f"icon-round-{n}.png")
    for n in (108, 162, 216, 324, 432):  # Android adaptive foreground: logo inside the 66% safe zone
        fg = Image.new("RGBA", (n, n), (0, 0, 0, 0))
        logo = draw_logo(int(n * 0.66))
        fg.alpha_composite(logo, ((n - logo.width) // 2, (n - logo.height) // 2))
        fg.save(MOBILE / f"icon-adaptive-{n}.png")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    draw_logo(512).save(OUT / "logo.png")
    draw_logo(96).save(OUT / "logo_96.png")
    draw_logo(256).save(OUT / "icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    draw_logo(1024).save(OUT / "icon.icns")  # macOS app icon
    draw_logo(64).save(OUT / "favicon.png")
    phone_icons()
    print(f"wrote logo.png, logo_96.png, icon.ico, icon.icns, favicon.png to {OUT} and phone icons to {MOBILE}")


if __name__ == "__main__":
    main()
