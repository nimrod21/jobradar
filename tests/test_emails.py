from app.emails import company_tokens, match_email, strip_html_snippet


def test_company_tokens_strip_legal_and_short():
    assert company_tokens("Smartcat Inc.") == ["smartcat"]
    assert company_tokens("Norm AI LLC") == ["norm"]
    assert "gmbh" not in company_tokens("Acme GmbH")
    assert company_tokens(None) == []


def test_direct_domain_match():
    assert match_email("recruiting@smartcat.com", "Smartcat Talent",
                       "Your application", "Smartcat", "Senior AI Engineer")


def test_display_name_match():
    assert match_email("no-reply@notifications.example.net", "Smartcat Recruiting",
                       "Interview invitation", "Smartcat Inc.", "AI Engineer")


def test_ats_relay_requires_company_in_subject_or_name():
    assert match_email("no-reply@greenhouse.io", "",
                       "Your application to Workato", "Workato", "AI Engineer")
    assert not match_email("no-reply@greenhouse.io", "",
                           "Your application update", "Workato", "AI Engineer")


def test_ats_subdomain_counts_as_relay():
    assert match_email("jobs@mail.lever.co", "Plaid",
                       "Thanks for applying", "Plaid", "Engineer")


def test_lookalike_does_not_match():
    # 'cat' is a substring but tokens require the full 'smartcat' token in domain
    assert not match_email("newsletter@cat-facts.com", "Cat Facts Daily",
                           "Your daily cat", "Smartcat", "AI Engineer")
    assert not match_email("noreply@linkedin.com", "LinkedIn",
                           "Jobs you may like", "Smartcat", "AI Engineer")


def test_no_company_never_matches():
    assert not match_email("hr@anything.com", "HR", "Re: your application",
                           None, "Engineer")


def test_snippet_strips_html_and_caps():
    s = strip_html_snippet("<p>Hello <b>there</b>,</p>" + "x" * 500)
    assert "<" not in s and s.startswith("Hello there")
    assert len(s) <= 200
