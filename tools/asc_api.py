"""Tiny App Store Connect API client for the TestFlight workflow (runs on GitHub Actions).

    python tools/asc_api.py preflight BUNDLE_ID NAME

  1. registers the bundle ID under Certificates, Identifiers & Profiles if it isn't there yet
     (so it shows up in App Store Connect's "New App" form before the first build), and
  2. checks an App Store Connect app record exists for it; if not, prints APP_RECORD_MISSING
     and exits 3 (tools/ship_ios.py looks for that and walks you through "New App").

Needs `pip install pyjwt cryptography` and these environment variables:
ASC_KEY_ID, ASC_ISSUER_ID, ASC_KEY_PATH (path to the AuthKey_XXXX.p8 file).
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import jwt

API = "https://api.appstoreconnect.apple.com/v1"


def token() -> str:
    with open(os.environ["ASC_KEY_PATH"], encoding="utf-8") as f:
        key = f.read()
    now = int(time.time())
    return jwt.encode({"iss": os.environ["ASC_ISSUER_ID"], "iat": now, "exp": now + 600,
                       "aud": "appstoreconnect-v1"},
                      key, algorithm="ES256", headers={"kid": os.environ["ASC_KEY_ID"], "typ": "JWT"})


def call(method: str, path: str, body: dict | None = None, params: dict | None = None) -> dict:
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": f"Bearer {token()}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        if e.code == 401:
            print("::error::App Store Connect rejected the API key (401). The ASC_ISSUER_ID, ASC_KEY_ID "
                  "and ASC_KEY_P8 secrets don't match, or the key was revoked. Run SHIP_TO_TESTFLIGHT.bat "
                  "and choose to enter the keys again. API_KEY_REJECTED")
        elif e.code == 403:
            print("::error::The API key isn't allowed to do this (403). Make a new key with the Admin role. "
                  "API_KEY_ROLE")
        print(f"{method} {path} -> HTTP {e.code}: {detail[:800]}")
        sys.exit(1)


def ensure_bundle_id(identifier: str, name: str) -> None:
    found = call("GET", "/bundleIds", params={"filter[identifier]": identifier, "limit": 200})["data"]
    if any(b["attributes"]["identifier"] == identifier for b in found):
        print(f"Bundle ID {identifier} is registered")
        return
    call("POST", "/bundleIds", {"data": {"type": "bundleIds", "attributes": {
        "identifier": identifier, "name": name, "platform": "IOS"}}})
    print(f"Registered bundle ID {identifier} ({name})")


def app_exists(identifier: str) -> bool:
    found = call("GET", "/apps", params={"filter[bundleId]": identifier, "limit": 200})["data"]
    return any(a["attributes"]["bundleId"] == identifier for a in found)


def main(argv):
    if len(argv) != 3 or argv[0] != "preflight":
        sys.exit(__doc__)
    identifier, name = argv[1], argv[2]
    ensure_bundle_id(identifier, name)
    if not app_exists(identifier):
        print(f"::error::APP_RECORD_MISSING: no App Store Connect app uses bundle ID {identifier} yet. "
              f"Create it at https://appstoreconnect.apple.com/apps (+ -> New App, platform iOS, bundle ID "
              f"{identifier}), then run again. SHIP_TO_TESTFLIGHT.bat walks you through it.")
        sys.exit(3)
    print(f"App Store Connect app found for {identifier}")


if __name__ == "__main__":
    main(sys.argv[1:])
