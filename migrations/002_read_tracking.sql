-- Per-job read state. "New" means the job was never opened in the detail
-- pane, not "the tracker was glanced at" — counts decrement one by one.

alter table jobs add column viewed_at timestamptz;
create index jobs_unviewed_idx on jobs (id) where viewed_at is null;

-- superseded by per-job state
alter table trackers drop column last_viewed_at;
