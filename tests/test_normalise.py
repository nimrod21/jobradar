from worker.models import RawJob
from worker.normalise import normalise, parse_salary, strip_html


def _raw(**over):
    base = dict(
        source="remoteok",
        title="Senior AI Engineer",
        apply_url="https://boards.greenhouse.io/acme/jobs/123",
        company="Acme",
        location="Remote",
        remote_hint=True,
    )
    base.update(over)
    return RawJob(**base)


def test_strip_html_plain():
    assert strip_html("Just text, no tags") == "Just text, no tags"


def test_strip_html_tags_and_structure():
    text = strip_html("<p>First</p><ul><li>one</li><li>two</li></ul>")
    assert "First" in text and "one" in text and "two" in text
    assert "<" not in text


def test_strip_html_greenhouse_escaped():
    escaped = "&lt;p&gt;Build &amp;amp; ship agents&lt;/p&gt;"
    assert strip_html(escaped) == "Build & ship agents"


def test_strip_html_drops_script():
    assert "alert" not in strip_html("<p>hi</p><script>alert(1)</script>")


def test_normalise_splits_description_fields():
    job = normalise(_raw(description_html="<p>We use <strong>LLMs</strong> daily.</p>"))
    assert job.description == "We use LLMs daily."
    assert "<strong>" in job.description_html


def test_normalise_plain_text_description_has_no_html_kept():
    job = normalise(_raw(description_html="Plain description, no markup."))
    assert job.description == "Plain description, no markup."
    assert job.description_html is None


def test_normalise_search_never_sees_tags():
    job = normalise(_raw(description_html='<div class="hybrid-layout">Fully distributed team.</div>'))
    # 'hybrid' appears only in a class attribute — must NOT become a geo flag
    assert "hybrid" not in job.geo_flags


def test_normalise_sets_fingerprints_and_flags():
    job = normalise(_raw())
    assert job.url_fp is not None
    assert job.content_fp
    assert job.remote_flag is True


def test_modified_date_low_confidence():
    job = normalise(_raw(posted_raw="2026-08-01T00:00:00Z", posted_is_modified=True))
    assert job.posted_at is not None
    assert job.posted_at_confident is False


def test_unparseable_date_none_not_confident():
    job = normalise(_raw(posted_raw="recently"))
    assert job.posted_at is None
    assert job.posted_at_confident is False


def test_parse_salary_range_k():
    lo, hi, cur, period = parse_salary("$120k - $160k per year")
    assert lo == 120000 and hi == 160000
    assert cur == "USD" and period == "year"


def test_parse_salary_plain_numbers():
    lo, hi, cur, _ = parse_salary("€60,000 – €80,000")
    assert lo == 60000 and hi == 80000 and cur == "EUR"


def test_parse_salary_garbage():
    assert parse_salary("Competitive") == (None, None, None, None)
    assert parse_salary(None) == (None, None, None, None)


def test_source_numeric_salary_wins():
    job = normalise(_raw(salary_min=100000.0, salary_max=140000.0, salary_currency="USD",
                         salary_raw="$100,000 - $140,000"))
    assert job.salary_min == 100000.0 and job.salary_max == 140000.0
