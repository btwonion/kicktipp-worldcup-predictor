import config


def test_load_settings_reads_env_file_without_python_dotenv(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "THE_ODDS_API_KEY=odds-key",
                "FOOTBALL_DATA_API_KEY='football-data-key'",
                'API_FOOTBALL_KEY="api-football-key"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "load_dotenv", None)
    monkeypatch.delenv("THE_ODDS_API_KEY", raising=False)
    monkeypatch.delenv("FOOTBALL_DATA_API_KEY", raising=False)
    monkeypatch.delenv("API_FOOTBALL_KEY", raising=False)

    settings = config.load_settings(env_file)

    assert settings.the_odds_api_key == "odds-key"
    assert settings.football_data_api_key == "football-data-key"
    assert settings.api_football_key == "api-football-key"


def test_load_settings_fallback_does_not_override_existing_environment(
    tmp_path, monkeypatch
):
    env_file = tmp_path / ".env"
    env_file.write_text("THE_ODDS_API_KEY=file-key", encoding="utf-8")
    monkeypatch.setattr(config, "load_dotenv", None)
    monkeypatch.setenv("THE_ODDS_API_KEY", "environment-key")
    monkeypatch.delenv("FOOTBALL_DATA_API_KEY", raising=False)
    monkeypatch.delenv("API_FOOTBALL_KEY", raising=False)

    settings = config.load_settings(env_file)

    assert settings.the_odds_api_key == "environment-key"
