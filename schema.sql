-- schema.sql — run once in the Supabase SQL editor.
-- Creates the dedup/history table that digest.py reads and writes (TABLE = "news_items").
-- Columns match the payload in digest.py -> insert_items().

create table if not exists public.news_items (
    id            text primary key,        -- sha1 of the normalized title (dedup key)
    title         text not null,
    link          text,
    source        text,
    category      text,
    summary       text,
    score         integer,
    published_at  timestamptz,             -- story's own publish time (may be null)
    created_at    timestamptz not null default now()  -- when we first ingested it
);

-- Helpful indexes for the dedup lookup and any later reporting.
create index if not exists news_items_created_at_idx on public.news_items (created_at desc);
create index if not exists news_items_category_idx   on public.news_items (category);

-- The pipeline connects with the Supabase service_role key, which bypasses RLS.
-- Leaving RLS disabled is fine for a private, server-only table. If you prefer to
-- enable it, do so and rely on the service_role key (it ignores RLS policies):
-- alter table public.news_items enable row level security;
