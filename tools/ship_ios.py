"""Ship the RuskiMaxxing iPhone app to TestFlight from a Windows PC (no Mac needed).

Double-click SHIP_TO_TESTFLIGHT.bat, which runs this. Standard library only. It:
  1. installs the GitHub CLI if it's missing, clones/updates the repo into %USERPROFILE%\\ruskimaxxing
     and signs you in to GitHub (browser) if needed;
  2. the first time only: walks you through making an App Store Connect API key and stores it as
     GitHub repo secrets (never printed, never saved anywhere else);
  3. runs a quick Apple check on GitHub (registers the bundle ID, checks the App Store Connect app
     exists - and if it doesn't, tells you exactly what to type into "New App");
  4. runs the real build on GitHub's Mac, which signs it and uploads it to TestFlight, and follows it live.
"""

from __future__ import annotations

import re
import sys
import webbrowser
from pathlib import Path

import ghtools
from ghtools import REPO_DIR, ask, follow, github_login, require_workflow, say, set_secret, step, wait_enter

WORKFLOW = "testflight.yml"
SECRETS = ("ASC_ISSUER_ID", "ASC_KEY_ID", "ASC_KEY_P8")
TEAM = "GA9A5J9A44 (Dillon REA Andrews)"
APP_NAME = "RuskiMaxxing"
SKU = "ruskimaxxing-ios"
KEYS_PAGE = "https://appstoreconnect.apple.com/access/integrations/api"
APPS_PAGE = "https://appstoreconnect.apple.com/apps"
ghtools.BAT = "SHIP_TO_TESTFLIGHT.bat"


def bundle_id(repo_dir: Path) -> str:
    """Same rule as tools/ios_prepare.py (Briefcase turns '_' into '-' in the iOS bundle ID)."""
    text = (repo_dir / "pyproject.toml").read_text(encoding="utf-8")
    section = text.split("[tool.briefcase]", 1)[1]
    bundle = re.search(r'^bundle\s*=\s*"([^"]+)"', section, re.M).group(1)
    app = re.search(r"^\[tool\.briefcase\.app\.(\w+)\]", section, re.M).group(1)
    return f"{bundle}.{app.replace('_', '-').lower()}"


# ----- 2. App Store Connect API key -> GitHub secrets ------------------------------------
def secrets_present() -> bool:
    return set(SECRETS) <= ghtools.secret_names()


def pick_p8() -> str:
    path = ""
    try:
        import tkinter
        from tkinter import filedialog
        root = tkinter.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askopenfilename(
            title="Pick the AuthKey_XXXXXXXXXX.p8 file you just downloaded",
            initialdir=str(Path.home() / "Downloads"), filetypes=[("App Store Connect API key", "*.p8")])
        root.destroy()
    except Exception:  # no tkinter: type the path instead
        pass
    return path or ask("Path to the .p8 file: ").strip('"')


def setup_keys() -> None:
    step("One-time setup: App Store Connect API key (about 3 minutes)")
    say("This lets GitHub's Mac sign and upload the app for you. Your browser opens App Store Connect.")
    say("Sign in with your Apple ID (andrews.dillon@gmail.com), then:")
    say()
    say("  1. You should be on Users and Access -> Integrations -> App Store Connect API.")
    say("     (If not: click 'Users and Access' at the top, then the 'Integrations' tab,")
    say("      then 'App Store Connect API' on the left, and pick 'Team Keys'.)")
    say("  2. First time only: click 'Request Access', tick the box and submit. It's instant.")
    say("  3. Click 'Generate API Key' (or the + button).")
    say("     Name: RuskiMaxxing GitHub     Access: Admin")
    say("     (Admin is needed: with App Manager, Apple refuses to make the signing certificate")
    say("      on GitHub's Mac - 'cloud signing permission error'.)")
    say("  4. Click Generate. In the table you now see:")
    say("       - Issuer ID: above the table, with a Copy button")
    say("       - Key ID: in your new key's row")
    say("  5. Click 'Download' on that row. Apple lets you download it ONLY ONCE, so keep the")
    say("     AuthKey_XXXXXXXXXX.p8 file (it lands in your Downloads folder).")
    say()
    webbrowser.open(KEYS_PAGE)

    while True:
        issuer = ask("Paste the Issuer ID and press Enter: ").lower()
        if re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", issuer):
            break
        say("  That doesn't look like an Issuer ID (like 69a6de7e-1234-47e3-e053-5b8c7c11a4d1). Try again.")
    while True:
        key_id = ask("Paste the Key ID and press Enter: ").upper()
        if re.fullmatch(r"[A-Z0-9]{10}", key_id):
            break
        say("  A Key ID is 10 letters/digits, like 2X9R4HXF34. Try again.")
    while True:
        say("Now pick the .p8 file you downloaded (a file window opens; it may be behind this one).")
        path = pick_p8()
        try:
            key = Path(path).read_text(encoding="utf-8").strip()
        except OSError:
            key = ""
        if "BEGIN PRIVATE KEY" in key:
            break
        say("  That isn't an App Store Connect .p8 key file. Try again.")
    if key_id not in Path(path).name:
        say(f"  Note: the file name doesn't contain {key_id}; make sure it's the key from the same row.")

    say("Saving them as encrypted GitHub secrets (they're never shown or saved anywhere else)...")
    for name, value in (("ASC_ISSUER_ID", issuer), ("ASC_KEY_ID", key_id), ("ASC_KEY_P8", key)):
        set_secret(name, value)
    say("Saved. You can delete the .p8 from Downloads now, or keep it somewhere safe as a backup.")


def new_app_guide(bid: str) -> None:
    step("One-time setup: create the app in App Store Connect")
    say("GitHub just registered the bundle ID with Apple, so it's now in the New App list.")
    say("Your browser opens App Store Connect -> Apps. Click the blue + (top left) -> New App, and enter:")
    say()
    say("   Platforms ........ iOS (tick only iOS)")
    say(f"   Name ............. {APP_NAME}   (must be unique on the App Store; if it's taken,")
    say(f"                      try '{APP_NAME}: Strength Program' - you can change it later)")
    say("   Primary Language . English (U.S.)")
    say(f"   Bundle ID ........ {APP_NAME} - {bid}")
    say(f"                      (exactly {bid} - note the dash, not an underscore)")
    say(f"   SKU .............. {SKU}")
    say("   User Access ...... Full Access")
    say()
    say("Then click Create. (If the Bundle ID isn't in the list yet, wait a minute and reload the page.)")
    webbrowser.open(APPS_PAGE)
    wait_enter("Press Enter once you've clicked Create (or type q to quit): ")


# ----- 3/4. run the workflow on GitHub and follow it -------------------------------------
def explain_failure(log: str, url: str) -> None:
    ghtools.show_log_tail(log)
    low = log.lower()
    if "cloud signing permission" in low or "api_key_role" in low or "requires the admin role" in low:
        hint = ("The API key needs the Admin role. Make a new key with Access: Admin, then run this again "
                "and type k to enter the new key.")
    elif "agreement" in low:
        hint = ("Apple wants you to accept an updated agreement. Sign in at https://developer.apple.com/account "
                "and https://appstoreconnect.apple.com, accept any banner agreements, then run this again.")
    elif "bundle version" in low or "cfbundleversion" in low:
        hint = "That build number was already used. Just run this again (each run gets a higher number)."
    elif "no suitable application records" in low or "app_record_missing" in low:
        hint = "The App Store Connect app isn't set up for this bundle ID yet. Run this again and follow the steps."
    else:
        hint = f"Open {url} to see the whole log, or send that link to whoever helps you with the code."
    say("What to do: " + hint)


def main() -> None:
    step("RuskiMaxxing -> TestFlight")
    ghtools.start("ship_ios.py")
    github_login()
    require_workflow(WORKFLOW)
    bid = bundle_id(REPO_DIR if REPO_DIR.exists() else Path(__file__).resolve().parent.parent)
    say(f"iPhone app bundle ID: {bid}   Apple team: {TEAM}")

    if not secrets_present():
        setup_keys()
    elif ask("Apple API key already set up. Press Enter to ship (or type k to enter a new key): ").lower() == "k":
        setup_keys()

    while True:
        step("Checking the Apple setup on GitHub (about 1 minute)")
        ok, log, url = follow(WORKFLOW, {"preflight_only": "true"})
        if ok:
            break
        if "APP_RECORD_MISSING" in log:
            new_app_guide(bid)
            continue
        explain_failure(log, url)
        if "API_KEY_REJECTED" in log or "API_KEY_ROLE" in log:
            if ask("Enter the API key details again? (y/n): ").lower().startswith("y"):
                setup_keys()
                continue
        sys.exit(1)

    step("Building, signing and uploading on GitHub's Mac (about 15-25 minutes)")
    say("You can leave this window open and do something else.")
    ok, log, url = follow(WORKFLOW, {"preflight_only": "false"})
    if not ok:
        explain_failure(log, url)
        sys.exit(1)
    step("Done - uploaded to App Store Connect")
    say("Apple now processes the build. It shows up in TestFlight in about 10-30 minutes:")
    say(f"  {APPS_PAGE} -> {APP_NAME} -> TestFlight")
    say("First time only: in TestFlight, click 'Internal Testing' -> + -> add yourself as a tester.")
    say("Then install Apple's free 'TestFlight' app on your iPhone and open the invite email.")
    say("Apple emails you when processing finishes (or if it finds a problem with the build).")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nStopped.")
