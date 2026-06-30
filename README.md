# Daily News Digest

A self-hosted daily news digest for the beats you care about — **compounding
pharmacies & compounded products, peptides, HRT/TRT, GLP-1 / medical weight
loss, and telehealth companies**.

It pulls from Google News, the Federal Register (FDA rulemaking), and any RSS
feeds you add; deduplicates against Supabase so each story appears once; uses
Claude to summarize, categorize, and score relevance; then delivers **both** an
emailed digest and a GitHub Pages dashboard. Runs daily on GitHub Actions — no
server to maintain.

```
Google News ┐
Fed Register ┼─► dedup (Supabase) ─► Claude (summary/category/score) ─┬─► email (Resend)
RSS feeds   ┘                                                         └─► dashboard (GitHub Pages)
```

## What you need

| Service        | Why                         | Free tier? |
|----------------|-----------------------------|------------|
| GitHub repo    | hosting + scheduler + Pages | yes        |
| Supabase       | dedup store (you have this) | yes        |
| Anthropic API  | summaries (you have this)   | usage-based|
| Resend         | sending the email           | yes (3k/mo)|

## Setup (about 15 minutes)

**1. Create the repo.** Push these files to a new GitHub repo (private is fine;
Pages still works on private repos for paid plans, otherwise make it public).

**2. Supabase table.** In the Supabase SQL editor, run `schema.sql` once.

**3. Resend (email).** Sign up at resend.com, verify a sending domain (or use
their onboarding `onboarding@resend.dev` for testing), and create an API key.

**4. Add GitHub secrets.** Repo → Settings → Secrets and variables → Actions:

| Secret              | Value                                                        |
|---------------------|-------------------------------------------------------------|
| `ANTHROPIC_API_KEY` | your Anthropic key                                          |
| `SUPABASE_URL`      | `https://xxxx.supabase.co`                                  |
| `SUPABASE_KEY`      | Supabase **service_role** key (server-side; keep secret)    |
| `RESEND_API_KEY`    | your Resend key                                             |
| `DIGEST_EMAIL_TO`   | your email (comma-separate for multiple recipients)        |
| `DIGEST_EMAIL_FROM` | a verified Resend sender, e.g. `digest@yourdomain.com`     |
| `SITE_BASE_URL`     | `https://USER.github.io/REPO` (for the email's dashboard link) |

**5. Enable Pages.** Repo → Settings → Pages → Source: **Deploy from a branch**,
branch `main`, folder **/docs**. After the first run, the dashboard lives at
`https://USER.github.io/REPO/`.

**6. First run.** Actions tab → "Daily News Digest" → **Run workflow**.
> The first run treats *everything* it finds as new, so expect a large digest
> once. Every run after that only shows genuinely new stories.

## Tuning

- **Sources:** edit `feeds.yaml` — add/remove Google News queries, Federal
  Register terms, or RSS feeds. Tighter queries = less noise.
- **Schedule:** edit the `cron` in `.github/workflows/daily-digest.yml`
  (it's in UTC).
- **Strictness:** set `MIN_SCORE` (default 3) higher for a tighter digest.
- **Model:** `CLAUDE_MODEL` defaults to `claude-sonnet-4-6`; `claude-haiku-4-5-20251001`
  is cheaper for this kind of summarization.


## Standing watch list

`feeds.yaml` has a `watch:` section. Each entry renders as a persistent panel at
the top of the dashboard and email **every day** (even with no news), and any
incoming story matching its `keywords` is auto-flagged with a WATCH badge and
pushed to the top. Pre-loaded with the three highest-exposure items: GLP-1 "copy"
combos, the peptide line's Category 1 status (PCAC Jul 23-24), and compounded
topical finasteride. Add/edit entries freely.

## Categories

Items are tagged into: Regulatory/FDA, Peptides, GLP-1 / Weight Loss, HRT/TRT,
Sexual Health, Hair Loss, Skincare, Wellness / Anti-Aging, Telehealth, Other.

## Run locally (optional)

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=... SUPABASE_URL=... SUPABASE_KEY=...
export RESEND_API_KEY=... DIGEST_EMAIL_TO=you@x.com DIGEST_EMAIL_FROM=digest@x.com
python digest.py
```

## Notes

- The dedup key is a normalized form of the headline, so the same story from two
  feeds collapses to one entry.
- `SUPABASE_KEY` should be the **service_role** key since this runs server-side.
  Don't expose it in any client-side code.
- Costs are tiny: one batched Claude call per ~25 new items per day.
