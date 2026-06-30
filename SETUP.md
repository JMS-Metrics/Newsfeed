# BoomRx Daily News Digest — Setup Guide

This repo runs itself once a day on GitHub's free servers: it pulls news on your
formulary beats, summarizes and scores each story with Claude, publishes a public
dashboard (a link you can share), and emails you the digest.

You do **not** need to touch the code. You only need to (1) put these files in a
GitHub repo, (2) create three free accounts, and (3) paste in some keys. ~20 min.

---

## What's in this folder

| File / folder                      | What it is                                   | You edit it? |
|------------------------------------|----------------------------------------------|--------------|
| `digest.py`                        | The program that does everything             | No           |
| `feeds.yaml`                       | The news topics + watch list (your beats)    | Optional     |
| `schema.sql`                       | One-time database setup, run in Supabase     | No           |
| `requirements.txt`                 | List of code libraries GitHub installs       | No           |
| `templates/`                       | Look of the dashboard + email                | No           |
| `.github/workflows/digest.yml`     | The daily timer                              | No           |
| `docs/index.html`                  | The dashboard page (auto-overwritten daily)  | No           |
| `README.md`                        | Background notes                             | No           |

> The dashboard link will be **the only thing you share** — it updates itself every morning.

---

## Step 1 — Create the GitHub repo

1. Go to https://github.com and sign in (make a free account if needed).
2. Click **+** (top right) → **New repository**.
3. Name it `boomrx-digest`. Choose **Public** (required for a free shareable dashboard link).
4. Click **Create repository**.
5. On the new repo page, click **uploading an existing file**, then drag in **all the
   files from this folder** (keep the folder structure — the `templates` and
   `.github/workflows` folders must come along). Click **Commit changes**.

## Step 2 — Database (Supabase) — free, stops repeat stories

1. Go to https://supabase.com → sign up → **New project** (any name, pick a password).
2. When it's ready, open **SQL Editor** → **New query**.
3. Open `schema.sql` from this folder, copy all of it, paste it in, click **Run**.
4. Go to **Project Settings → API**. Copy two things for Step 4:
   - **Project URL** (looks like `https://abcd.supabase.co`)
   - **service_role** key (the secret one — *not* the "anon" key)

## Step 3 — Email (Resend) — free, sends you the digest

1. Go to https://resend.com → sign up.
2. **API Keys** → **Create API Key** → copy it for Step 4.
3. For the "from" address: easiest is to use their test sender `onboarding@resend.dev`
   to start. (Later you can verify your own domain to send from `digest@boomrx...`.)

## Step 4 — Paste your keys into GitHub (Secrets)

In your GitHub repo: **Settings → Secrets and variables → Actions → New repository secret**.
Add each of these (name on the left, your value on the right):

| Secret name          | What to paste                                              |
|----------------------|-----------------------------------------------------------|
| `ANTHROPIC_API_KEY`  | Your Anthropic API key (console.anthropic.com → API Keys)  |
| `SUPABASE_URL`       | The Project URL from Step 2                                |
| `SUPABASE_KEY`       | The **service_role** key from Step 2                       |
| `RESEND_API_KEY`     | The key from Step 3                                        |
| `DIGEST_EMAIL_TO`    | Your email (commas for multiple people)                   |
| `DIGEST_EMAIL_FROM`  | `onboarding@resend.dev` to start                          |
| `SITE_BASE_URL`      | `https://YOURUSERNAME.github.io/boomrx-digest`            |

## Step 5 — Turn on the dashboard (GitHub Pages)

1. Repo → **Settings → Pages**.
2. Under **Source**, choose **Deploy from a branch**.
3. Branch: **main**, folder: **/docs**. Click **Save**.
4. After the first run, your shareable link is: `https://YOURUSERNAME.github.io/boomrx-digest`

## Step 6 — Run it once to test

1. Repo → **Actions** tab. If prompted, click to enable workflows.
2. Click **Daily News Digest** (left) → **Run workflow** → **Run workflow**.
3. Wait ~2–3 minutes. A green check = success. You'll get an email, and the dashboard
   link will go live shortly after.

After this, it runs **automatically every morning** (7am Eastern). Nothing more to do.

---

## Adjusting it later (optional)

- **Change topics / watch list:** edit `feeds.yaml` on GitHub (pencil icon → edit → commit).
  Add a Google News query under `google_news`, or a watch item under `watch`.
- **Change the time:** edit the `cron` line in `.github/workflows/digest.yml`
  (it's in UTC; `0 11 * * *` = 7am Eastern).
- **Show more/fewer stories:** the workflow has optional `MIN_SCORE` and `MAX_ITEMS`
  settings you can uncomment.

## If something breaks

- Open **Actions** → click the failed run (red X) → read the last red line. It usually
  names the missing/incorrect secret.
- Most common issue: using the Supabase **anon** key instead of **service_role**, or a
  typo in a secret name (they must match the table above exactly).
