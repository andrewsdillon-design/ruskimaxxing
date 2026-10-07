"""One-click server deploy: tools/deploy_server.py and server/deploy/enable_github_deploy.sh."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import deploy_server  # noqa: E402

ENABLE = ROOT / "server" / "deploy" / "enable_github_deploy.sh"
PUBKEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOb8x+/2kP0ZcZ3m6o1sV0fGq2uS3r0YH0j4m9w8uT5d ruskimaxxing-github-deploy"
bash = pytest.mark.skipif(not shutil.which("bash"), reason="needs bash")


@bash
def test_remote_command_passes_arguments_intact():
    """The one line typed into the server unpacks the script and hands it the arguments exactly."""
    script = b'#!/usr/bin/env bash\nprintf "<%s>\\n" "$@"\n'
    cmd = deploy_server.remote_command("root", "api.example.com", "me+x@example.com", PUBKEY, script)
    out = subprocess.run(["bash", "-c", cmd.replace("sudo bash", "bash")], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.splitlines() == ["<root>", "<api.example.com>", "<me+x@example.com>", f"<{PUBKEY}>"]


@bash
@pytest.mark.parametrize("args", [
    ["root", "api.example.com", "x@example.com; rm -rf /", PUBKEY],
    ["root", "api.example.com$(id)", "x@example.com", PUBKEY],
    ["root", "api.example.com", "x@example.com", "ssh-rsa AAAAB3Nza"],
    ["root", "api.example.com", "x@example.com", 'ssh-ed25519 AAAA" command="sh'],
    ["root;id", "api.example.com", "x@example.com", PUBKEY],
    [],
])
def test_enable_script_rejects_bad_arguments_before_doing_anything(args):
    out = subprocess.run(["bash", str(ENABLE), *args], capture_output=True, text=True)
    assert out.returncode == 2 and "usage:" in out.stdout


@bash
def test_deploy_scripts_parse():
    for name in ("deploy.sh", "enable_github_deploy.sh", "install.sh"):
        assert subprocess.run(["bash", "-n", str(ROOT / "server" / "deploy" / name)]).returncode == 0


def test_install_sets_up_the_deploy_command():
    install = (ROOT / "server" / "deploy" / "install.sh").read_text()
    assert "/usr/local/sbin/ruskimaxxing-deploy" in install and "/etc/ruskimaxxing-cloud.deploy" in install
