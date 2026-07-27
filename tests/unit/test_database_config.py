from bot_ofertas.storage import DatabaseSettings


def test_database_settings_hide_password(monkeypatch) -> None:
    monkeypatch.setenv("POSTGRES_DB", "offers")
    monkeypatch.setenv("POSTGRES_USER", "bot")
    monkeypatch.setenv("POSTGRES_PASSWORD", "a-secret-that-must-not-leak")
    monkeypatch.setenv("POSTGRES_HOST", "127.0.0.1")
    monkeypatch.setenv("POSTGRES_PORT", "5433")

    settings = DatabaseSettings.from_env()

    assert "a-secret-that-must-not-leak" not in repr(settings)
    assert "a-secret-that-must-not-leak" not in settings.safe_url
    assert "***" in settings.safe_url
    assert settings.port == 5433
