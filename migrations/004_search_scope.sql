-- Include-term scope per tracker: title-only search cuts the "mentions AI
-- once in the description" noise.

alter table trackers add column search_in text not null default 'both';
-- both | title | description

create index jobs_title_vec_idx on jobs using gin (to_tsvector('english', coalesce(title, '')));
create index jobs_desc_vec_idx  on jobs using gin (to_tsvector('english', coalesce(description, '')));
