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

-- Enable Row-Level Security. With RLS ON and NO policies defined, the anon and
-- publishable keys get zero access (this is a private, server-only table). The
-- pipeline is unaffected: digest.py uses the Supabase SECRET (service_role) key,
-- which bypasses RLS. This clears the "rls_disabled_in_public" security warning.
alter table public.news_items enable row level security;
