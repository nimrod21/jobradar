import pytest

from app.scoring import build_messages, parse_verdict, profile_version

PROFILE = {
    "summary": "Full-stack + AI engineer, Python/TS, 6 years",
    "conf_coding": 5, "conf_design": 7, "conf_english": 8,
    "needs_sponsorship": False, "min_salary": 60000, "salary_currency": "USD",
    "tz_range": "UTC+0..UTC+6", "contract_ok": True,
    "domains_avoid": ["gambling", "crypto"], "domains_love": ["devtools"],
    "stack_love": ["Python", "Claude"], "stack_avoid": ["Java"],
    "dealbreakers": "No 100% travel roles",
}

JOB = {
    "title": "Senior AI Engineer", "company": "Smartcat",
    "location_raw": "Europe", "remote_flag": True, "geo_flags": [],
    "salary_raw": "$120k-$160k", "employment_type": "Full time",
    "description": "Build agentic pipelines with LLM tool calling." * 300,
}


def test_build_messages_includes_calibration():
    msgs = build_messages(PROFILE, JOB)
    user = msgs[1]["content"]
    assert "live-coding/algorithms 5" in user
    assert "system design 7" in user
    assert "gambling, crypto" in user
    assert "No 100% travel roles" in user
    assert "Senior AI Engineer" in user


def test_build_messages_truncates_description():
    msgs = build_messages(PROFILE, JOB)
    assert len(msgs[1]["content"]) < 8500


def test_profile_version_changes_with_content():
    v1 = profile_version(PROFILE)
    assert v1 == profile_version(dict(PROFILE))
    assert v1 != profile_version({**PROFILE, "conf_coding": 9})
    assert len(v1) == 12


def test_parse_clean():
    v = parse_verdict('{"score": 82, "label": "safe", "one_liner": "Great fit.",'
                      '"reasons_for": ["Python", "agentic work"],'
                      '"reasons_against": ["salary unclear"], "dealbreaker_hits": []}')
    assert v["score"] == 82 and v["label"] == "safe"
    assert v["reasons_for"] == ["Python", "agentic work"]


def test_parse_fenced_and_prose_wrapped():
    v = parse_verdict('Sure! Here you go:\n```json\n{"score": 40, "label": "stretch",'
                      '"one_liner": "x", "reasons_for": [], "reasons_against": [],'
                      '"dealbreaker_hits": []}\n```')
    assert v["score"] == 40 and v["label"] == "stretch"


def test_parse_dealbreaker_caps_score():
    v = parse_verdict('{"score": 88, "label": "safe", "one_liner": "x",'
                      '"reasons_for": [], "reasons_against": [],'
                      '"dealbreaker_hits": ["gambling company"]}')
    assert v["score"] <= 20


def test_parse_clamps_score():
    assert parse_verdict('{"score": 150, "label": "safe", "one_liner": "x",'
                         '"reasons_for": [], "reasons_against": [],'
                         '"dealbreaker_hits": []}')["score"] == 100


def test_parse_float_integer_score_ok():
    assert parse_verdict('{"score": 70.0, "label": "safe", "one_liner": "x",'
                         '"reasons_for": [], "reasons_against": [],'
                         '"dealbreaker_hits": []}')["score"] == 70


def test_parse_rejects_garbage():
    with pytest.raises(ValueError):
        parse_verdict("I think this job is a great fit!")
    with pytest.raises(ValueError):
        parse_verdict('{"score": "high", "label": "safe"}')
    with pytest.raises(ValueError):
        parse_verdict('{"score": 50, "label": "amazing", "one_liner": "x"}')


def test_parse_limits_list_lengths():
    v = parse_verdict('{"score": 50, "label": "stretch", "one_liner": "x",'
                      '"reasons_for": ["a","b","c","d","e"], "reasons_against": [],'
                      '"dealbreaker_hits": []}')
    assert len(v["reasons_for"]) == 3
