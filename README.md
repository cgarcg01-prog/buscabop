# buscabop

Daily watcher for the **Boletín Oficial de la Provincia de León** (BOP León).
Each day, GitHub Actions fetches the day's bulletin PDF, extracts its text, and
searches for the keywords listed in [`keywords.txt`](keywords.txt). If any
keyword matches, an email is sent to `cgarcg01@gmail.com` with the snippets and
links. If there is no bulletin that day (weekends, holidays) or no match,
nothing is sent.

## Edit your keywords from your phone

1. Open this repository in the GitHub mobile app (or `github.com` in a mobile browser).
2. Tap `keywords.txt`.
3. Tap the **⋯** (three dots) → **Edit file** → make changes → **Commit changes** → **Commit directly to main**.

The next daily run picks up the new list automatically. Lines starting with `#`
are comments. Matching is case- and accent-insensitive (`expropiacion` matches
`Expropiación`).

## One-time setup

### 1. Create the GitHub repo

Push this directory to a **public** GitHub repo (Actions minutes are unlimited
on public repos, so the daily run is free).

### 2. Create a Gmail App Password

The workflow sends mail through Gmail's SMTP. Gmail no longer allows the
regular account password for SMTP — you need an **App Password**:

1. On the Google account that will *send* the emails, enable 2-Step Verification:
   <https://myaccount.google.com/security>.
2. Generate an app password at <https://myaccount.google.com/apppasswords>.
   Choose "Mail" / "Other (Custom name): buscabop". Copy the 16-character
   password Google shows you.

### 3. Add the secrets

In the GitHub repo: **Settings → Secrets and variables → Actions → New repository secret**.

| Name                 | Value                                                  |
|----------------------|--------------------------------------------------------|
| `GMAIL_USER`         | Gmail address that will send the email (e.g. `you@gmail.com`) |
| `GMAIL_APP_PASSWORD` | The 16-character app password from step 2             |

The recipient is hard-coded to `cgarcg01@gmail.com` in
[`.github/workflows/daily.yml`](.github/workflows/daily.yml).

### 4. Run it once

Open the repo on GitHub → **Actions** tab → **Daily BOP check** → **Run workflow**.
The job takes about a minute. If today's BOP contains a keyword, an email
arrives shortly after.

## Schedule

The cron is `0 13 * * *` (13:00 UTC every day = 15:00 in Madrid summer time,
14:00 in Madrid winter time), giving the BOP time to publish each morning.
GitHub Actions cron is best-effort and can drift several minutes.

## Run locally

```sh
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Today's bulletin
python scripts/check_bop.py

# A specific past day (Mon-Fri only — BOP is not published on weekends)
python scripts/check_bop.py --date 22-04-2026
```

When there are matches the script writes `report.html` next to itself; that's
the file the workflow attaches as the email body.
