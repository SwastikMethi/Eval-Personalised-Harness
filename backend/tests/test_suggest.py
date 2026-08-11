"""AI-assisted setup: digest safety and suggestion parsing.

The digest is the only thing in this product that sends repository content to a
third party, so "no secrets leave the machine" is the property that matters
most here. Parsing is deliberately paranoid: a model's output is a suggestion,
and an invented command or a hallucinated sha must never reach the user as
though it were detected fact.
"""

import json
from pathlib import Path

import pytest

from app.repositories.digest import MAX_TOTAL_CHARS, build_digest, is_secret
from app.repositories.suggest import SuggestionError, parse_suggestion

# --- digest safety ----------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [".env", ".env.local", "id_rsa", "server.pem", "app.key", "aws_credentials", "my_secret.txt"],
)
def test_secret_files_are_recognised(name: str) -> None:
    assert is_secret(name)


def test_secrets_never_reach_the_digest(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# project\nrun tests with pytest")
    (tmp_path / ".env").write_text("OPENROUTER_API_KEY=sk-or-v1-SUPERSECRET")
    (tmp_path / "id_rsa").write_text("-----BEGIN OPENSSH PRIVATE KEY-----")
    (tmp_path / "app.py").write_text("print('hi')")

    digest = build_digest(tmp_path)
    text = digest.as_prompt_text()

    assert "SUPERSECRET" not in text
    assert "BEGIN OPENSSH PRIVATE KEY" not in text
    # Not even named in the tree listing.
    assert ".env" not in text
    assert "id_rsa" not in text
    assert "README.md" in text


def test_only_manifests_are_read_not_all_source(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\naddopts = '-q'")
    # A neutral filename: source is listed but never read, so a hardcoded
    # credential inside ordinary code still does not leave the machine.
    (tmp_path / "config_loader.py").write_text("TOKEN = 'do-not-send-me'")

    digest = build_digest(tmp_path)
    assert "pyproject.toml" in digest.files
    # Listed by name, never read — an allowlist, not a blocklist.
    assert "config_loader.py" in digest.tree
    assert "config_loader.py" not in digest.files
    assert "do-not-send-me" not in digest.as_prompt_text()


def test_noisy_directories_are_skipped(tmp_path: Path) -> None:
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / "package.json").write_text("{}")
    (tmp_path / "package.json").write_text('{"scripts":{"test":"vitest"}}')

    digest = build_digest(tmp_path)
    assert "package.json" in digest.files
    assert not any("node_modules" in p for p in digest.tree)


def test_prompt_text_is_bounded(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("x" * 50_000)
    assert len(build_digest(tmp_path).as_prompt_text()) <= MAX_TOTAL_CHARS


# --- suggestion parsing -----------------------------------------------------

SHAS = {"aaaaaaaa1111", "bbbbbbbb2222"}


def _payload(**over: object) -> str:
    body = {
        "commands": {
            "install": "pip install -r requirements.txt",
            "build": None,
            "test": "pytest -q",
            "lint": "  ",
            "typecheck": None,
            "test_framework": "pytest",
        },
        "rationale": {"test": "pyproject.toml configures pytest"},
        "confidence": "high",
        "commits": [{"sha": "aaaaaaaa1111", "why": "fixes a bug and adds a test"}],
    }
    body.update(over)
    return json.dumps(body)


def test_parses_a_clean_response() -> None:
    s = parse_suggestion(_payload(), "m1", SHAS)
    assert s.commands["test"] == "pytest -q"
    assert s.test_framework == "pytest"
    assert s.confidence == "high"
    assert s.commits[0]["sha"] == "aaaaaaaa1111"


def test_blank_and_missing_commands_stay_absent() -> None:
    """A whitespace command is not a command. Inventing one is worse than null."""
    s = parse_suggestion(_payload(), "m1", SHAS)
    assert s.commands["lint"] is None
    assert s.commands["build"] is None
    assert s.commands["typecheck"] is None


def test_fenced_json_is_tolerated() -> None:
    s = parse_suggestion(f"Here you go:\n```json\n{_payload()}\n```\n", "m1", SHAS)
    assert s.commands["test"] == "pytest -q"


def test_hallucinated_sha_is_dropped() -> None:
    """A sha we never supplied cannot be replayed, so it must not be offered."""
    s = parse_suggestion(
        _payload(commits=[{"sha": "deadbeef9999", "why": "invented"}]), "m1", SHAS
    )
    assert s.commits == []


def test_malformed_output_errors_rather_than_raising_something_random() -> None:
    with pytest.raises(SuggestionError, match="did not return JSON"):
        parse_suggestion("I'm afraid I can't help with that.", "m1", SHAS)
    with pytest.raises(SuggestionError, match="malformed JSON"):
        parse_suggestion('{"commands": {oops}}', "m1", SHAS)


def test_junk_types_do_not_crash_the_parser() -> None:
    s = parse_suggestion(
        json.dumps({"commands": "not-a-dict", "commits": "nope", "rationale": 7}), "m1", SHAS
    )
    assert all(v is None for v in s.commands.values())
    assert s.commits == []
    assert s.rationale == {}
    assert s.confidence == "low"  # anything but explicit "high" is low
