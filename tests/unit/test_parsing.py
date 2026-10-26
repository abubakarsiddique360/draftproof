"""Model-output parsing helpers."""

from __future__ import annotations

import pytest

from draftproof.domain.errors import InvalidModelOutputError
from draftproof.pipeline.parsing import (
    clean_section_markdown,
    extract_json,
    parse_model,
    strip_code_fence,
)
from draftproof.pipeline.schemas import RawClaims


def test_strip_code_fence_removes_json_block() -> None:
    assert strip_code_fence('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert strip_code_fence('plain {"a": 1}') == 'plain {"a": 1}'


def test_extract_json_from_prose() -> None:
    payload = extract_json('Sure! Here is the JSON:\n{"a": [1, 2], "b": "c"}\nEnjoy.')
    assert payload == {"a": [1, 2], "b": "c"}


def test_extract_json_raises_on_garbage() -> None:
    with pytest.raises(InvalidModelOutputError):
        extract_json("no json here at all")


def test_parse_model_validates() -> None:
    raw = parse_model(
        '{"claims": [{"text": "A claim", "evidence_ids": ["ev1"]}]}', RawClaims, task="claims"
    )
    assert raw.claims[0].text == "A claim"

    with pytest.raises(InvalidModelOutputError) as excinfo:
        parse_model('{"claims": "not a list"}', RawClaims, task="claims")
    assert "schema validation" in excinfo.value.message


def test_clean_section_markdown_adds_heading() -> None:
    cleaned = clean_section_markdown("Body paragraph without a heading. " * 4, title="My Section")
    assert cleaned.startswith("## My Section\n")
    assert cleaned.endswith("\n")


def test_clean_section_markdown_strips_h1_and_fence() -> None:
    text = (
        "```markdown\n# Big title\n\n## Real heading\n\n"
        + ("Some useful body text. " * 6)
        + "\n```"
    )
    cleaned = clean_section_markdown(text, title="Fallback")
    assert cleaned.startswith("## Real heading")
    assert "# Big title" not in cleaned


def test_clean_section_markdown_rejects_short_output() -> None:
    with pytest.raises(InvalidModelOutputError):
        clean_section_markdown("## T\n\ntoo short", title="T")
