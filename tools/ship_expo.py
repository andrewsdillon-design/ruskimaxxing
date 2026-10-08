"""Build the RuskiMaxxing phone app (mobile/, Expo) in Expo's cloud and send it to TestFlight. One command.

    python tools/ship_expo.py                  # iPhone: build and submit to App Store Connect / TestFlight
    python tools/ship_expo.py android          # Android: build an installable APK (download link at the end)
    python tools/ship_expo.py ios --no-submit  # build only
    python tools/ship_expo.py ios --dry-run    # everything except the cloud build

SHIP_TO_TESTFLIGHT.bat runs this. Steps: install packages, run TypeScript and the tests, sign in to Expo as
dandrews91, create the Expo project the first time (and save its ID in mobile/eas-project.json), then build
with EAS. iPhone builds are locked to your Apple team (Dillon REA Andrews, GA9A5J9A44). The first iPhone build
asks for your Apple ID password and the 6-digit code from your iPhone so EAS can make the signing certificate;
after that it doesn't. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "mobile"
PROJECT_FILE = APP / "eas-project.json"

EXPO_ACCOUNT = "dandrews91"
APPLE_ID = "andrews.dillon@gmail.com"
APPLE_TEAM_ID = "GA9A5J9A44"  # Dillon REA Andrews (Individual)
APPLE_TEAM_NAME = "Dillon REA Andrews (Individual)"
EAS = "npx --yes eas-cli@latest"
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def say(title: str) -> None:
    print(f"\n=== {title} ===", flush=True)


def fail(message: str) -> None:
    print(f"\nStopped: {message}", flush=True)
    sys.exit(1)


def run(cmd: str, env: dict | None = None, capture: bool = False, cwd: Path = APP) -> subprocess.CompletedProcess:
    """Run a command in mobile/. Interactive unless captured, so Apple's prompts reach you."""
    print(f"> {cmd}", flush=True)
    return subprocess.run(cmd, cwd=cwd, shell=True, env=env or os.environ.copy(), text=True, capture_output=capture)


def need(tool: str, hint: str) -> None:
    if not shutil.which(tool):
        fail(f"{tool} isn't installed. {hint}")


def install() -> None:
    say("Installing packages")
    if run("npm ci" if (APP / "package-lock.json").exists() else "npm install").returncode != 0:
        fail("package install failed (see above).")


def checks() -> None:
    say("Checking the code: TypeScript and tests")
    if run("npx tsc --noEmit").returncode != 0:
        fail("TypeScript found errors. Fix them before building.")
    if run("npx jest").returncode != 0:
        fail("tests failed. Fix them before building.")


def expo_login() -> None:
    say("Expo account")
    who = run(f"{EAS} whoami", capture=True)
    user = (who.stdout or "").strip().splitlines()[0].split()[0] if who.returncode == 0 and who.stdout.strip() else ""
    if user and user != EXPO_ACCOUNT:
        print(f"Signed in to Expo as {user}, but this app belongs to {EXPO_ACCOUNT}. Signing out first.")
        run(f"{EAS} logout")
        user = ""
    if not user:
        print(f"Sign in to Expo as {EXPO_ACCOUNT} ({APPLE_ID}).")
        if run(f"{EAS} login").returncode != 0:
            fail("Expo sign-in failed.")
    print(f"Expo: {EXPO_ACCOUNT}")


def project_id() -> str:
    try:
        return json.loads(PROJECT_FILE.read_text(encoding="utf-8")).get("projectId", "")
    except (OSError, ValueError):
        return ""


def ensure_project(dry_run: bool) -> None:
    """Create (or find) the 'ruskimaxxing' project on Expo the first time, and keep its ID in git."""
    if project_id():
        print(f"Expo project: {project_id()}")
        return
    say("Creating the Expo project (first time only)")
    if dry_run:
        print(f"(dry run) would run: {EAS} init --account {EXPO_ACCOUNT} --json --non-interactive")
        return
    out = run(f"{EAS} init --account {EXPO_ACCOUNT} --json --non-interactive", capture=True)
    found = UUID.search((out.stdout or "") + (out.stderr or ""))
    if not found:
        print(out.stdout, out.stderr)
        fail("couldn't create the Expo project (see above).")
    PROJECT_FILE.write_text(json.dumps({"projectId": found.group(0)}, indent=2) + "\n", encoding="utf-8")
    print(f"Expo project: {found.group(0)} (saved in mobile/eas-project.json)")
    # keep it in git so the next build (and any other PC) uses the same project
    run(f'git add "{PROJECT_FILE}"', cwd=ROOT)
    if run('git commit -m "Link the phone app to its Expo project" --quiet', cwd=ROOT).returncode == 0:
        if run("git push --quiet", cwd=ROOT).returncode != 0:
            print("Couldn't push that commit; it's saved locally. Push it later (or it's re-created next time).")


def build(platform: str, submit: bool, dry_run: bool) -> None:
    env = os.environ.copy()
    env["EAS_BUILD_NO_EXPO_GO_WARNING"] = "true"
    if platform == "ios":
        env["EXPO_APPLE_ID"] = APPLE_ID
        env["EXPO_APPLE_TEAM_ID"] = APPLE_TEAM_ID
        env["EXPO_APPLE_TEAM_TYPE"] = "INDIVIDUAL"
        say(f"Building for iPhone on Apple team {APPLE_TEAM_NAME}, {APPLE_TEAM_ID}")
        print(f"If Apple asks: sign in as {APPLE_ID}, enter the 6-digit code from your iPhone, pick")
        print(f"'{APPLE_TEAM_NAME}' if it lists teams, and answer yes to creating certificates and profiles.")
        cmd = f"{EAS} build --platform ios --profile production"
        if submit:
            cmd += " --auto-submit-with-profile production"
    else:
        say("Building for Android (installable APK)")
        cmd = f"{EAS} build --platform android --profile preview"
    if dry_run:
        print(f"(dry run) would run: {cmd}")
        return
    # Without prompts first (works once credentials exist), then interactively for first-time signing setup.
    if run(cmd + " --non-interactive", env=env).returncode == 0:
        return
    print("\nThe build needs your input (first-time signing setup). Running it interactively...")
    if run(cmd, env=env).returncode != 0:
        fail("the build failed. The link above shows the build log on expo.dev.")


def done(platform: str, submit: bool) -> None:
    say("Done")
    if platform == "ios" and submit:
        print("The build is uploading to App Store Connect. It appears under TestFlight in 10 to 30 minutes.")
        print("First time: App Store Connect -> RuskiMaxxing -> TestFlight -> Internal Testing -> + -> add yourself,")
        print("then install Apple's TestFlight app on your iPhone and open the invite.")
        try:
            webbrowser.open("https://appstoreconnect.apple.com/apps")
        except Exception:
            pass
    else:
        print(f"Build finished. Download it from https://expo.dev/accounts/{EXPO_ACCOUNT}/projects/ruskimaxxing/builds")


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the RuskiMaxxing phone app in Expo's cloud and send it to TestFlight.")
    ap.add_argument("platform", nargs="?", choices=["ios", "android"], default="ios")
    ap.add_argument("--no-submit", action="store_true", help="build only, don't upload to the store")
    ap.add_argument("--skip-checks", action="store_true", help="skip TypeScript and tests (not recommended)")
    ap.add_argument("--dry-run", action="store_true", help="do everything except the cloud build")
    args = ap.parse_args()

    need("node", "Install Node.js LTS from https://nodejs.org (or run SHIP_TO_TESTFLIGHT.bat, which installs it).")
    need("npm", "It comes with Node.js.")
    install()
    if not args.skip_checks:
        checks()
    expo_login()
    ensure_project(args.dry_run)
    submit = not args.no_submit
    build(args.platform, submit, args.dry_run)
    done(args.platform, submit)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nStopped.")
