# Security and ethical use

This document describes how the project handles credentials, the intended
scope of use, and considerations regarding the platforms' terms of use.

## TL;DR

- You only capture **your own accounts**, with cookies from **your own
  login**. The tool does not bypass authentication or access third-party
  data.
- Cookies/profiles live in `.storage/` (gitignored — never committed).
- Credentials never enter Git. Cookies are used only for authenticated
  requests made directly to the respective platform.
- If you share this project with someone else, they need to log in
  themselves — profiles are not portable nor shareable.

## How login works

Each platform has a `scripts/<plat>-login.py` script:

1. It opens an isolated Chromium instance (via Playwright) pointing to
   the platform's login page.
2. You log in manually — email, password, eventually captcha or 2FA.
   The script **does not receive nor store** your credentials.
3. After login completes, Playwright saves the session cookies to
   `.storage/<platform>-profile-<account>/`. This directory lives on the
   local filesystem, inside the project directory.
4. Subsequent capture scripts reuse this profile — they open the browser
   with cookies already loaded, no need to log in again.

**What lives in `.storage/`:**

- HTTP cookies for the platform
- Browser LocalStorage / IndexedDB
- Browser cache (irrelevant)

**What does NOT live in `.storage/`:**

- Your password (the platform only sends/receives session cookies after
  login completes)
- DVC remote secrets: local configuration may live in `.dvc/config.local`,
  with a private copy in `private/dvc.config.local`. Treat both as passwords
  and never add them to Git.

## What `.gitignore` protects

```
.storage/        # cookies/profiles for each platform
data/raw/        # raw captured data (your conversations)
data/merged/     # consolidated data
data/processed/  # canonical parquets
data/unified/    # cross-platform parquets
data/external/   # manual snapshots (GDPR exports, clippings, etc)
.venv/           # Python virtual environment
```

**Before pushing:** always confirm you are committing only code, not
personal data. `git status` should show zero files in `data/`,
`.storage/`, `.venv/`.

## Platform terms of use (ToS)

This tool uses internal APIs of the platforms, authenticated with cookies from
your own login. It automates requests associated with a web session; that does
not remove any contractual restrictions on automation.

**What this means:**

- You are accessing data you already have permission to see (your own
  account).
- You are not scraping public data of third parties.
- You are not sharing your credentials with the tool.
- You are not aggressively bypassing rate limits (the tool makes
  incremental requests, with pauses where appropriate).

**What is NOT covered:**

- Specific ToS clauses that prohibit **any** automation, including personal
  use. Read the current terms of each platform and assess whether your use
  falls under those restrictions.
- This tool **has not been audited** by a lawyer nor reviewed by any of
  the platforms. It exists for personal archiving and research — do not
  use it in critical professional contexts without understanding the ToS
  implications.

**In short:** if you are logged into the platform and accessing your
own conversations, this tool merely automates what you would do
manually. But the legal interpretation of "automation" varies by ToS —
read your platform's terms.

## Best practices

### Before pushing the repository

```bash
# Check zero sensitive files
git status

# Confirm .storage/ and data/ are gitignored
git check-ignore .storage/ data/

```

If credentials appear in an old commit (even if removed later), Git
history still contains them. Revoke the exposed credential immediately and use
a history-rewrite procedure appropriate to the repository before making it
public. Avoid printing complete historical diffs in a shared terminal while
investigating the incident.

### Cookie rotation

Platform session cookies usually last months but can be invalidated:

- By the platform (logout on another device, security policy)
- By you (explicit logout, password change)
- After prolonged inactivity

If a capture starts failing with 401/403, redo the login for the
specific platform:

```bash
rm -rf .storage/<platform>-profile-<account>
python scripts/<platform>-login.py
```

### Before sharing a machine or backup

Profiles in `.storage/` allow access to your platform accounts
without needing a password (just need a browser able to read the
cookies). **Treat `.storage/` with the same care as any logged-in
browser cache.**

If you are going to lend the machine, make a public backup, or
discard it:

```bash
rm -rf .storage/
```

## Reporting vulnerabilities

If you find a vulnerability in the code (e.g., injection, unintended
credential exfiltration, data leak), open a **private** issue or
contact the maintainer directly. Do not expose publicly until the
fix is in production.

## Limitations of this policy

- We do not cover the platforms' own behavior (e.g., what OpenAI does
  with your data, or whether ChatGPT can detect use of this tool).
- We are not security auditors. The code is provided as-is (see
  [LICENSE](../LICENSE)).
- If your account is corporate/enterprise, check your organization's
  policy on local data archiving.
