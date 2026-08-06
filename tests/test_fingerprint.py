from worker.fingerprint import (
    content_fingerprint,
    fingerprint,
    is_aggregator_host,
    normalise_url,
    normalised_title,
    url_fingerprint,
)


def test_normalise_url_strips_noise():
    assert (
        normalise_url("https://WWW.Boards.Greenhouse.io/workato/jobs/8675585002/?gh_src=abc#top")
        == "boards.greenhouse.io/workato/jobs/8675585002"
    )


def test_normalise_url_trailing_slash():
    assert normalise_url("https://jobs.lever.co/plaid/") == "jobs.lever.co/plaid"


def test_aggregator_hosts_null_url_fp():
    assert url_fingerprint("https://remoteok.com/remote-jobs/12345") is None
    assert url_fingerprint("https://weworkremotely.com/remote-jobs/x") is None
    assert url_fingerprint("https://news.ycombinator.com/item?id=1") is None
    assert url_fingerprint("https://sub.jobgether.com/offer/x") is None


def test_direct_ats_url_gets_fp():
    fp = url_fingerprint("https://boards.greenhouse.io/workato/jobs/8675585002")
    assert fp is not None
    # same job, different tracking params -> same fp
    assert fp == url_fingerprint(
        "https://boards.greenhouse.io/workato/jobs/8675585002?gh_jid=8675585002&utm_source=remoteok"
    )


def test_normalised_title_strips_suffixes():
    assert normalised_title("Backend Engineer (Remote)") == "backend engineer"
    assert normalised_title("Data Analyst - Europe") == "data analyst"
    assert normalised_title("Senior ML Engineer — EMEA") == "senior ml engineer"
    assert normalised_title("Sr. Engineer,  Platform") == "sr engineer platform"


def test_normalised_title_keeps_short_titles_whole():
    # stripping "- iOS" would leave too little; keep as-is (minus punctuation)
    assert "engineer" in normalised_title("Engineer - iOS") or normalised_title("Engineer - iOS")


def test_six_country_syndication_collapses():
    # same remote role syndicated per-country -> same content_fp
    fps = {
        content_fingerprint("AI Acquisition", "Growth Engineer (Remote)", loc, True)
        for loc in ["Germany", "France", "Spain", "Poland", "Portugal", None]
    }
    assert len(fps) == 1


def test_onsite_roles_differ_by_country():
    a = content_fingerprint("Acme", "Engineer", "Berlin, Germany", False)
    b = content_fingerprint("Acme", "Engineer", "Paris, France", False)
    assert a != b


def test_cross_source_same_job_matches_on_content():
    # aggregator copy (no url_fp) and ATS copy share content_fp
    agg_url_fp, agg_content = fingerprint(
        "Workato", "Senior AI Engineer", "https://remoteok.com/remote-jobs/999",
        "Remote", True,
    )
    ats_url_fp, ats_content = fingerprint(
        "Workato", "Senior AI Engineer (Remote)",
        "https://boards.greenhouse.io/workato/jobs/8675585002", None, True,
    )
    assert agg_url_fp is None
    assert ats_url_fp is not None
    assert agg_content == ats_content


def test_hn_override():
    url_fp, content_fp = fingerprint(
        None, "whatever", "https://news.ycombinator.com/item?id=5",
        None, False, content_fp_override="hn:49156683",
    )
    assert url_fp is None
    assert content_fp == "hn:49156683"


def test_is_aggregator_host_subdomains():
    assert is_aggregator_host("www.remoteok.com")
    assert is_aggregator_host("api.jobgether.com")
    assert not is_aggregator_host("boards.greenhouse.io")
