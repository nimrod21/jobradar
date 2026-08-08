from app.score_queue import eligible_providers, providers_from_cfg


def _p(name):
    return {"name": name, "api_base": f"https://{name}.example/v1",
            "api_key": "k", "model": "m"}


def test_eligible_respects_order_and_cooldowns():
    provs = [_p("groq"), _p("google"), _p("openrouter")]
    now = 1000.0
    assert [p["name"] for p in eligible_providers(provs, {}, now)] == \
        ["groq", "google", "openrouter"]
    cooled = {"groq": now + 60}
    assert [p["name"] for p in eligible_providers(provs, cooled, now)] == \
        ["google", "openrouter"]
    expired = {"groq": now - 1}
    assert [p["name"] for p in eligible_providers(provs, expired, now)][0] == "groq"


def test_providers_from_cfg_list():
    cfg = {"providers": [
        {"name": "groq", "api_base": "https://api.groq.com/openai/v1",
         "api_key": "k", "model": "llama"},
        {"api_base": "https://api.x.ai/v1", "api_key": "k2", "model": "m"},
        {"name": "broken", "api_base": "", "api_key": "k3"},        # dropped
        {"name": "nokey", "api_base": "https://paid.example/v1"},   # dropped
        {"name": "ollama", "api_base": "http://localhost:11434/v1", "model": "m"},
    ]}
    provs = providers_from_cfg(cfg)
    names = [p["name"] for p in provs]
    assert names == ["groq", "api.x.ai", "ollama"]   # keyless local kept


def test_providers_from_cfg_legacy_flat():
    cfg = {"openrouter_api_key": "sk-x", "model": "nemotron",
           "api_base": "https://openrouter.ai/api/v1"}
    provs = providers_from_cfg(cfg)
    assert len(provs) == 1
    assert provs[0]["name"] == "openrouter" and provs[0]["model"] == "nemotron"


def test_providers_from_cfg_empty():
    assert providers_from_cfg({}) == []
