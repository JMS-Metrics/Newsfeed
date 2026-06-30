#!/usr/bin/env python3
"""
Daily news digest.

Beats: compounding pharmacies & compounded products, peptides, HRT/TRT,
GLP-1 / medical weight loss, telehealth companies.

Pipeline
--------
1. Ingest items from Google News topic queries, the Federal Register API,
   and any RSS feeds in feeds.yaml.
2. Deduplicate against a Supabase table — only stories we've never shown proceed.
3. Ask Claude to summarize, categorize, and score each new item for relevance.
4. Persist new items to Supabase.
5. Render a GitHub Pages dashboard (docs/index.html + dated archive copy).
6. Email the digest via Resend.

Designed to run once a day from GitHub Actions. See README.md for setup.
"""

import os
import re
import sys
import json
import time
import html
import hashlib
import datetime as dt
from urllib.parse import quote_plus

import requests
import feedparser
import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

# --------------------------------------------------------------------------- #
# Config / secrets (from environment — set as GitHub Actions secrets)
# --------------------------------------------------------------------------- #
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
SUPABASE_URL      = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY      = os.environ["SUPABASE_KEY"]
RESEND_API_KEY    = os.environ.get("RESEND_API_KEY")
EMAIL_TO          = [e.strip() for e in os.environ.get("DIGEST_EMAIL_TO", "").split(",") if e.strip()]
EMAIL_FROM        = os.environ.get("DIGEST_EMAIL_FROM", "")

MODEL          = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
MAX_ITEMS      = int(os.environ.get("MAX_ITEMS", "60"))          # cap new items summarized per run
BATCH_SIZE     = int(os.environ.get("BATCH_SIZE", "25"))         # items per Claude call
MIN_SCORE      = int(os.environ.get("MIN_SCORE", "3"))           # only show items scoring >= this
SITE_BASE_URL  = os.environ.get("SITE_BASE_URL", "")            # e.g. https://USER.github.io/REPO

HERE  = os.path.dirname(os.path.abspath(__file__))
DOCS  = os.path.join(HERE, "docs")
ARCH  = os.path.join(DOCS, "archive")
TABLE = "news_items"

# Fixed display order, aligned to the formulary categories.
CATEGORY_ORDER = [
    "Regulatory/FDA",
    "Peptides",
    "GLP-1 / Weight Loss",
    "HRT/TRT",
    "Sexual Health",
    "Hair Loss",
    "Skincare",
    "Wellness / Anti-Aging",
    "Telehealth",
    "Other",
]

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def strip_html(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def norm_title(title: str) -> str:
    """Normalized title used as the dedup key, so the same story from two feeds collapses."""
    t = title.lower()
    t = re.sub(r"[^a-z0-9 ]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def item_id(title: str) -> str:
    return hashlib.sha1(norm_title(title).encode("utf-8")).hexdigest()


def parse_date(entry) -> str | None:
    for key in ("published_parsed", "updated_parsed"):
        val = entry.get(key)
        if val:
            return dt.datetime(*val[:6], tzinfo=dt.timezone.utc).isoformat()
    return None


# --------------------------------------------------------------------------- #
# 1. Ingest
# --------------------------------------------------------------------------- #
def fetch_google_news(query: str) -> list[dict]:
    url = (
        "https://news.google.com/rss/search?q="
        + quote_plus(query)
        + "&hl=en-US&gl=US&ceid=US:en"
    )
    feed = feedparser.parse(url)
    out = []
    for e in feed.entries:
        title = strip_html(e.get("title", ""))
        if not title:
            continue
        src = ""
        if e.get("source") and isinstance(e.source, dict):
            src = e.source.get("title", "")
        out.append({
            "title": title,
            "link": e.get("link", ""),
            "source": src or "Google News",
            "snippet": strip_html(e.get("summary", ""))[:400],
            "published_at": parse_date(e),
        })
    return out


def fetch_federal_register(term: str) -> list[dict]:
    url = "https://www.federalregister.gov/api/v1/documents.json"
    params = {
        "per_page": 20,
        "order": "newest",
        "conditions[term]": term,
        "conditions[agencies][]": "food-and-drug-administration",
    }
    try:
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        results = r.json().get("results", [])
    except Exception as exc:                                    # noqa: BLE001
        print(f"  ! Federal Register '{term}' failed: {exc}")
        return []
    out = []
    for d in results:
        out.append({
            "title": strip_html(d.get("title", "")),
            "link": d.get("html_url", ""),
            "source": f"Federal Register ({d.get('type', 'Notice')})",
            "snippet": strip_html(d.get("abstract", ""))[:400],
            "published_at": (d.get("publication_date") or "") + "T00:00:00+00:00"
            if d.get("publication_date") else None,
        })
    return out


def fetch_rss(name: str, url: str) -> list[dict]:
    feed = feedparser.parse(url)
    out = []
    for e in feed.entries:
        title = strip_html(e.get("title", ""))
        if not title:
            continue
        out.append({
            "title": title,
            "link": e.get("link", ""),
            "source": name,
            "snippet": strip_html(e.get("summary", ""))[:400],
            "published_at": parse_date(e),
        })
    return out


def ingest(cfg: dict) -> list[dict]:
    items: dict[str, dict] = {}

    def add(rows):
        for row in rows:
            if not row["title"] or not row["link"]:
                continue
            iid = item_id(row["title"])
            row["id"] = iid
            items.setdefault(iid, row)            # first occurrence wins

    print("Ingesting Google News queries...")
    for q in cfg.get("google_news", []) or []:
        add(fetch_google_news(q))
        time.sleep(0.5)                            # be polite

    print("Ingesting Federal Register...")
    for t in cfg.get("federal_register", []) or []:
        add(fetch_federal_register(t))
        time.sleep(0.3)

    print("Ingesting RSS feeds...")
    for f in cfg.get("rss", []) or []:
        if isinstance(f, dict) and f.get("url"):
            add(fetch_rss(f.get("name", "RSS"), f["url"]))

    print(f"  -> {len(items)} unique items ingested")
    return list(items.values())


# --------------------------------------------------------------------------- #
# 2. Dedup against Supabase
# --------------------------------------------------------------------------- #
def sb_headers(extra=None):
    h = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    if extra:
        h.update(extra)
    return h


def existing_ids(ids: list[str]) -> set[str]:
    found: set[str] = set()
    for i in range(0, len(ids), 100):
        chunk = ids[i:i + 100]
        in_clause = "(" + ",".join(chunk) + ")"
        url = f"{SUPABASE_URL}/rest/v1/{TABLE}?select=id&id=in.{in_clause}"
        r = requests.get(url, headers=sb_headers(), timeout=30)
        r.raise_for_status()
        found.update(row["id"] for row in r.json())
    return found


def insert_items(rows: list[dict]) -> None:
    if not rows:
        return
    url = f"{SUPABASE_URL}/rest/v1/{TABLE}?on_conflict=id"
    r = requests.post(
        url,
        headers=sb_headers({"Prefer": "resolution=ignore-duplicates,return=minimal"}),
        data=json.dumps(rows),
        timeout=60,
    )
    if r.status_code >= 300:
        print(f"  ! Supabase insert error {r.status_code}: {r.text[:300]}")
    r.raise_for_status()


# --------------------------------------------------------------------------- #
# 3. Summarize + categorize + score with Claude
# --------------------------------------------------------------------------- #
SYSTEM_PROMPT = """You are a pharma-industry news analyst preparing a daily digest for a \
compounding pharmacy. The relevant beats, drawn from their formulary, are: compounded peptides \
(BPC-157, TB-500, GHK-Cu, CJC-1295/ipamorelin, sermorelin, tesamorelin, MOTS-c, KPV, PT-141, \
thymosin alpha-1, pentadeca arginate); GLP-1 / medical weight loss (semaglutide, tirzepatide, \
phentermine); HRT/TRT (testosterone, estradiol, progesterone, enclomiphene, clomiphene, \
anastrozole, thyroid); sexual health (sildenafil, tadalafil, PT-141, Tri-Mix, oxytocin); hair \
loss (finasteride, minoxidil, dutasteride); skincare (tretinoin, hydroquinone, kojic/azelaic \
acid); and wellness/anti-aging (NAD+, glutathione, ketamine, low-dose naltrexone). Compounding \
regulation and telehealth-competitor news are central.

You will receive a JSON array of news items. For EACH item, return an object with:
  - "id": copy the id exactly
  - "category": exactly one of ["Regulatory/FDA","Peptides","GLP-1 / Weight Loss","HRT/TRT",
    "Sexual Health","Hair Loss","Skincare","Wellness / Anti-Aging","Telehealth","Other"].
    Use "Regulatory/FDA" for FDA actions, rules, bulks-list/PCAC decisions, enforcement, or
    legislation even when drug-specific. Use "Telehealth" for competitor/company news (Hims,
    Ro, etc.) not tied to one drug class.
  - "summary": one factual sentence, <= 30 words, plain language, no hype. Paraphrase only.
  - "score": integer 1-5 for relevance to the beats above. 5 = core, directly relevant
    industry news; 3 = tangential but on-topic; 1 = off-topic noise.

Return ONLY a JSON array, no prose, no markdown fences."""


def claude_batch(batch: list[dict]) -> dict[str, dict]:
    payload = [
        {"id": b["id"], "title": b["title"], "source": b["source"], "snippet": b["snippet"]}
        for b in batch
    ]
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": MODEL,
            "max_tokens": 4000,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": json.dumps(payload)}],
        },
        timeout=120,
    )
    r.raise_for_status()
    text = "".join(b.get("text", "") for b in r.json()["content"] if b.get("type") == "text")
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        text = text[4:].strip() if text.lower().startswith("json") else text.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        print("  ! Could not parse Claude output; skipping batch")
        return {}
    return {row["id"]: row for row in parsed if "id" in row}


def match_watch(item: dict, watch: list[dict]) -> list[str]:
    """Return labels of any watch entries whose keywords appear in the item."""
    hay = " ".join([
        item.get("title", ""), item.get("summary", ""), item.get("snippet", "")
    ]).lower()
    labels = []
    for w in watch:
        if any(str(k).lower() in hay for k in w.get("keywords", [])):
            labels.append(w["label"])
    return labels


def enrich(new_items: list[dict]) -> list[dict]:
    # newest first, capped
    new_items.sort(key=lambda x: x.get("published_at") or "", reverse=True)
    new_items = new_items[:MAX_ITEMS]

    enriched = []
    for i in range(0, len(new_items), BATCH_SIZE):
        batch = new_items[i:i + BATCH_SIZE]
        print(f"  summarizing {i + 1}-{i + len(batch)} of {len(new_items)}...")
        analysis = claude_batch(batch)
        for it in batch:
            a = analysis.get(it["id"], {})
            it["category"] = a.get("category", "Other")
            it["summary"] = a.get("summary", it.get("snippet", "")[:200])
            try:
                it["score"] = int(a.get("score", 1))
            except (TypeError, ValueError):
                it["score"] = 1
            enriched.append(it)
    return enriched


# --------------------------------------------------------------------------- #
# 4/5. Render dashboard + email
# --------------------------------------------------------------------------- #
def build_groups(items: list[dict]) -> list[dict]:
    shown = [i for i in items if i.get("score", 0) >= MIN_SCORE]
    by_cat: dict[str, list] = {}
    for it in shown:
        by_cat.setdefault(it["category"], []).append(it)
    groups = []
    for cat in CATEGORY_ORDER:
        rows = by_cat.get(cat)
        if not rows:
            continue
        rows.sort(key=lambda x: (-x.get("score", 0), x["title"]))
        groups.append({"category": cat, "items": rows})
    return groups


def render(env, template_name, **ctx) -> str:
    return env.get_template(template_name).render(**ctx)


def archive_list() -> list[dict]:
    if not os.path.isdir(ARCH):
        return []
    files = sorted(
        (f for f in os.listdir(ARCH) if f.endswith(".html")), reverse=True
    )[:30]
    return [{"date": f[:-5], "href": f"archive/{f}"} for f in files]


def write_outputs(groups, date_str, generated_at, total, watch=None):
    watch = watch or []
    env = Environment(
        loader=FileSystemLoader(os.path.join(HERE, "templates")),
        autoescape=select_autoescape(["html"]),
    )
    today_iso = now_utc().strftime("%Y-%m-%d")

    # dated archive copy first, so it appears in the archive list on the index
    os.makedirs(ARCH, exist_ok=True)
    page_ctx = dict(groups=groups, date_str=date_str, generated_at=generated_at,
                    total=total, watch=watch, is_archive=True, archives=[])
    with open(os.path.join(ARCH, f"{today_iso}.html"), "w") as fh:
        fh.write(render(env, "page.html.j2", **page_ctx))

    # index (latest)
    page_ctx.update(is_archive=False, archives=archive_list())
    with open(os.path.join(DOCS, "index.html"), "w") as fh:
        fh.write(render(env, "page.html.j2", **page_ctx))

    email_html = render(env, "email.html.j2", groups=groups, date_str=date_str,
                        generated_at=generated_at, total=total, watch=watch,
                        site_url=SITE_BASE_URL)
    return email_html


def send_email(html_body: str, date_str: str, total: int):
    if not (RESEND_API_KEY and EMAIL_TO and EMAIL_FROM):
        print("  ! Email not configured (RESEND_API_KEY / DIGEST_EMAIL_TO / DIGEST_EMAIL_FROM); skipping")
        return
    r = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
        json={
            "from": EMAIL_FROM,
            "to": EMAIL_TO,
            "subject": f"Daily Digest — {date_str} ({total} stories)",
            "html": html_body,
        },
        timeout=60,
    )
    if r.status_code >= 300:
        print(f"  ! Resend error {r.status_code}: {r.text[:300]}")
    else:
        print(f"  -> email sent to {', '.join(EMAIL_TO)}")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    with open(os.path.join(HERE, "feeds.yaml")) as fh:
        cfg = yaml.safe_load(fh)
    watch = cfg.get("watch", []) or []

    all_items = ingest(cfg)
    ids = [i["id"] for i in all_items]
    seen = existing_ids(ids)
    new_items = [i for i in all_items if i["id"] not in seen]
    print(f"{len(new_items)} new items (of {len(all_items)} ingested)")

    date_str = now_utc().strftime("%B %d, %Y")
    generated_at = now_utc().strftime("%Y-%m-%d %H:%M UTC")

    if not new_items:
        # still refresh the page (watch panel stays visible), but no email
        write_outputs([], date_str, generated_at, 0, watch=watch)
        print("No new items today. Page refreshed; no email sent.")
        return

    enriched = enrich(new_items)

    # flag any items that hit the standing watch list, and surface them
    for it in enriched:
        labels = match_watch(it, watch)
        if labels:
            it["watch_labels"] = labels
            it["score"] = max(int(it.get("score", 0)), 5)

    # persist everything we processed (so nothing is summarized twice)
    insert_items([
        {
            "id": it["id"], "title": it["title"][:500], "link": it["link"],
            "source": it.get("source", "")[:200], "category": it.get("category"),
            "summary": it.get("summary"), "score": it.get("score"),
            "published_at": it.get("published_at"),
        }
        for it in enriched
    ])

    groups = build_groups(enriched)
    total = sum(len(g["items"]) for g in groups)

    email_html = write_outputs(groups, date_str, generated_at, total, watch=watch)

    if total:
        send_email(email_html, date_str, total)
    else:
        print("No items cleared the relevance threshold; page refreshed, no email sent.")

    print("Done.")


if __name__ == "__main__":
    sys.exit(main())
