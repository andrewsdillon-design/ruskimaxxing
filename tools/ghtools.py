"""Shared helpers for the one-click Windows scripts (SHIP_TO_TESTFLIGHT.bat, DEPLOY_SERVER.bat).

Standard library only. They install Git / the GitHub CLI if needed, keep %USERPROFILE%\\ruskimaxxing up
to date, sign in to GitHub, store repo secrets, and start + follow a GitHub Actions workflow.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = "andrewsdillon-design/ruskimaxxing"
BRANCH = "main"
REPO_DIR = Path(os.environ.get("USERPROFILE") or Path.home()) / "ruskimaxxing"
WIN_DIRS = {  # where winget puts these, so they work in this window right after installing
    "git": [r"%ProgramFiles%\Git\cmd"],
    "gh": [r"%ProgramFiles%\GitHub CLI", r"%LOCALAPPDATA%\Programs\GitHub CLI"],
    "ssh": [r"%SystemRoot%\System32\OpenSSH"],
    "ssh-keygen": [r"%SystemRoot%\System32\OpenSSH"],
}
BAT = "the .bat file"  # set by each script, for messages like "double-click ... again"


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
        sys.exit(f"Stopped. Double-click {BAT} to carry on later.")


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
                 f"double-click {BAT} again.")


# ----- tools, repo, GitHub sign-in --------------------------------------------------------
def update_repo() -> None:
    if (REPO_DIR / ".git").exists():
        say(f"Updating {REPO_DIR} ...")
        dirty = run(["git", "-C", str(REPO_DIR), "status", "--porcelain"], capture=True).stdout.strip()
        if dirty:
            say("  (you have local changes there, so it isn't updated; that's fine for this)")
            return
        run(["git", "-C", str(REPO_DIR), "checkout", "-q", BRANCH], check=False)
        run(["git", "-C", str(REPO_DIR), "pull", "-q", "--ff-only", "origin", BRANCH], check=False)
    else:
        say(f"Downloading the project to {REPO_DIR} ...")
        run(["git", "clone", "-q", f"https://github.com/{REPO}.git", str(REPO_DIR)])


def start(script_name: str) -> None:
    """Install Git + gh, update the repo, then run the newest copy of the calling script from it."""
    ensure_tool("git", "Git.Git")
    ensure_tool("gh", "GitHub.cli")
    if os.environ.get("RM_LATEST"):
        return
    update_repo()
    latest = REPO_DIR / "tools" / script_name
    if latest.exists():
        os.environ["RM_LATEST"] = "1"
        sys.exit(subprocess.run([sys.executable, str(latest)]).returncode)


def github_login() -> None:
    if gh("auth", "status", "--hostname", "github.com", check=False, capture=True).returncode == 0:
        return
    step("Sign in to GitHub")
    say("Your browser opens. Copy the 8-character code shown here, paste it on the GitHub page,")
    say("and approve. Answer any questions here with Enter (the defaults are right).")
    gh("auth", "login", "--hostname", "github.com", "--git-protocol", "https", "--web")


def workflow_on_main(workflow: str) -> bool:
    return gh("api", f"repos/{REPO}/contents/.github/workflows/{workflow}?ref={BRANCH}", "--silent",
              check=False, capture=True).returncode == 0


def require_workflow(workflow: str) -> None:
    while not workflow_on_main(workflow):
        step("One thing first: merge the pull request")
        say(f"GitHub can only start {workflow} once it's on the main branch.")
        say("Opening the pull requests page: open the newest one and click 'Merge pull request'")
        say("(if it says Draft, click 'Ready for review' first).")
        webbrowser.open(f"https://github.com/{REPO}/pulls")
        wait_enter("Press Enter after merging (or type q to quit): ")
        update_repo()


def secret_names() -> set[str]:
    out = gh("secret", "list", "-R", REPO, capture=True).stdout
    return {line.split()[0] for line in out.splitlines() if line.strip()}


def set_secret(name: str, value: str) -> None:
    """Stored encrypted on GitHub; the value goes in on stdin, so it's never shown or saved anywhere."""
    gh("secret", "set", name, "-R", REPO, input_text=value, capture=True)


# ----- run a workflow on GitHub and follow it ------------------------------------------
def start_run(workflow: str, fields: dict[str, str] | None = None) -> tuple[int, str]:
    started = datetime.now(timezone.utc) - timedelta(seconds=30)
    args = ["workflow", "run", workflow, "-R", REPO, "--ref", BRANCH]
    for key, value in (fields or {}).items():
        args += ["-f", f"{key}={value}"]
    gh(*args, capture=True)
    for _ in range(40):  # the run takes a few seconds to appear
        time.sleep(3)
        out = gh("run", "list", "-R", REPO, "-w", workflow, "-e", "workflow_dispatch", "-L", "5",
                 "--json", "databaseId,createdAt,url", capture=True, check=False).stdout or "[]"
        runs = [r for r in json.loads(out)
                if datetime.fromisoformat(r["createdAt"].replace("Z", "+00:00")) >= started]
        if runs:
            newest = max(runs, key=lambda r: r["createdAt"])
            return newest["databaseId"], newest["url"]
    sys.exit(f"Started it but couldn't find the run. Look here: https://github.com/{REPO}/actions")


def follow(workflow: str, fields: dict[str, str] | None = None) -> tuple[bool, str, str]:
    """Start the workflow and watch it live. Returns (ok, log of the failed steps, run URL)."""
    run_id, url = start_run(workflow, fields)
    say(f"Following it live (you can also watch at {url})")
    ok = gh("run", "watch", str(run_id), "-R", REPO, "--exit-status", "--interval", "10",
            check=False).returncode == 0
    log = "" if ok else (gh("run", "view", str(run_id), "-R", REPO, "--log-failed",
                            capture=True, check=False).stdout or "")
    return ok, log, url


def show_log_tail(log: str, lines: int = 40) -> None:
    say()
    say("---- last lines of the failing step ----")
    for line in [ln.split("\t")[-1] for ln in log.splitlines() if ln.strip()][-lines:]:
        say(line[:200])
    say("-----------------------------------------")
