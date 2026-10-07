"""Get Briefcase's generated iPhone Xcode project ready for an App Store / TestFlight build.

Runs on the GitHub Actions macOS runner (see .github/workflows/testflight.yml), after
`briefcase create iOS`. Standard library only.

    python tools/ios_prepare.py bundle-id                      # print the iOS bundle ID
    python tools/ios_prepare.py project --build-number 12.1    # patch the Xcode project
    python tools/ios_prepare.py check-archive PATH.xcarchive   # verify what's inside an archive

What `project` does:
  * Info.plist: build number (CFBundleVersion, must always go up), marketing version from
    pyproject, ITSAppUsesNonExemptEncryption = false, and checks the ruskimaxxing:// URL scheme.
  * Adds packaging/ios/PrivacyInfo.xcprivacy to the app (Apple requires a privacy manifest).
  * Checks the 1024 px App Store icon has no alpha channel.
  * Prints the bundle ID and writes bundle_id/project/scheme/version to $GITHUB_OUTPUT.
"""

import argparse
import os
import plistlib
import re
import shutil
import struct
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = "ruskimaxxing_mobile"
URL_SCHEME = "ruskimaxxing"
PRIVACY_MANIFEST = ROOT / "packaging" / "ios" / "PrivacyInfo.xcprivacy"
# fixed (made-up, unique) object IDs, so re-running on the same project changes nothing
FILE_REF, BUILD_FILE = "7A5C0000000000000000F001", "7A5C0000000000000000F002"


def briefcase_config() -> tuple[dict, dict]:
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["briefcase"]
    return cfg, cfg["app"][APP]


def bundle_id() -> str:
    """What Briefcase 0.4.x uses: the bundle plus the app name with '_' turned into '-'
    (App Store bundle IDs may only contain letters, digits, '-' and '.')."""
    cfg, _ = briefcase_config()
    bid = f"{cfg['bundle']}.{APP.replace('_', '-').lower()}"
    if not re.fullmatch(r"[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+", bid):
        sys.exit(f"Bundle ID {bid!r} isn't valid for the App Store")
    return bid


def fail(msg: str):
    print(f"::error::{msg}")
    sys.exit(1)


def png_has_alpha(path: Path) -> bool:
    data = path.read_bytes()[:33]
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        fail(f"{path} isn't a PNG")
    width, height, _depth, color_type = struct.unpack(">IIBB", data[16:26])
    if (width, height) != (1024, 1024):
        fail(f"{path} is {width}x{height}, the App Store icon must be 1024x1024")
    return color_type in (4, 6)  # gray+alpha, RGBA (palette PNGs with tRNS are rare; Pillow writes RGB here)


def add_privacy_manifest(pbxproj: Path, group: str) -> None:
    text = pbxproj.read_text(encoding="utf-8")
    if FILE_REF in text:
        return
    name = "PrivacyInfo.xcprivacy"
    edits = [
        (r"(/\* End PBXBuildFile section \*/)",
         f"\t\t{BUILD_FILE} /* {name} in Resources */ = {{isa = PBXBuildFile; fileRef = {FILE_REF} /* {name} */; }};\n"),
        (r"(/\* End PBXFileReference section \*/)",
         f'\t\t{FILE_REF} /* {name} */ = {{isa = PBXFileReference; lastKnownFileType = text.xml; path = {name}; '
         f'sourceTree = "<group>"; }};\n'),
    ]
    for pattern, line in edits:
        text, n = re.subn(pattern, lambda m: line + m.group(1), text, count=1)
        if not n:
            fail(f"Unexpected Xcode project layout (no {pattern}); Briefcase's template changed")
    after = [  # list entries go right after the opening "children = (" / "files = ("
        (rf"(\w{{24}} /\* {re.escape(group)} \*/ = \{{\s*isa = PBXGroup;\s*children = \(\n)",
         f"\t\t\t\t{FILE_REF} /* {name} */,\n"),
        (r"(isa = PBXResourcesBuildPhase;\s*buildActionMask = \d+;\s*files = \(\n)",
         f"\t\t\t\t{BUILD_FILE} /* {name} in Resources */,\n"),
    ]
    for pattern, line in after:
        text, n = re.subn(pattern, lambda m: m.group(1) + line, text, count=1)
        if not n:
            fail(f"Unexpected Xcode project layout (no {pattern}); Briefcase's template changed")
    pbxproj.write_text(text, encoding="utf-8")


def check_url_scheme(info: dict) -> None:
    schemes = [s for t in info.get("CFBundleURLTypes", []) for s in t.get("CFBundleURLSchemes", [])]
    if URL_SCHEME not in schemes:
        fail(f"Info.plist is missing the {URL_SCHEME}:// URL scheme (browser sign-in needs it)")


def prepare_project(xcode_dir: Path, build_number: str) -> dict:
    projects = list(xcode_dir.glob("*.xcodeproj"))
    if len(projects) != 1:
        fail(f"Expected one .xcodeproj in {xcode_dir} - run `briefcase create iOS` first")
    project = projects[0]
    paths = tomllib.loads((xcode_dir / "briefcase.toml").read_text(encoding="utf-8"))["paths"]
    plist_path = xcode_dir / paths["info_plist_path"]
    group = plist_path.parent.name                     # the app's source group/folder, e.g. "RuskiMaxxing"

    cfg, _ = briefcase_config()
    if not re.fullmatch(r"\d+(\.\d+){0,2}", build_number):
        fail(f"Build number {build_number!r} must be up to three dot-separated integers")
    with plist_path.open("rb") as f:
        info = plistlib.load(f)
    expected = bundle_id()
    if info.get("CFBundleIdentifier") != expected:
        fail(f"Briefcase made bundle ID {info.get('CFBundleIdentifier')!r}, expected {expected!r}")
    info["CFBundleShortVersionString"] = cfg["version"]
    info["CFBundleVersion"] = build_number
    info["ITSAppUsesNonExemptEncryption"] = False      # HTTPS only: exempt, so no export-compliance prompt
    check_url_scheme(info)
    with plist_path.open("wb") as f:
        plistlib.dump(info, f)

    shutil.copyfile(PRIVACY_MANIFEST, plist_path.parent / PRIVACY_MANIFEST.name)
    add_privacy_manifest(project / "project.pbxproj", group)

    icons = list(xcode_dir.glob("*/Images.xcassets/AppIcon.appiconset/icon-1024.png"))
    if not icons:
        fail("No 1024 px app icon in the Xcode project")
    if png_has_alpha(icons[0]):
        fail("The 1024 px app icon has an alpha channel; App Store Connect rejects that. "
             "Save src/ruskimaxxing_mobile/resources/icon-1024.png without transparency.")

    out = {"bundle_id": expected, "project": str(project), "scheme": project.stem,
           "version": cfg["version"], "build": build_number}
    print(f"iOS bundle ID: {expected}")
    print(f"Version {cfg['version']} (build {build_number}); project {project}")
    return out


def check_archive(archive: Path, build_number: str | None) -> None:
    apps = list((archive / "Products" / "Applications").glob("*.app"))
    if len(apps) != 1:
        fail(f"No app inside {archive}")
    app = apps[0]
    with (app / "Info.plist").open("rb") as f:
        info = plistlib.load(f)
    problems = []
    if info.get("CFBundleIdentifier") != bundle_id():
        problems.append(f"bundle ID is {info.get('CFBundleIdentifier')}")
    if build_number and info.get("CFBundleVersion") != build_number:
        problems.append(f"build number is {info.get('CFBundleVersion')}")
    if info.get("ITSAppUsesNonExemptEncryption") is not False:
        problems.append("ITSAppUsesNonExemptEncryption isn't false")
    if not (app / "PrivacyInfo.xcprivacy").is_file():
        problems.append("PrivacyInfo.xcprivacy is missing")
    if not (app / "Assets.car").is_file():
        problems.append("compiled icons (Assets.car) are missing")
    if not (app / "Frameworks" / "Python.framework").is_dir():
        problems.append("Python.framework is missing")
    if not list((app / "app").rglob("ruskimaxxing_mobile/app.py")):
        problems.append("the app's Python code is missing")
    try:
        check_url_scheme(info)
    except SystemExit:
        problems.append("URL scheme missing")
    if problems:
        fail("Archive check failed: " + "; ".join(problems))
    print(f"Archive OK: {info['CFBundleIdentifier']} {info['CFBundleShortVersionString']} "
          f"({info['CFBundleVersion']}), privacy manifest, icons, Python and app code present")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("bundle-id")
    p = sub.add_parser("project")
    p.add_argument("--build-number", required=True)
    p.add_argument("--xcode-dir", type=Path, default=ROOT / "build" / APP / "ios" / "xcode")
    c = sub.add_parser("check-archive")
    c.add_argument("archive", type=Path)
    c.add_argument("--build-number")
    args = parser.parse_args(argv)

    if args.cmd == "bundle-id":
        print(bundle_id())
    elif args.cmd == "project":
        out = prepare_project(args.xcode_dir, args.build_number)
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
                f.writelines(f"{k}={v}\n" for k, v in out.items())
    else:
        check_archive(args.archive, args.build_number)


if __name__ == "__main__":
    main()
