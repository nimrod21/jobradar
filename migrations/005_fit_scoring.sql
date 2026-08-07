-- Fit scoring: single-row profile + per-job verdicts.

create table profile (
  id            smallint primary key default 1 check (id = 1),
  summary       text,
  conf_coding   int check (conf_coding between 1 and 10),
  conf_design   int check (conf_design between 1 and 10),
  conf_english  int check (conf_english between 1 and 10),
  needs_sponsorship boolean default false,
  min_salary    numeric,
  salary_currency text default 'USD',
  tz_range      text,
  contract_ok   boolean default true,
  domains_avoid text[] not null default '{}',
  domains_love  text[] not null default '{}',
  stack_love    text[] not null default '{}',
  stack_avoid   text[] not null default '{}',
  dealbreakers  text,
  version       text not null default ''
);

create table job_scores (
  job_id          bigint primary key references jobs(id) on delete cascade,
  profile_version text not null,     -- mismatch with profile.version = stale
  score           int,
  label           text,              -- safe | stretch | reach
  verdict         jsonb,
  model           text,
  failed          boolean not null default false,
  created_at      timestamptz not null default now()
);

alter table profile    enable row level security;
alter table job_scores enable row level security;
