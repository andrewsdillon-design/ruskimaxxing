# iPhone app: TestFlight and the App Store

The iPhone app (`src/ruskimaxxing_mobile`, BeeWare/Toga, Python) is built, signed and uploaded by
GitHub Actions on a Mac runner, so no Mac is needed. From Windows, double-click
**`SHIP_TO_TESTFLIGHT.bat`**.

| | |
|---|---|
| Bundle ID (iOS) | `io.github.andrewsdillondesign.ruskimaxxing-mobile` (Briefcase turns `_` into `-`; App Store IDs can't have `_`) |
| Android package | `io.github.andrewsdillondesign.ruskimaxxing_mobile` (unchanged, so existing APK installs still update) |
| Apple team | GA9A5J9A44, Dillon REA Andrews (Individual) |
| Version | `version` in `pyproject.toml` (`[tool.briefcase]`) |
| Build number | `<run number>.<attempt>` of the TestFlight workflow, so it always goes up |
| Devices | iPhone only (`TARGETED_DEVICE_FAMILY=1`), so no iPad screenshots are needed |
| Workflow | `.github/workflows/testflight.yml` |

## How it works

1. **`SHIP_TO_TESTFLIGHT.bat`** installs Git and Python if they're missing, then runs `tools/ship_ios.py`, which:
   installs the GitHub CLI, clones or updates the repo in `%USERPROFILE%\ruskimaxxing`, signs in to GitHub,
   does the one-time Apple setup, starts the workflow and follows it live.
2. **Workflow, `preflight` job (Linux, about 30 seconds):** registers the bundle ID with Apple if needed, and
   checks that the App Store Connect app exists. If it doesn't, the job stops with `APP_RECORD_MISSING`, and
   the script shows you exactly what to type into **New App**.
3. **Workflow, `ios` job (macOS, about 15 to 25 minutes):**
   - `briefcase create iOS`.
   - `tools/ios_prepare.py`: sets the build number and version, sets `ITSAppUsesNonExemptEncryption = false`,
     checks the `ruskimaxxing://` URL scheme, adds `packaging/ios/PrivacyInfo.xcprivacy`, checks that the
     1024 px icon has no alpha channel, and prints the bundle ID.
   - `xcodebuild archive`, unsigned. An automatically signed archive needs a development profile, and Apple
     only makes one once an iPhone is registered to the team ("Your team has no devices").
   - Checks the archive's contents.
   - `xcodebuild -exportArchive` with `packaging/ios/ExportOptions.plist` (app-store-connect, upload). This step
     signs for the App Store: the API key lets Xcode create the distribution certificate and App Store profile. If that
     fails, it falls back to exporting an `.ipa` and uploading it with `xcrun altool`.

**Without the secrets, and always on pull requests,** the workflow builds and checks an **unsigned** archive,
uploads it as a run artifact, and stops before signing. This proves that everything up to signing works.

### Secrets (set by the .bat; stored only as GitHub repo secrets)

| Secret | What it is |
|---|---|
| `ASC_ISSUER_ID` | Issuer ID shown above the API keys table |
| `ASC_KEY_ID` | The key's 10-character Key ID |
| `ASC_KEY_P8` | Full contents of the downloaded `AuthKey_XXXXXXXXXX.p8` |

Create the key at App Store Connect → **Users and Access → Integrations → App Store Connect API → Team Keys →
Generate API Key**, with Access set to **Admin**. App Manager can upload builds, but it can't create the cloud-managed
signing certificate that a Mac without your certificates needs. That fails with "Cloud signing permission
error". The key file can only be downloaded once.

### Why the order matters (bundle ID → New App → upload)

App Store Connect's **New App** form only lists bundle IDs that are already registered with Apple, and an upload
fails ("No suitable application records were found") until that app exists. The script's first check run
registers the bundle ID through the API, then tells you to create the app, then builds. If you register it by
hand instead, use Certificates, Identifiers & Profiles → Identifiers → + → App IDs → App → Explicit
`io.github.andrewsdillondesign.ruskimaxxing-mobile`.

### New App values

| Field | Value |
|---|---|
| Platforms | iOS |
| Name | RuskiMaxxing. It must be unique on the store; if it's taken, use "RuskiMaxxing: Strength Program" |
| Primary language | English (U.S.) |
| Bundle ID | `io.github.andrewsdillondesign.ruskimaxxing-mobile` |
| SKU | `ruskimaxxing-ios` |
| User access | Full Access |

### Shipping a new version

Bump the version in **both** places in `pyproject.toml`, and `__version__` in `src/ruskimaxxing/__init__.py`. Then run
the .bat again or push a `v*` tag. After a version has been approved, Apple rejects new builds that use the same version.

---

## TestFlight-first checklist

**Now (internal TestFlight, no review needed):**
- [ ] Merge the PR, double-click `SHIP_TO_TESTFLIGHT.bat`, and do the one-time key and New App steps.
- [ ] Wait 10–30 minutes for the "processing complete" email.
- [ ] App Store Connect → the app → TestFlight → Internal Testing → **+** → add yourself.
- [ ] On the iPhone, install **TestFlight** from the App Store and accept the invite.
- [ ] Run through "What to Test" (below) yourself.

**External testers (friends, a public link), which needs a short Beta App Review:**
- [ ] TestFlight → Test Information: paste the "What to Test" text, a feedback email, the privacy policy URL
      `https://api.ruskimaxxing.com/privacy`, and the review notes below.
- [ ] Add an External Testing group and add the build. The first build gets a quick review, usually within a day.

**App Store release (full App Review):**
- [ ] App Privacy: answer as in "Privacy nutrition label" below.
- [ ] Age rating questionnaire: as below.
- [ ] Screenshots: 6.9" iPhone (1320 × 2868), at least 3. Description, keywords, support URL
      (`https://github.com/andrewsdillon-design/ruskimaxxing` or the website), and marketing URL (optional).
- [ ] Price: Free. No in-app purchases.
- [ ] Make a **reviewer account** on the website with cloud backup turned on (make it complimentary in the admin
      pages) and put it in the review notes.
- [ ] Deploy the server from this PR (it has the app-mode fix, see guideline 3.1.1 below) before submitting.
- [ ] Submit for review.

---

## App Review readiness

### Account deletion (guideline 5.1.1(v)): done in this PR
- Setup → Cloud backup → **Delete account** asks for the password and deletes the account and all cloud
  backups in the app (`DELETE /api/account`). If the password is forgotten, a "Delete on the website" button
  opens `/account/delete?app=1`.
- Deleting an account (in the app or on the website) also **cancels any Stripe subscription**, so nobody is
  charged after deleting. If Stripe can't be reached, nothing is deleted and the person is asked to try again.
- Setup has **Privacy policy** and **Terms** buttons (`/privacy`, `/terms`). Signing up on the website also links both.

### Payments (guidelines 3.1.1 and 3.1.3)
What the iOS app does today:
- It has **no** purchase buttons, prices or "subscribe" calls to action. The phone app has Year 1 only; Years 2–3
  aren't in the phone app.
- Cloud backup is optional. When it isn't active for an account, the app says only "Cloud backup isn't active
  for this account" and gives no instructions about where to buy it.
- That fits **3.1.3(f)**: a free stand-alone companion to a paid web service (cloud storage), with no purchasing
  in the app and no calls to action to buy outside it.

**Website pages opened from the app: fixed in this PR ("app mode").**
Before, every website page had a footer link to `/account`, where the Stripe **Subscribe** and program-year
buttons are, so a reviewer could reach a purchase in two taps from the app. Now:
- The phone app opens its pages with `?app=1`: sign-in (`/link?...&app=1`, added by the server for phone
  apps), delete account, privacy and terms. That turns on app mode for 30 minutes in that browser
  (`rmx_app` cookie). `?app=0` turns it off.
- In app mode the footer has no Account link. `/account` shows only "Signed in as", Log out and Delete
  account: no plan status, prices, Subscribe, billing or Program years. `/account/program` redirects
  to `/account`. The subscribe, billing-portal and program-year checkout endpoints refuse to start a
  purchase.
- What's left: the Terms page still *describes* the plan and program-year prices, because it's a legal
  document and has no buy button. That isn't a call to action, and Apple asks apps to link the terms.
- Tests: `server/tests/test_billing.py::test_pages_opened_from_the_phone_app_sell_nothing`.

The server change must be deployed to api.ruskimaxxing.com before App Review. Older app builds still work,
but they open pages without `?app=1`.

**If Years 2–3 come to the phone later:** keep them unlock-only. The app checks the signed-in account (as cloud
backup does) and shows the content if it's owned. On iOS (`toga.platform.current_platform == "iOS"`), show no
price, no buy button and no "buy on the website" text. People who don't own it see only that it's "not on
this account". Year 1 stays free.

### Export compliance
`ITSAppUsesNonExemptEncryption = false` is in Info.plist. The app uses only HTTPS (exempt), so App Store
Connect won't ask on each build.

### Privacy manifest
`packaging/ios/PrivacyInfo.xcprivacy` includes:
- No tracking.
- Required-reason APIs used by Python and Toga: file timestamps (C617.1), system boot time (35F9.1), disk space
  (E174.1) and UserDefaults (CA92.1).
- The data types below.

### Privacy "nutrition label" (App Store Connect → App Privacy)
"Do you or your third-party partners collect data from this app?" **Yes**. Data is only collected when the person
turns on the optional cloud backup. Without it, everything stays on the phone.

| Data type | Collected | Linked to user | Tracking | Purpose |
|---|---|---|---|---|
| Contact Info → Email Address | Yes (cloud account) | Yes | No | App Functionality |
| Health & Fitness → Health (bodyweight, body fat %, height) | Yes (backup) | Yes | No | App Functionality |
| Health & Fitness → Fitness (workout logs, PRs) | Yes (backup) | Yes | No | App Functionality |
| Identifiers → User ID (account ID) | Yes | Yes | No | App Functionality |
| Everything else: location, contacts, purchases, usage data, diagnostics, ads | No | | | |

Purchases happen on the website, not in the app, so the app doesn't collect them. If the website's research
pages are counted, they use aggregate, de-identified data only, so nothing more is added here. Keep
`server/README.md` "Admin" consistent with this.

### Age rating questionnaire
Answer **None** or **No** to everything: violence, sexual content, profanity, drugs, gambling, horror, mature themes,
medical/treatment information, contests, user-generated content, messaging/chat, unrestricted web access (links
open in Safari; there's no in-app browser), advertising, and parental controls. **Result: 4+.**

### TestFlight "What to Test"
```
Thanks for testing RuskiMaxxing, a free 1-year strength, mass and power program.
Please try:
1. Setup tab: enter your intake (units, start Monday, height, bodyweight) and a starting max or two.
2. Workout tab: open this week's Day 1, log sets (weight, reps, RPE, done), Save workout, then All done.
3. Progress, PRs and Body tabs: check charts, PRs and bodyweight entries update.
4. Optional: Setup > Cloud backup > Create account or log in. Finish on the website, tap "Return to
   the app", then Back up now. Try Delete account too (it asks for your password).
5. Close and reopen the app: everything should still be there.
Report anything confusing, cut off or slow (screenshot + what you tapped) with TestFlight's feedback.
```

### Review notes template (App Review Information → Notes)
```
RuskiMaxxing is a free strength-training program and workout log. All training data is stored
on the device. There are no in-app purchases and no ads.

Optional cloud backup: Setup tab > "3. Cloud backup" > "Create account or log in". This opens our
website (https://api.ruskimaxxing.com) in Safari to sign in, then returns to the app via the
ruskimaxxing:// link and syncs. Demo account with backup active:
  Email:    <reviewer email>
  Password: <reviewer password>
Account deletion: Setup > Cloud backup > Delete account (in the app; asks for the password).
Privacy policy and terms: buttons at the end of the Cloud backup section in Setup.

The app is built with Python (BeeWare Toga). Encryption: HTTPS only (exempt).
```
Sign-in required: **No**. The demo account is only for the optional backup.
