"""Phase 3 — verify the AI backend is fully provider-swappable.

Guards the contract that every AI call goes through ``get_provider()`` (so
``AI_PROVIDER`` switches the model everywhere) and that provider SDKs are only
imported inside the abstraction (``app/services/llm.py``), never in call sites.
"""
import os
import re

import pytest

from app.services import llm
from app.core import config


class FakeProvider:
    def __init__(self, text):
        self.text = text
        self.name = "fake"

    async def complete(self, prompt, json_mode=False, temperature=0.7):
        return self.text


# ── Runtime: AI_PROVIDER actually selects the backend ─────────────────────────
def test_get_provider_reflects_ai_provider_setting(monkeypatch):
    original = config.settings.AI_PROVIDER
    monkeypatch.setattr(config.settings, "AI_PROVIDER", "groq")
    llm._PROVIDERS.clear()
    try:
        assert llm.get_provider().name == "groq"
    finally:
        monkeypatch.setattr(config.settings, "AI_PROVIDER", original)
        llm._PROVIDERS.clear()


def test_available_providers_lists_all_backends():
    assert set(llm.available_providers()) >= {"gemini", "groq", "ollama"}


# ── Runtime: a service routes through get_provider (so it is swappable) ────────
async def test_gemini_service_uses_get_provider(monkeypatch):
    from app.services import gemini_service
    monkeypatch.setattr(gemini_service, "get_provider", lambda: FakeProvider("FAKE_REPLY"))
    out = await gemini_service.generate_contractor_reply("hello", {"ai_tone_preference": "professional"})
    assert out == "FAKE_REPLY"


# ── Static guard: no provider SDK leaks into call sites ────────────────────────
def _app_py_sources():
    base = os.path.dirname(os.path.dirname(__file__))
    app_dir = os.path.join(base, "app")
    for root, _, files in os.walk(app_dir):
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(root, f)


PROVIDER_SDK_IMPORTS = re.compile(r"^\s*(import\s+google|from\s+google|import\s+groq|from\s+groq|import\s+openai|from\s+openai)", re.M)


def test_provider_sdks_only_inside_llm_abstraction():
    offenders = []
    for path in _app_py_sources():
        if os.path.basename(path) == "llm.py":
            continue
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        if PROVIDER_SDK_IMPORTS.search(src):
            offenders.append(path)
    assert offenders == [], f"Provider SDK imported outside llm.py: {offenders}"


def test_ai_call_sites_import_get_provider():
    expected = {
        "app/services/gemini_service.py",
        "app/services/intake_service.py",
        "app/services/quote_service.py",
        "app/services/voice_dispatch.py",
    }
    missing = []
    base = os.path.dirname(os.path.dirname(__file__))
    for rel in expected:
        path = os.path.join(base, rel)
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        if "get_provider" not in src:
            missing.append(rel)
    assert missing == [], f"AI call site missing get_provider(): {missing}"
