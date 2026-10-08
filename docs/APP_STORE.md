# iPhone app: TestFlight and the App Store

The phone app lives in **`mobile/`**. It's an Expo (React Native + TypeScript) app with the same look as the
Orthodox Barbell Club app, in RuskiMaxxing's colors. Expo builds and signs it in its own cloud (EAS) and
uploads it to App Store Connect, so no Mac is needed. From Windows, double-click **`SHIP_TO_TESTFLIGHT.bat`**.

| | |
|---|---|
| Bundle ID (iOS) | `io.github.andrewsdillondesign.ruskimaxxing-mobile` (the same App Store Connect app as the earlier builds) |
| Android package | `io.github.andrewsdillondesign.ruskimaxxing_mobile` |
| Apple team | GA9A5J9A44, Dillon REA Andrews (Individual) |
| Expo account | dandrews91, project `ruskimaxxing` (its ID is saved in `mobile/eas-project.json`) |
| Version | `version` in `mobile/app.config.ts` (and `mobile/package.json`): **2.4.0** |
| Build number | Managed by EAS (`appVersionSource: remote`, `autoIncrement`), so it always goes up |
| Devices | iPhone only (`supportsTablet: false`), so no iPad screenshots are needed |

## How it works

**`SHIP_TO_TESTFLIGHT.bat`** installs Git, Node.js and Python if they're missing and updates
`%USERPROFILE%\ruskimaxxing`. It then runs **`tools/ship_expo.py`**, which:
1. installs the app's packages and runs TypeScript and the tests;
2. signs in to Expo as dandrews91;
3. the first time only, creates the Expo project and commits its ID;
4. builds in Expo's cloud with `eas build --platform ios --profile production --auto-submit-with-profile production`.

The build is uploaded to App Store Connect when it finishes, and shows up in TestFlight 10–30 minutes later.

**The first build** asks you to sign in to Apple as andrews.dillon@gmail.com, type the 6-digit code from your
iPhone, and answer **yes** to creating the distribution certificate and provisioning profile. EAS stores them, so
later builds don't ask again.

`python tools/ship_expo.py android` builds an installable Android APK and prints a download link.

### The training logic is ported and tested

The program, workout pre-fills, training maxes, PRs and jump standards in `mobile/src/core/` are a TypeScript
port of `src/ruskimaxxing/`.

`tools/export_mobile_fixtures.py` runs the Python originals on the whole program and on worked examples (lb,
kg, no height), and writes `mobile/src/core/__tests__/fixtures.json`. The jest golden tests require the
TypeScript output to match exactly, down to Python's round-half-to-even and number formatting.

Whenever the Python logic changes, re-run the script. `tests/test_mobile_fixtures.py` fails until you do.

Cloud backup sends records in the desktop app's format, so the phone and desktop app can share one account.

### Checks

- **`.github/workflows/mobile.yml`** (on pushes and PRs that touch `mobile/` or the Python logic) runs:
  - the golden-data freshness check;
  - TypeScript;
  - jest;
  - `expo-doctor`;
  - a web build.
- To run them locally: `cd mobile && npm ci && npx tsc --noEmit && npx jest`.
- To preview on your computer: `npx expo start --web`.

### New App values (already done; kept for reference)

| Field | Value |
|---|---|
| Platforms | iOS |
| Name | RuskiMaxxing |
| Primary language | English (U.S.) |
| Bundle ID | `io.github.andrewsdillondesign.ruskimaxxing-mobile` |
| SKU | `ruskimaxxing-ios` |

### Shipping a new version

Bump `version` in `mobile/app.config.ts` and `mobile/package.json`, then double-click the .bat. Build numbers go up
by themselves. After a version has been approved, Apple rejects new builds that use the same version.

### The old GitHub build

Builds up to 2.3.1 (9.1) came from a BeeWare/Python app built on GitHub Actions. That pipeline has been removed.
The GitHub repo secrets `ASC_ISSUER_ID`, `ASC_KEY_ID` and `ASC_KEY_P8` aren't used any more and can be deleted.
The App Store Connect API key itself can be revoked too, unless you use it elsewhere.

---

## TestFlight-first checklist

**Now (internal TestFlight, no review needed):**
- [ ] Double-click `SHIP_TO_TESTFLIGHT.bat` and do the one-time Expo and Apple sign-ins.
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
- Setup (the gear, top right) → Cloud backup → **Delete account** asks for the password and deletes the account and all cloud
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
backup does) and shows the content if it's owned. On iOS (`Platform.OS === 'ios'`), show no
price, no buy button and no "buy on the website" text. People who don't own it see only that it's "not on
this account". Year 1 stays free.

### Export compliance
`ITSAppUsesNonExemptEncryption = false` is in Info.plist (set in `mobile/app.config.ts`). The app uses only HTTPS (exempt), so App Store
Connect won't ask on each build.

### Privacy manifest
`ios.privacyManifests` in `mobile/app.config.ts` (Expo writes it into PrivacyInfo.xcprivacy) includes:
- No tracking.
- Required-reason APIs used by React Native and Expo: file timestamps (C617.1), system boot time (35F9.1), disk space
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
1. Setup (gear, top right): enter your intake (units, start Monday, height, bodyweight) and a starting max or two.
2. Today tab: open this week's Day 1, log sets (weight, reps, RPE, tick done), then Save workout.
3. Progress, PRs and Body tabs: check charts, PRs and bodyweight entries update.
4. Optional: Setup > Cloud backup > Create a free account or log in. Finish on the website, tap "Return to
   the app", then Back up now. Try Delete account too (it asks for your password).
5. Close and reopen the app: everything should still be there.
Report anything confusing, cut off or slow (screenshot + what you tapped) with TestFlight's feedback.
```

### Review notes template (App Review Information → Notes)
```
RuskiMaxxing is a free strength-training program and workout log. All training data is stored
on the device. There are no in-app purchases and no ads.

Optional cloud backup: Setup (gear icon, top right) > "3. Cloud backup" > "Create a free account or log in". This opens our
website (https://api.ruskimaxxing.com) in Safari to sign in, then returns to the app via the
ruskimaxxing:// link and syncs. Demo account with backup active:
  Email:    <reviewer email>
  Password: <reviewer password>
Account deletion: Setup > Cloud backup > Delete account (in the app; asks for the password).
Privacy policy and terms: buttons at the end of the Cloud backup section in Setup.

The app is built with Expo (React Native). Encryption: HTTPS only (exempt).
```
Sign-in required: **No**. The demo account is only for the optional backup.
