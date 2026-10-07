"""Deploy RuskiMaxxing Cloud (api.ruskimaxxing.com) from a Windows PC with one double-click.

Double-click DEPLOY_SERVER.bat, which runs this. Standard library only. It:
  1. installs Git / the GitHub CLI if missing, updates %USERPROFILE%\\ruskimaxxing, signs in to GitHub;
  2. the first time only: makes an SSH key just for GitHub, logs in to your server once (you type your
     server password) to deploy right away and install that key - locked so it can ONLY run the deploy -
     and stores it as GitHub secrets (the private key isn't kept on this PC);
  3. runs the "Deploy server" workflow: server tests, then deploy, then a health check, and follows it live.
"""

from __future__ import annotations

import base64
import re
import shlex
import shutil
import sys
import tempfile
from pathlib import Path

import ghtools
from ghtools import REPO_DIR, ask, follow, github_login, require_workflow, run, say, set_secret, step, wait_enter

WORKFLOW = "deploy-server.yml"
SECRETS = ("DEPLOY_HOST", "DEPLOY_USER", "DEPLOY_SSH_KEY", "DEPLOY_KNOWN_HOSTS")
DEFAULT_HOST = "api.ruskimaxxing.com"
ENABLE_SCRIPT = Path("server") / "deploy" / "enable_github_deploy.sh"
ghtools.BAT = "DEPLOY_SERVER.bat"


def ask_default(prompt: str, default: str, pattern: str, example: str) -> str:
    while True:
        value = ask(f"{prompt} [{default}]: " if default else f"{prompt}: ") or default
        if re.fullmatch(pattern, value):
            return value
        say(f"  That doesn't look right (example: {example}). Try again.")


def remote_command(user: str, domain: str, email: str, pubkey: str, script: bytes) -> str:
    """One shell line for the server: unpack enable_github_deploy.sh and run it with sudo."""
    blob = base64.b64encode(script).decode()
    args = " ".join(shlex.quote(a) for a in (user, domain, email, pubkey))
    return (f"echo {blob} | base64 -d > /tmp/rmx-enable-deploy.sh && sudo bash /tmp/rmx-enable-deploy.sh {args}; "
            "rc=$?; rm -f /tmp/rmx-enable-deploy.sh; exit $rc")


def setup() -> None:
    step("One-time setup: let GitHub deploy your server (about 5 minutes)")
    if not (ghtools.find_tool("ssh") and ghtools.find_tool("ssh-keygen")):
        sys.exit("Windows' SSH client is missing. Open Settings -> System -> Optional features -> Add a feature -> "
                 "'OpenSSH Client', install it, then double-click DEPLOY_SERVER.bat again.")
    say("You'll log in to your server ONCE, the same way you did when you installed it. That login")
    say("deploys the latest version right away and lets GitHub run the deploy from then on. GitHub gets")
    say("its own key that can only run the deploy command - not a shell, nothing else.")
    say()
    host = ask_default("Server address", DEFAULT_HOST, r"[A-Za-z0-9.-]+", DEFAULT_HOST)
    user = ask_default("User you log in to the server with", "root", r"[a-z_][a-z0-9_-]*", "root")
    domain = ask_default("The API's web address (domain)", host if not re.fullmatch(r"[\d.]+", host) else
                         DEFAULT_HOST, r"[A-Za-z0-9.-]+", DEFAULT_HOST)
    email = ask_default("The email you used when installing the server (for the HTTPS certificate)", "",
                        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+", "you@example.com")

    tmp = Path(tempfile.mkdtemp(prefix="rmx-deploy-"))
    try:
        key, known = tmp / "github_deploy_key", tmp / "known_hosts"
        run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "ruskimaxxing-github-deploy", "-f", str(key)],
            capture=True)
        pubkey = key.with_suffix(".pub").read_text(encoding="utf-8").strip()
        script = (REPO_DIR / ENABLE_SCRIPT).read_bytes().replace(b"\r\n", b"\n")
        command = remote_command(user, domain, email, pubkey, script)

        step(f"Logging in to {user}@{host}")
        say("If it asks 'Are you sure you want to continue connecting', that's normal the first time.")
        say("Type your server password when asked (nothing shows while you type), then press Enter.")
        say("If you use sudo, it may ask for that password too. The deploy then runs (1-3 minutes).")
        say()
        ok = run(["ssh", "-t", "-o", "StrictHostKeyChecking=accept-new", "-o", f"UserKnownHostsFile={known}",
                  f"{user}@{host}", command], check=False).returncode == 0
        if not ok:
            step("That didn't work - do it from your server's web console instead")
            say("Open your VPS provider's web console (or however you normally get a terminal on the server),")
            say("log in, and paste this whole line (it's long - copy all of it), then press Enter:")
            say()
            say(command)
            say()
            wait_enter("Press Enter here once it says 'Done. GitHub can now deploy' (or type q to quit): ")
        if not known.exists() or not known.read_text(encoding="utf-8").strip():
            out = run(["ssh-keyscan", "-t", "ed25519", host], capture=True, check=False).stdout or ""
            known.write_text(out, encoding="utf-8")
        host_key = known.read_text(encoding="utf-8").strip()
        if not host_key:
            sys.exit(f"Couldn't read {host}'s SSH host key. Check the server address and try again.")

        say("Saving the deploy settings as encrypted GitHub secrets...")
        set_secret("DEPLOY_HOST", host)
        set_secret("DEPLOY_USER", user)
        set_secret("DEPLOY_SSH_KEY", key.read_text(encoding="utf-8"))
        set_secret("DEPLOY_KNOWN_HOSTS", host_key)
        say("Saved. (The private key now exists only on GitHub; this PC's copy is deleted.)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def explain_failure(log: str, url: str) -> bool:
    """Print what went wrong. Returns True if running the setup again is the fix."""
    ghtools.show_log_tail(log)
    low = log.lower()
    if "deploy_not_set_up" in low:
        say("What to do: the deploy isn't set up yet - answer y below.")
        return True
    if "permission denied" in low or "host key verification failed" in low or "remote host identification" in low:
        say("What to do: GitHub couldn't log in to the server (new server, or the key was removed).")
        say("Answer y below to set it up again.")
        return True
    if any(line.startswith("test\t") for line in log.splitlines()):  # gh prefixes each line with its job
        say("What to do: a server test failed, so nothing was deployed. The server is unchanged.")
    else:
        say(f"What to do: open {url} to see the whole log. The server keeps running the old version if the")
        say("deploy stopped early; install.sh checks nginx before reloading it.")
    return False


def main() -> None:
    step("RuskiMaxxing Cloud -> deploy")
    ghtools.start("deploy_server.py")
    github_login()
    require_workflow(WORKFLOW)
    if not set(SECRETS) <= ghtools.secret_names():
        setup()
    elif ask("Deploying is set up. Press Enter to deploy now (or type s to set it up again): ").lower() == "s":
        setup()
    while True:
        step("Testing, then deploying the latest version (about 3-5 minutes)")
        ok, log, url = follow(WORKFLOW)
        if ok:
            break
        if explain_failure(log, url) and ask("Set up again? (y/n): ").lower().startswith("y"):
            setup()
            continue
        sys.exit(1)
    step("Done - the server is running the latest version")
    say(f"Check it: https://{DEFAULT_HOST}/health   (details: {url})")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nStopped.")
