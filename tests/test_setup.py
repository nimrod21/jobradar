from app.setup import AI_PRESETS, migration_files


def test_migrations_present_and_ordered():
    files = migration_files()
    names = [f.name for f in files]
    assert names == sorted(names)
    assert names[0].startswith("001")
    assert len(names) >= 6


def test_presets_shape():
    for name, p in AI_PRESETS.items():
        assert p["api_base"].startswith("http"), name
        assert p["model"], name
        assert p["key_url"].startswith("http"), name
    assert "ollama" in AI_PRESETS  # the fully-local option
