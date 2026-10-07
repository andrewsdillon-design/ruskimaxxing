"""tools/ios_prepare.py: the App Store fix-ups applied to Briefcase's generated iPhone project."""

import importlib.util
import plistlib
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("ios_prepare", ROOT / "tools" / "ios_prepare.py")
ios_prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ios_prepare)

BUNDLE_ID = "io.github.andrewsdillondesign.ruskimaxxing-mobile"

# the parts of Briefcase 0.4.5's iOS template project.pbxproj that the script edits
PBXPROJ = """// !$*UTF8*$!
{
	objects = {

/* Begin PBXBuildFile section */
		600000000000000000100200 /* Images.xcassets in Resources */ = {isa = PBXBuildFile; fileRef = 610000000000000000100800 /* Images.xcassets */; };
/* End PBXBuildFile section */

/* Begin PBXFileReference section */
		610000000000000000100800 /* Images.xcassets */ = {isa = PBXFileReference; lastKnownFileType = folder.assetcatalog; path = Images.xcassets; sourceTree = "<group>"; };
/* End PBXFileReference section */

/* Begin PBXGroup section */
		60796EEB19190F4100A9926B /* RuskiMaxxing */ = {
			isa = PBXGroup;
			children = (
				610000000000000000100800 /* Images.xcassets */,
			);
			path = "RuskiMaxxing";
			sourceTree = "<group>";
		};
/* End PBXGroup section */

/* Begin PBXResourcesBuildPhase section */
		60796EE019190F4100A9926B /* Resources */ = {
			isa = PBXResourcesBuildPhase;
			buildActionMask = 2147483647;
			files = (
				600000000000000000100200 /* Images.xcassets in Resources */,
			);
			runOnlyForDeploymentPostprocessing = 0;
		};
/* End PBXResourcesBuildPhase section */
	};
}
"""


@pytest.fixture
def xcode(tmp_path):
    (tmp_path / "RuskiMaxxing.xcodeproj").mkdir()
    (tmp_path / "RuskiMaxxing.xcodeproj" / "project.pbxproj").write_text(PBXPROJ)
    (tmp_path / "briefcase.toml").write_text(
        '[paths]\ninfo_plist_path = "RuskiMaxxing/RuskiMaxxing-Info.plist"\n')
    icons = tmp_path / "RuskiMaxxing" / "Images.xcassets" / "AppIcon.appiconset"
    icons.mkdir(parents=True)
    Image.new("RGB", (1024, 1024), "purple").save(icons / "icon-1024.png")
    info = {"CFBundleIdentifier": BUNDLE_ID, "CFBundleVersion": "1", "CFBundleShortVersionString": "0",
            "CFBundleURLTypes": [{"CFBundleURLName": "x", "CFBundleURLSchemes": ["ruskimaxxing"]}]}
    with (tmp_path / "RuskiMaxxing" / "RuskiMaxxing-Info.plist").open("wb") as f:
        plistlib.dump(info, f)
    return tmp_path


def test_bundle_id_is_app_store_safe():
    assert ios_prepare.bundle_id() == BUNDLE_ID   # Briefcase turns ruskimaxxing_mobile into ruskimaxxing-mobile


def test_prepare_project(xcode, capsys):
    out = ios_prepare.prepare_project(xcode, "42.1")
    assert out["bundle_id"] == BUNDLE_ID and out["scheme"] == "RuskiMaxxing"
    assert f"iOS bundle ID: {BUNDLE_ID}" in capsys.readouterr().out
    with (xcode / "RuskiMaxxing" / "RuskiMaxxing-Info.plist").open("rb") as f:
        info = plistlib.load(f)
    assert info["CFBundleVersion"] == "42.1"
    assert info["CFBundleShortVersionString"] == ios_prepare.briefcase_config()[0]["version"]
    assert info["ITSAppUsesNonExemptEncryption"] is False
    assert (xcode / "RuskiMaxxing" / "PrivacyInfo.xcprivacy").is_file()
    pbx = (xcode / "RuskiMaxxing.xcodeproj" / "project.pbxproj").read_text()
    assert pbx.count(ios_prepare.FILE_REF) == 3 and pbx.count(ios_prepare.BUILD_FILE) == 2
    ios_prepare.prepare_project(xcode, "42.2")      # running again doesn't add it twice
    assert (xcode / "RuskiMaxxing.xcodeproj" / "project.pbxproj").read_text() == pbx


def test_privacy_manifest_is_valid():
    with ios_prepare.PRIVACY_MANIFEST.open("rb") as f:
        manifest = plistlib.load(f)
    assert manifest["NSPrivacyTracking"] is False
    kinds = {a["NSPrivacyAccessedAPIType"] for a in manifest["NSPrivacyAccessedAPITypes"]}
    assert {"NSPrivacyAccessedAPICategoryFileTimestamp", "NSPrivacyAccessedAPICategoryDiskSpace"} <= kinds


def test_rejects_icon_with_alpha(xcode):
    icon = next(xcode.glob("*/Images.xcassets/AppIcon.appiconset/icon-1024.png"))
    Image.new("RGBA", (1024, 1024)).save(icon)
    with pytest.raises(SystemExit):
        ios_prepare.prepare_project(xcode, "1")


def test_rejects_bad_build_number(xcode):
    with pytest.raises(SystemExit):
        ios_prepare.prepare_project(xcode, "build-7")


def test_real_app_icon_has_no_alpha():
    assert not ios_prepare.png_has_alpha(ROOT / "src" / "ruskimaxxing_mobile" / "resources" / "icon-1024.png")


def test_windows_script_agrees_on_bundle_id(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tools"))   # ship_ios imports ghtools from next to it
    spec = importlib.util.spec_from_file_location("ship_ios", ROOT / "tools" / "ship_ios.py")
    ship_ios = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ship_ios)
    assert ship_ios.bundle_id(ROOT) == BUNDLE_ID
