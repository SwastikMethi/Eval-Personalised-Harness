"""The suite must never reach a real provider.

The free tier grants ~50 model requests a DAY, so a test run that leaks
upstream both spends the user's quota and turns unrelated assertions into
network flakes. This happened for real: NVIDIA_API_KEY was added to .env and
to Settings, but not to conftest's blanking list, so create_app() installed
NimProvider as the default and five proxy-budget tests started failing with
502s from live calls.

conftest blanks the keys; these tests fail loudly when a new provider is
added and that step is forgotten.
"""

from app.api import proxy
from app.core.config import Settings
from app.main import create_app
from app.providers.fake import FakeProvider


def test_every_provider_key_is_blank_during_tests() -> None:
    """Enumerated from Settings, not hardcoded, so adding a provider key
    without blanking it in conftest fails here instead of silently spending
    quota inside some unrelated test."""
    settings = Settings()
    key_fields = [name for name in type(settings).model_fields if name.endswith("_api_key")]

    assert key_fields, "no *_api_key fields found — did the settings naming change?"
    non_blank = [name for name in key_fields if getattr(settings, name)]
    assert not non_blank, (
        f"{non_blank} is set during tests. Add `os.environ[...] = \"\"` to "
        f"tests/conftest.py, or the suite will call the live provider."
    )


def test_created_app_stays_on_the_fake_provider() -> None:
    create_app(start_worker=False)
    assert isinstance(proxy.provider_for("openrouter"), FakeProvider)
    assert isinstance(proxy.provider_for("nvidia"), FakeProvider)
