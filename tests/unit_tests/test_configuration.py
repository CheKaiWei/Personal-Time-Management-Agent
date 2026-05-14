from agent.config import DEFAULT_SYSTEM_PROMPT, get_openai_settings
from agent.graph import _normalize_messages


def test_get_openai_settings_falls_back_to_codex(monkeypatch, tmp_path) -> None:
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    (codex_dir / "auth.json").write_text(
        '{"OPENAI_API_KEY": "codex-key"}',
        encoding="utf-8",
    )
    (codex_dir / "config.toml").write_text(
        """
model = "gpt-5.4"

[model_providers.OpenAI]
base_url = "https://example.test/v1"
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_SYSTEM_PROMPT", raising=False)

    settings = get_openai_settings(codex_dir=codex_dir)

    assert settings.api_key == "codex-key"
    assert settings.base_url == "https://example.test/v1"
    assert settings.model == "gpt-5.4"
    assert settings.system_prompt == DEFAULT_SYSTEM_PROMPT


def test_environment_values_override_codex(monkeypatch, tmp_path) -> None:
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    (codex_dir / "auth.json").write_text(
        '{"OPENAI_API_KEY": "codex-key"}',
        encoding="utf-8",
    )

    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://env.example/v1")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.5")
    monkeypatch.setenv("OPENAI_SYSTEM_PROMPT", "Respond in one line.")

    settings = get_openai_settings(codex_dir=codex_dir)

    assert settings.api_key == "env-key"
    assert settings.base_url == "https://env.example/v1"
    assert settings.model == "gpt-5.5"
    assert settings.system_prompt == "Respond in one line."


def test_normalize_messages_supports_legacy_input() -> None:
    assert _normalize_messages({"changeme": "hello"}) == [
        {"role": "user", "content": "hello"}
    ]
