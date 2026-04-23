"""Smoke test: verify Azure Kimi auth + endpoint work.

This test is deliberately minimal. It only runs if ``AZURE_KIMI_API_KEY``
is set; otherwise it's skipped. It sends a 2-word probe ("say hi in 2
words") through the chat completion endpoint and asserts that we got
*some* content back. It does NOT exercise the function-calling structured-
output path — that's covered by the CLI roundtrip tests.
"""

from __future__ import annotations

import os

import pytest


pytestmark = pytest.mark.skipif(
    not os.environ.get("AZURE_KIMI_API_KEY")
    or not os.environ.get("AZURE_KIMI_ENDPOINT"),
    reason="AZURE_KIMI_API_KEY / AZURE_KIMI_ENDPOINT not set",
)


def test_kimi_probe() -> None:
    """Minimal chat-completion probe."""
    from pipeline.extract import kimi

    client = kimi.get_client()
    resp = client.chat.completions.create(
        model=kimi._model_name(),
        messages=[
            {"role": "system", "content": "You are a terse assistant."},
            {"role": "user", "content": "say hi in 2 words"},
        ],
        max_tokens=2048,  # minimum for this reasoning model
    )
    assert resp.choices, "expected at least one choice"
    content = resp.choices[0].message.content
    assert content and isinstance(content, str), (
        f"expected non-empty content; got {content!r}"
    )
