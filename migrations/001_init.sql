-- JobRadar schema. Apply with psql or the Supabase SQL editor.

create table jobs (
  id            bigint generated always as identity primary key,
  url_fp        text,                          -- normalised-apply-URL hash; null when the host is a known aggregator/redirect
  content_fp    text not null,                 -- sha1(company | normalised_title | geo) — always computed
  title         text not null,
  company       text,
  location_raw  text,                          -- verbatim, whatever the source said
  remote_flag   boolean,                       -- derived, unreliable alone
  geo_flags     text[] not null default '{}',  -- matched red-flag phrases
  employment_type text,
  salary_raw    text,                          -- verbatim
  salary_min    numeric,                       -- best effort
  salary_max    numeric,
  salary_currency text,
  salary_period text,                          -- hour | day | month | year
  description   text,                          -- plain text, HTML stripped at ingest — feeds search_vec and geo scanning
  description_html text,                       -- verbatim source HTML, only for rendering the detail pane
  apply_url     text not null,
  posted_at     timestamptz,                   -- normalised at ingest
  posted_at_confident boolean not null default true,
  updated_at_src timestamptz,                  -- source's modified date, if given
  first_seen_at timestamptz not null default now(),
  last_seen_at  timestamptz not null default now(),
  status        text not null default 'new',   -- new|interesting|applied|replied|rejected|dead
  notes         text,
  apply_clicked_at timestamptz,                -- stamped when the app's Apply button opened the URL; drives the Applied page
  applied_at    timestamptz,                   -- set when the human confirms on the Applied page
  search_vec    tsvector generated always as (
                  setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
                  setweight(to_tsvector('english', coalesce(company, '')), 'B') ||
                  setweight(to_tsvector('english', coalesce(description, '')), 'C')
                ) stored
);

create unique index jobs_url_fp_idx     on jobs (url_fp) where url_fp is not null;
create unique index jobs_content_fp_idx on jobs (content_fp);
create index jobs_search_idx   on jobs using gin (search_vec);
create index jobs_posted_idx   on jobs (posted_at desc);
create index jobs_status_idx   on jobs (status);
create index jobs_company_idx  on jobs (lower(company));
create index jobs_geo_idx      on jobs using gin (geo_flags);

create table job_sources (
  job_id        bigint not null references jobs(id) on delete cascade,
  source        text not null,                 -- 'remoteok' | 'greenhouse:workato' | ...
  source_job_id text,
  source_url    text,
  seen_at       timestamptz not null default now(),
  primary key (job_id, source)
);

create table ats_registry (
  id          bigint generated always as identity primary key,
  ats         text not null,                   -- greenhouse | ashby | lever | workable | ...
  slug        text not null,
  company     text,
  first_seen  timestamptz not null default now(),
  last_polled timestamptz,
  last_status int,
  last_new_job_at timestamptz,                 -- drives adaptive polling
  active      boolean not null default true,
  unique (ats, slug)
);

create table trackers (
  id            bigint generated always as identity primary key,
  name          text not null,
  include_terms text[] not null default '{}',  -- OR within the array
  exclude_terms text[] not null default '{}',
  exclude_companies text[] not null default '{}',
  date_window   text not null default '14d',   -- 24h | 7d | 14d | 30d | all
  location_mode text not null default 'any',   -- any | remote | text | region
  location_value text,
  enabled       boolean not null default true,
  last_viewed_at timestamptz,                  -- partition point for "new since last opened"
  created_at    timestamptz not null default now()
);

create table source_health (
  source        text primary key,
  last_success  timestamptz,
  last_error    text,
  last_error_at timestamptz,
  consecutive_failures int not null default 0,
  jobs_last_run int
);

-- Deny-all RLS: the auto-generated PostgREST API exposes nothing.
-- The worker and the app connect over direct Postgres as the table owner, which bypasses RLS.
alter table jobs          enable row level security;
alter table job_sources   enable row level security;
alter table ats_registry  enable row level security;
alter table trackers      enable row level security;
alter table source_health enable row level security;
