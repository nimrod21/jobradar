from worker.slugs import parse_ats_url


def test_greenhouse():
    assert parse_ats_url("https://boards.greenhouse.io/workato/jobs/8675585002") == ("greenhouse", "workato")
    assert parse_ats_url("https://job-boards.greenhouse.io/gitlab/jobs/1") == ("greenhouse", "gitlab")


def test_ashby_url_decoded():
    assert parse_ats_url("https://jobs.ashbyhq.com/Scale%20Army%20Careers/abc-123") == ("ashby", "Scale Army Careers")


def test_lever():
    assert parse_ats_url("https://jobs.lever.co/plaid/00000000-0000") == ("lever", "plaid")


def test_workable():
    assert parse_ats_url("https://apply.workable.com/gramian/j/174189A027/") == ("workable", "gramian")


def test_breezy_subdomain():
    assert parse_ats_url("https://acme.breezy.hr/p/some-role") == ("breezy", "acme")


def test_personio():
    assert parse_ats_url("https://acme.jobs.personio.de/job/1") == ("personio", "acme")


def test_smartrecruiters():
    assert parse_ats_url("https://jobs.smartrecruiters.com/Bosch/744000-engineer") == ("smartrecruiters", "Bosch")


def test_rippling():
    assert parse_ats_url("https://ats.rippling.com/acme-jobs/jobs/1") == ("rippling", "acme-jobs")


def test_non_ats_hosts():
    assert parse_ats_url("https://remoteok.com/remote-jobs/1") is None
    assert parse_ats_url("https://acme.com/careers/1") is None
    assert parse_ats_url("not a url") is None


def test_generic_first_segment_not_mistaken_for_slug():
    assert parse_ats_url("https://apply.workable.com/j/ABC123") is None
