"""Robust parsing of model JSON into validated domain objects."""

from __future__ import annotations

import json
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from draftproof.domain.errors import InvalidModelOutputError

ModelT = TypeVar("ModelT", bound=BaseModel)


def strip_code_fence(text: str) -> str:
    """Remove a surrounding Markdown code fence when present."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) < 2:
        return stripped
    opening = lines[0].strip().strip("`").strip().lower()
    if opening not in {"", "json", "json5", "javascript", "text", "markdown", "md"}:
        return stripped
    body = lines[1:]
    if body and body[-1].strip().startswith("```"):
        body = body[:-1]
    return "\n".join(body).strip()


def extract_json(text: str) -> Any:
    """Extract the first JSON value from a model response."""
    candidate = strip_code_fence(text)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for index, char in enumerate(candidate):
        if char not in "{[":
            continue
        try:
            value, _end = decoder.raw_decode(candidate[index:])
        except json.JSONDecodeError:
            continue
        return value
    raise InvalidModelOutputError(
        "Model response did not contain valid JSON",
        snippet=candidate[:400],
    )


def parse_model(text: str, model: type[ModelT], *, task: str) -> ModelT:
    """Validate a model response against a Pydantic model."""
    payload = extract_json(text)
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        summary = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']) or '<root>'}: {error['msg']}"
            for error in exc.errors()[:4]
        )
        raise InvalidModelOutputError(
            f"Model output failed schema validation for task '{task}': {summary}",
            task=task,
            snippet=str(payload)[:400],
        ) from exc


def clean_section_markdown(text: str, *, title: str) -> str:
    """Normalize a drafted section: single heading, no fences, no preamble."""
    body = strip_code_fence(text) if text.strip().startswith("```markdown") else text.strip()
    lines = body.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and lines[0].startswith("# ") and not lines[0].startswith("## "):
        lines.pop(0)
        while lines and not lines[0].strip():
            lines.pop(0)
    if not lines or not lines[0].startswith("## "):
        lines.insert(0, f"## {title}")
        lines.insert(1, "")
    cleaned = "\n".join(lines).strip()
    if len(cleaned) < 80:
        raise InvalidModelOutputError(
            "Section draft was too short to publish",
            task="draft_section",
            snippet=cleaned[:200],
        )
    return cleaned + "\n"
