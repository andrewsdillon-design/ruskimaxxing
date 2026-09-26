"""Check GitHub Releases for a newer version of this app (standard library only, works on phones).

    update = check_for_update(store)          # at most once a day unless force=True
    if update:
        print(update.version, update.url)     # url = the download for this platform (or the release page)
"""

import json
import sys
import time
import urllib.request
from dataclasses import dataclass

from ruskimaxxing import __version__
from ruskimaxxing.edition import EDITION

REPOS = {"standard": "andrewsdillon-design/ruskimaxxing",
         "supertotal": "andrewsdillon-design/ruskimaxxingsupertotal"}
# release asset name ends with this for each platform
ASSETS = {"windows": "Windows.exe", "macos": "macOS.zip", "linux": "Linux.tar.gz", "android": "Android.apk"}
CHECK_EVERY = 20 * 3600  # seconds


@dataclass
class Update:
    version: str   # "2.3.0"
    url: str       # direct download for this platform, or the release page
    page: str      # release page (what's new)


def parse(version: str) -> tuple[int, ...]:
    parts = []
    for p in version.strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits or 0))
    return tuple(parts)


def desktop_platform() -> str:
    return "windows" if sys.platform.startswith("win") else "macos" if sys.platform == "darwin" else "linux"


def fetch_latest(repo: str) -> dict:
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/releases/latest",
                                 headers={"Accept": "application/vnd.github+json",
                                          "User-Agent": f"RuskiMaxxing/{__version__}"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def newer_release(release: dict, platform: str, current: str = __version__) -> Update | None:
    tag = release.get("tag_name", "")
    if not tag or release.get("draft") or release.get("prerelease") or parse(tag) <= parse(current):
        return None
    page = release.get("html_url", "")
    url = next((a["browser_download_url"] for a in release.get("assets", [])
                if a.get("name", "").endswith(ASSETS.get(platform, "\0"))), page)
    return Update(tag.lstrip("vV"), url, page)


def check_for_update(store, platform: str | None = None, force: bool = False, fetch=fetch_latest) -> Update | None:
    """Newest release if it's newer than this app. Remembers the answer for a day; network errors return None."""
    platform = platform or desktop_platform()
    now = time.time()
    if not force and now - float(store.get("update_checked", "0") or 0) < CHECK_EVERY:
        cached = store.get("update_version", "")
        if cached and parse(cached) > parse(__version__):
            return Update(cached, store.get("update_url", ""), store.get("update_page", ""))
        return None
    try:
        update = newer_release(fetch(REPOS.get(EDITION, REPOS["standard"])), platform)
    except Exception:  # offline, rate-limited, GitHub down: try again next time
        return None
    store.set("update_checked", str(now))
    store.set("update_version", update.version if update else "")
    store.set("update_url", update.url if update else "")
    store.set("update_page", update.page if update else "")
    return update


def dismissed(store, update: Update) -> bool:
    return store.get("update_dismissed", "") == update.version


def dismiss(store, update: Update) -> None:
    store.set("update_dismissed", update.version)
