from ruskimaxxing import __version__
from ruskimaxxing.storage import Store
from ruskimaxxing.updates import check_for_update, dismiss, dismissed, newer_release, parse

REL = {"tag_name": "v99.1.0", "html_url": "https://github.com/x/releases/tag/v99.1.0", "assets": [
    {"name": "RuskiMaxxing-Windows.exe", "browser_download_url": "https://dl/win.exe"},
    {"name": "RuskiMaxxing-Android.apk", "browser_download_url": "https://dl/app.apk"},
    {"name": "RuskiMaxxing.xlsx", "browser_download_url": "https://dl/book.xlsx"}]}


def test_parse_and_compare():
    assert parse("v2.10.0") > parse("2.9.3") and parse("v2.2.0") == (2, 2, 0)
    assert newer_release({**REL, "tag_name": f"v{__version__}"}, "windows") is None
    assert newer_release({**REL, "prerelease": True}, "windows") is None


def test_picks_platform_download():
    assert newer_release(REL, "windows").url == "https://dl/win.exe"
    assert newer_release(REL, "android").url == "https://dl/app.apk"
    assert newer_release(REL, "linux").url == REL["html_url"]      # no Linux asset: release page


def test_check_once_a_day_and_dismiss(tmp_path):
    store, calls = Store(tmp_path / "d.db"), []

    def fetch(repo):
        calls.append(repo)
        return REL
    update = check_for_update(store, "android", fetch=fetch)
    assert update.version == "99.1.0" and update.url == "https://dl/app.apk"
    assert check_for_update(store, "android", fetch=fetch).version == "99.1.0" and len(calls) == 1   # cached
    check_for_update(store, "android", force=True, fetch=fetch)
    assert len(calls) == 2
    assert not dismissed(store, update)
    dismiss(store, update)
    assert dismissed(store, update)


def test_offline_is_quiet(tmp_path):
    def fetch(repo):
        raise OSError("no network")
    assert check_for_update(Store(tmp_path / "d.db"), "windows", force=True, fetch=fetch) is None
