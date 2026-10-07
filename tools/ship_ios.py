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

import json
import os
import re
import shutil
import subprocess
import sys
import time
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = "andrewsdillon-design/ruskimaxxing"
BRANCH = "main"
WORKFLOW = "testflight.yml"
REPO_DIR = Path(os.environ.get("USERPROFILE") or Path.home()) / "ruskimaxxing"
SECRETS = ("ASC_ISSUER_ID", "ASC_KEY_ID", "ASC_KEY_P8")
TEAM = "GA9A5J9A44 (Dillon REA Andrews)"
APP_NAME = "RuskiMaxxing"
SKU = "ruskimaxxing-ios"
KEYS_PAGE = "https://appstoreconnect.apple.com/access/integrations/api"
APPS_PAGE = "https://appstoreconnect.apple.com/apps"
WIN_DIRS = {  # where winget puts these, so they work in this window right after installing
    "git": [r"%ProgramFiles%\Git\cmd"],
    "gh": [r"%ProgramFiles%\GitHub CLI", r"%LOCALAPPDATA%\Programs\GitHub CLI"],
}


# ----- small helpers ------------------------------------------------------------------
def say(text: str = "") -> None:
    print(text, flush=True)


def step(title: str) -> None:
    say()
    say("=" * 70)
    say("  " + title)
    say("=" * 70)


def ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:
        return ""


def wait_enter(prompt: str = "Press Enter when that's done (or type q to quit): ") -> None:
    if ask(prompt).lower() in ("q", "quit", "exit"):
        sys.exit("Stopped. Double-click SHIP_TO_TESTFLIGHT.bat to carry on later.")


def run(cmd, check=True, capture=False, input_text=None, cwd=None) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, cwd=cwd, text=True, input=input_text,
                            stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.PIPE if capture else None)
    if check and result.returncode:
        detail = (result.stderr or result.stdout or "").strip() if capture else ""
        sys.exit(f"\nThis failed: {' '.join(map(str, cmd[:3]))} ...\n{detail}")
    return result


def gh(*args, **kw) -> subprocess.CompletedProcess:
    return run(["gh", *args], **kw)


def find_tool(name: str) -> bool:
    if shutil.which(name):
        return True
    for d in WIN_DIRS.get(name, []):
        d = os.path.expandvars(d)
        if Path(d, name + ".exe").exists():
            os.environ["PATH"] = d + os.pathsep + os.environ["PATH"]
            return True
    return False


def ensure_tool(name: str, winget_id: str) -> None:
    if find_tool(name):
        return
    if os.name != "nt" or not shutil.which("winget"):
        sys.exit(f"Please install {name} first (https://cli.github.com for gh, https://git-scm.com for git).")
    say(f"Installing {name} with winget...")
    run(["winget", "install", "-e", "--id", winget_id, "--accept-source-agreements",
         "--accept-package-agreements"], check=False)
    if not find_tool(name):
        sys.exit(f"{name} was installed but this window can't see it yet. Close this window and "
                 "double-click SHIP_TO_TESTFLIGHT.bat again.")


def bundle_id(repo_dir: Path) -> str:
    """Same rule as tools/ios_prepare.py (Briefcase turns '_' into '-' in the iOS bundle ID)."""
    text = (repo_dir / "pyproject.toml").read_text(encoding="utf-8")
    section = text.split("[tool.briefcase]", 1)[1]
    bundle = re.search(r'^bundle\s*=\s*"([^"]+)"', section, re.M).group(1)
    app = re.search(r"^\[tool\.briefcase\.app\.(\w+)\]", section, re.M).group(1)
    return f"{bundle}.{app.replace('_', '-').lower()}"


# ----- 1. tools, repo, GitHub sign-in ----------------------------------------------------
def update_repo() -> None:
    if (REPO_DIR / ".git").exists():
        say(f"Updating {REPO_DIR} ...")
        dirty = run(["git", "-C", str(REPO_DIR), "status", "--porcelain"], capture=True).stdout.strip()
        if dirty:
            say("  (you have local changes there, so it isn't updated; that's fine for shipping)")
            return
        run(["git", "-C", str(REPO_DIR), "checkout", "-q", BRANCH], check=False)
        run(["git", "-C", str(REPO_DIR), "pull", "-q", "--ff-only", "origin", BRANCH], check=False)
    else:
        say(f"Downloading the project to {REPO_DIR} ...")
        run(["git", "clone", "-q", f"https://github.com/{REPO}.git", str(REPO_DIR)])


def run_latest_copy() -> None:
    """Always run the newest version of this script (the one in the freshly updated repo)."""
    latest = REPO_DIR / "tools" / "ship_ios.py"
    if os.environ.get("RM_SHIP_LATEST") or not latest.exists():
        return
    os.environ["RM_SHIP_LATEST"] = "1"
    sys.exit(subprocess.run([sys.executable, str(latest)]).returncode)


def github_login() -> None:
    if gh("auth", "status", "--hostname", "github.com", check=False, capture=True).returncode == 0:
        return
    step("Sign in to GitHub")
    say("Your browser opens. Copy the 8-character code shown here, paste it on the GitHub page,")
    say("and approve. Answer any questions here with Enter (the defaults are right).")
    gh("auth", "login", "--hostname", "github.com", "--git-protocol", "https", "--web")


def workflow_on_main() -> bool:
    return gh("api", f"repos/{REPO}/contents/.github/workflows/{WORKFLOW}?ref={BRANCH}", "--silent",
              check=False, capture=True).returncode == 0


def require_workflow() -> None:
    while not workflow_on_main():
        step("One thing first: merge the pull request")
        say("GitHub only lets you start the TestFlight build once it's on the main branch.")
        say("Opening the pull requests page: open the 'Ship the iPhone app to TestFlight' one and")
        say("click 'Merge pull request' (if it says Draft, click 'Ready for review' first).")
        webbrowser.open(f"https://github.com/{REPO}/pulls")
        wait_enter("Press Enter after merging (or type q to quit): ")
        update_repo()


# ----- 2. App Store Connect API key -> GitHub secrets ------------------------------------
def secrets_present() -> bool:
    out = gh("secret", "list", "-R", REPO, capture=True).stdout
    names = {line.split()[0] for line in out.splitlines() if line.strip()}
    return all(s in names for s in SECRETS)


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
        gh("secret", "set", name, "-R", REPO, input_text=value, capture=True)
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
def start_run(preflight_only: bool) -> tuple[int, str]:
    started = datetime.now(timezone.utc) - timedelta(seconds=30)
    gh("workflow", "run", WORKFLOW, "-R", REPO, "--ref", BRANCH,
       "-f", f"preflight_only={'true' if preflight_only else 'false'}", capture=True)
    for _ in range(40):  # the run takes a few seconds to appear
        time.sleep(3)
        out = gh("run", "list", "-R", REPO, "-w", WORKFLOW, "-e", "workflow_dispatch", "-L", "5",
                 "--json", "databaseId,createdAt,url", capture=True, check=False).stdout or "[]"
        runs = [r for r in json.loads(out)
                if datetime.fromisoformat(r["createdAt"].replace("Z", "+00:00")) >= started]
        if runs:
            newest = max(runs, key=lambda r: r["createdAt"])
            return newest["databaseId"], newest["url"]
    sys.exit(f"Started the build but couldn't find it. Look here: https://github.com/{REPO}/actions")


def follow(preflight_only: bool) -> tuple[bool, str, str]:
    run_id, url = start_run(preflight_only)
    say(f"Following it live (you can also watch at {url})")
    ok = gh("run", "watch", str(run_id), "-R", REPO, "--exit-status", "--interval", "10",
            check=False).returncode == 0
    log = "" if ok else (gh("run", "view", str(run_id), "-R", REPO, "--log-failed",
                            capture=True, check=False).stdout or "")
    return ok, log, url


def explain_failure(log: str, url: str) -> None:
    lines = [ln.split("\t")[-1] for ln in log.splitlines() if ln.strip()]
    say()
    say("---- last lines of the failing step ----")
    for line in lines[-40:]:
        say(line[:200])
    say("-----------------------------------------")
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
    ensure_tool("git", "Git.Git")
    ensure_tool("gh", "GitHub.cli")
    if not os.environ.get("RM_SHIP_LATEST"):
        update_repo()
        run_latest_copy()
    github_login()
    require_workflow()
    bid = bundle_id(REPO_DIR if REPO_DIR.exists() else Path(__file__).resolve().parent.parent)
    say(f"iPhone app bundle ID: {bid}   Apple team: {TEAM}")

    if not secrets_present():
        setup_keys()
    elif ask("Apple API key already set up. Press Enter to ship (or type k to enter a new key): ").lower() == "k":
        setup_keys()

    while True:
        step("Checking the Apple setup on GitHub (about 1 minute)")
        ok, log, url = follow(preflight_only=True)
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
    ok, log, url = follow(preflight_only=False)
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
