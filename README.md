# JobRadar

Personal job-search aggregator. A worker polls ~20 job sources hourly, normalises and de-duplicates everything into Postgres, and a desktop app searches the local copy — because job boards are individually bad at search. LinkedIn doesn't index description bodies; Workable turns "agentic" into 2,015 leasing-agent listings. Fetch from everything, store it once, search your own copy.

```
  [hourly scheduler on a VPS]
              |
      per-source fetchers          one module per source, common interface
              |
        normalise                  map every source into one schema
              |
     fingerprint + upsert          dedupe collapses at write time
              |
      Postgres tsvector            title + description, weighted
              |
         [Supabase]
              |
      desktop app (reader)         search, filter, track applications
```

## The interesting parts

- **A slug-harvesting registry.** Every job found on an aggregator carries an apply URL. Parse it, extract the ATS and company slug (`boards.greenhouse.io/workato/...` → `greenhouse:workato`), and poll that company's board directly forever after. Aggregators become a discovery mechanism; the registry becomes the real feed.
- **Dedupe as a database constraint.** Two fingerprints per job — a normalised-URL hash and a content hash — matched on either at write time, with unique indexes as the race backstop. The same requisition found on five boards collapses into one row that remembers all five sources.
- **Isolated source modules.** One adapter per source behind a common interface; a source changing its response shape fails alone and is recorded in `source_health`, never taking the run down.
- **Weighted full-text search.** A generated `tsvector` (title weighted above description) makes "AI" match the word *AI* and never *email*, *training* or *maintain* — the two-letter-keyword problem `LIKE '%AI%'` can't solve.

## Status

Under construction. Build order: schema → pure functions → source adapters → slug registry → desktop app.

## Setup

1. Create a Supabase project, run `migrations/*.sql` in order.
2. `cp .env.example .env`, fill `DATABASE_URL` with the **session pooler** connection string.
3. `pip install -r requirements.txt`
4. `python -m worker.main --once` for a single cycle.

No LinkedIn, Indeed or Glassdoor adapters — their terms prohibit automated access. Every source here is a public JSON API intended for programmatic use, an RSS feed, or a sitemap.
