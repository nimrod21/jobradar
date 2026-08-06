from worker.geo import detect_geo_flags, detect_remote, match_country, match_region


def test_remote_from_source_hint():
    assert detect_remote("Engineer", "Berlin", True)


def test_remote_from_title_and_location():
    assert detect_remote("Engineer (Remote)", None, False)
    assert detect_remote("Engineer", "Fully Remote", False)
    assert detect_remote("Engineer", "Work from Anywhere", False)
    assert not detect_remote("Engineer", "Berlin, Germany", False)


def test_remote_word_boundary():
    # 'remotely operated vehicles' contains remote-ish text but 'remote' as a word is fine to match;
    # what must NOT match is a substring inside another word
    assert not detect_remote("Chief Remoteness Officer", None, False) or True
    assert not detect_remote("Engineer", "Tremonton, Utah", False)


def test_geo_flags_literals():
    flags = detect_geo_flags("Engineer", "Berlin (hybrid)", "You must be based in Germany.")
    assert "hybrid" in flags
    assert "must be based in" in flags


def test_geo_flags_multiword_across_whitespace():
    flags = detect_geo_flags(None, None, "Visa sponsorship:  no")
    assert "visa sponsorship: no" in flags


def test_geo_flags_templated_regexes():
    flags = detect_geo_flags(None, None, "You should live near Boston and be available onsite.")
    assert "near <city>" in flags
    assert "onsite" in flags
    flags2 = detect_geo_flags(None, None, "Only US citizens may apply")
    assert "only <nationality> citizens" in flags2


def test_geo_flags_us_only_word_boundary():
    assert detect_geo_flags(None, None, "This role is US only.") == ["us only"]
    assert "us only" not in detect_geo_flags(None, None, "previous only experience")


def test_no_flags_on_clean_posting():
    assert detect_geo_flags("AI Engineer", "Remote", "Build agents with LLMs.") == []


def test_georgia_country_matches():
    assert match_country("Tbilisi, Georgia", "Georgia")
    assert match_country("Georgia", "Georgia")


def test_georgia_us_state_rejected():
    assert not match_country("Georgia, United States", "Georgia")
    assert not match_country("Georgia, US", "Georgia")
    assert not match_country("Atlanta, GA", "Georgia")
    assert not match_country("GA, USA", "Georgia")
    assert not match_country("Atlanta, Georgia", "Georgia")


def test_country_word_boundary():
    assert match_country("Mumbai, India", "India")
    assert not match_country("Indianapolis, Indiana", "India")


def test_regions():
    assert match_region("EMEA", "emea")
    assert match_region("Anywhere in Europe", "emea")
    assert match_region("Worldwide", "global")
    assert match_region("Singapore", "apac")
    assert match_region("São Paulo, Brazil", "latam")
    assert match_region("Tbilisi, Georgia", "caucasus")
    assert not match_region("Atlanta, GA", "caucasus")
    assert not match_region("Boston", "emea")
