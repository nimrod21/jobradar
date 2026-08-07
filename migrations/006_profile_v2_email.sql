-- Profile v2 (separate page, richer items) + email reply tracking.

alter table profile add column years_exp int;
alter table profile add column current_title text;
alter table profile add column target_roles text[] not null default '{}';
alter table profile add column target_level text default 'any';   -- any|junior|mid|senior|staff|lead
alter table profile add column conf_behavioral int check (conf_behavioral between 1 and 10);
alter table profile add column salary_target numeric;
alter table profile add column salary_period text default 'month'; -- month | year
alter table profile add column notice text;                        -- availability / notice period
alter table profile add column education text;
alter table profile add column languages text[] not null default '{}';
alter table profile add column citizenship text;

create table job_emails (
  id          bigint generated always as identity primary key,
  job_id      bigint not null references jobs(id) on delete cascade,
  account     text not null,
  msg_id      text not null,
  from_addr   text,
  subject     text,
  snippet     text,               -- first ~200 chars, for list rows
  body        text,               -- full sanitized body, expandable view
  attachments int not null default 0,
  received_at timestamptz,
  unique (job_id, msg_id)
);

alter table job_emails enable row level security;
