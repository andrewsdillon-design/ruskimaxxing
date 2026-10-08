"""Make the Expo phone app's icons and splash image from the RuskiMaxxing emblem.

    python tools/make_mobile_icons.py

Writes mobile/assets/: icon.png (1024, no transparency, for the App Store), splash-icon.png,
android-icon-foreground/background/monochrome.png (Android adaptive icon layers), emblem.png (in-app,
256 px) and favicon.png.
"""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
LOGO = ROOT / "src" / "ruskimaxxing" / "assets" / "logo.png"           # round emblem, transparent corners
ICON = ROOT / "src" / "ruskimaxxing_mobile" / "resources" / "icon-1024.png"  # emblem on purple, no alpha
OUT = ROOT / "mobile" / "assets"
PURPLE_DARK = (46, 12, 40)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    logo = Image.open(LOGO).convert("RGBA")
    Image.open(ICON).convert("RGB").resize((1024, 1024), Image.LANCZOS).save(OUT / "icon.png")
    logo.resize((1024, 1024), Image.LANCZOS).save(OUT / "splash-icon.png")

    # Android adaptive icons: the launcher masks a 1024 canvas to a circle/squircle; keep the art in the middle 2/3
    fg = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    art = logo.resize((680, 680), Image.LANCZOS)
    fg.paste(art, (172, 172), art)
    fg.save(OUT / "android-icon-foreground.png")
    Image.new("RGB", (1024, 1024), PURPLE_DARK).save(OUT / "android-icon-background.png")
    alpha = fg.getchannel("A")
    mono = Image.new("RGBA", (1024, 1024), (255, 255, 255, 0))
    mono.putalpha(alpha)
    mono.save(OUT / "android-icon-monochrome.png")

    logo.resize((256, 256), Image.LANCZOS).save(OUT / "emblem.png")
    logo.resize((48, 48), Image.LANCZOS).save(OUT / "favicon.png")
    print(f"wrote icons to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
