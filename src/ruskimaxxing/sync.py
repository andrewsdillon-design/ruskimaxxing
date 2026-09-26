"""Cloud backup client (standard library only, so it also runs on phones).

    cloud = Cloud(store)
    cloud.register(url, email, password)   # or cloud.login(...)
    cloud.sync()                           # push local changes, pull other devices' changes

Login state lives in the local settings table (never synced): cloud_url,
cloud_email, cloud_token, cloud_seq (last server change pulled) and
cloud_pushed (timestamp of the last successful push).
"""

import json
import urllib.error
import urllib.request

from ruskimaxxing.edition import EDITION
from ruskimaxxing.storage import Store, now

DEFAULT_SERVER = "https://api.ruskimaxxing.com"  # RuskiMaxxing Cloud; the Server field lets people change it
TIMEOUT = 20


class CloudError(Exception):
    def __init__(self, message: str, code: int = 0):
        super().__init__(message)
        self.code = code


def http_transport(method: str, url: str, body: dict | None, token: str | None) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json", "Accept": "application/json",
                                          **({"Authorization": f"Bearer {token}"} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise CloudError(f"Can't reach the server ({getattr(e, 'reason', e)}). Check the address and your connection.")


class Cloud:
    def __init__(self, store: Store, transport=http_transport):
        self.store = store
        self.transport = transport

    # ----- state ------------------------------------------------------------------
    @property
    def url(self) -> str:
        return (self.store.get("cloud_url", "") or DEFAULT_SERVER).rstrip("/")

    @property
    def email(self) -> str:
        return self.store.get("cloud_email", "") if self.logged_in else ""

    @property
    def logged_in(self) -> bool:
        return bool(self.store.get("cloud_token", ""))

    def status(self) -> str:
        if not self.logged_in:
            return "Not signed in - your data is only on this device"
        if self.store.get("cloud_backup_active", "1") == "0":
            return f"Signed in as {self.email} - backups aren't active for this account (restore still works)"
        last = self.store.get("cloud_last_sync", "")
        return f"Signed in as {self.email}" + (f" - last backup {last[:16].replace('T', ' ')} UTC" if last else "")

    # ----- calls ------------------------------------------------------------------
    def _call(self, method: str, path: str, body: dict | None = None, auth: bool = True) -> dict:
        if not self.url:
            raise CloudError("Enter your server address first")
        code, data = self.transport(method, self.url + path, body,
                                    self.store.get("cloud_token", "") if auth else None)
        if code == 401 and auth:
            self.store.set("cloud_token", "")
        if code >= 400:
            raise CloudError(data.get("detail") if isinstance(data.get("detail"), str) else f"Server error ({code})",
                             code)
        if isinstance(data.get("plan"), dict):
            self.store.set("cloud_backup_active", "1" if data["plan"].get("active") else "0")
        return data

    def _signed_in(self, url: str, data: dict) -> None:
        self.store.set("cloud_url", url.rstrip("/"))
        self.store.set("cloud_token", data["token"])
        self.store.set("cloud_email", data["email"])
        self.store.set("cloud_seq", "0")      # pull everything once for this account
        self.store.set("cloud_pushed", "")    # and push everything we have

    def register(self, url: str, email: str, password: str) -> None:
        self.store.set("cloud_url", url.rstrip("/"))
        self._signed_in(url, self._call("POST", "/api/register", {"email": email, "password": password}, auth=False))

    def login(self, url: str, email: str, password: str) -> None:
        self.store.set("cloud_url", url.rstrip("/"))
        self._signed_in(url, self._call("POST", "/api/login", {"email": email, "password": password}, auth=False))

    def logout(self) -> None:
        try:
            self._call("POST", "/api/logout")
        except CloudError:
            pass  # offline: forget the token locally anyway
        self.store.set("cloud_token", "")

    def reset_password(self, url: str, email: str) -> str:
        self.store.set("cloud_url", url.rstrip("/"))
        return self._call("POST", "/api/password-reset", {"email": email}, auth=False).get("message", "")

    def delete_account(self, password: str) -> None:
        self._call("DELETE", "/api/account", {"password": password})
        self.store.set("cloud_token", "")
        self.store.set("cloud_email", "")

    def sync(self) -> tuple[int, int]:
        """Push local changes and pull remote ones. Returns (sent, received)."""
        if not self.logged_in:
            raise CloudError("Sign in first")
        started = now()
        changes = self.store.changes(self.store.get("cloud_pushed", "") or None)
        since = int(self.store.get("cloud_seq", "0") or 0)
        sent, inactive = 0, None
        try:
            # send in chunks (the server takes up to 5000 changes per request)
            for i in range(0, max(len(changes), 1), 2000):
                chunk = changes[i:i + 2000]
                data = self._call("POST", "/api/sync", {"edition": EDITION, "since": since, "changes": chunk})
                sent += len(chunk)
        except CloudError as e:
            if e.code != 402:
                raise
            # backups aren't active for this account: still restore what's saved, keep local edits queued
            inactive = e
            data = self._call("POST", "/api/sync", {"edition": EDITION, "since": since, "changes": []})
        received = self.store.apply(data["changes"])
        self.store.set("cloud_seq", str(data["seq"]))
        if inactive:
            raise CloudError(f"{inactive} Received {received} updates.", 402)
        self.store.set("cloud_pushed", started)
        self.store.set("cloud_last_sync", started)
        return sent, received
