"""Deterministic JSON-Schema instance synthesis.

Used by the offline ``mock`` provider so that the full pipeline — including
structured stages such as outlining and claim extraction — can run with no
network access and no API keys.
"""

from __future__ import annotations

import random
import re
from typing import Any

_MAX_DEPTH = 8

_PATTERN_CANDIDATES = (
    "s1",
    "item-1",
    "ABC123",
    "2026-01-01",
    "example@example.com",
    "a",
    "id_1",
)


def resolve_ref(root: dict[str, Any], ref: str) -> dict[str, Any]:
    """Resolve a local ``#/...`` JSON pointer reference."""
    node: Any = root
    for raw in ref.lstrip("#/").split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or token not in node:
            return {}
        node = node[token]
    return node if isinstance(node, dict) else {}


def _merge_all_of(schema: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {key: value for key, value in schema.items() if key != "allOf"}
    properties: dict[str, Any] = dict(merged.get("properties") or {})
    required: list[str] = list(merged.get("required") or [])
    for part in schema.get("allOf") or []:
        resolved = resolve_ref(root, part["$ref"]) if "$ref" in part else part
        properties.update(resolved.get("properties") or {})
        required.extend(resolved.get("required") or [])
    if properties:
        merged["properties"] = properties
    if required:
        merged["required"] = required
    return merged


def _pick_branch(options: list[dict[str, Any]]) -> dict[str, Any]:
    for option in options:
        if option.get("type") not in (None, "null"):
            return option
    return options[0] if options else {}


def _string_value(schema: dict[str, Any], rng: random.Random, name: str) -> str:
    pattern = schema.get("pattern")
    if isinstance(pattern, str):
        for candidate in _PATTERN_CANDIDATES:
            try:
                if re.fullmatch(pattern, candidate):
                    return candidate
            except re.error:
                break

    fmt = schema.get("format")
    lowered = name.lower()
    if fmt == "email" or "email" in lowered:
        return "editor@example.com"
    if fmt in {"uri", "url"} or "url" in lowered or "link" in lowered:
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "source"
        return f"https://example.com/{slug}"
    if fmt == "date" or lowered.endswith("_at") or lowered == "date":
        return "2026-01-15"
    if fmt == "date-time":
        return "2026-01-15T09:00:00Z"

    min_length = int(schema.get("minLength", 0) or 0)
    max_length = int(schema.get("maxLength", 240) or 240)
    label = name.replace("_", " ").strip() or "value"
    base = f"Generated {label} for the run"
    if len(base) < min_length:
        base = base.ljust(min_length, "x")
    return base[:max_length]


def _number_value(schema: dict[str, Any], rng: random.Random) -> int | float:
    is_int = schema.get("type") == "integer"
    minimum = schema.get("minimum")
    maximum = schema.get("maximum")
    if minimum is None and maximum is None:
        return 1 if is_int else 0.5
    low = float(minimum) if minimum is not None else 0.0
    high = float(maximum) if maximum is not None else low + 10
    if high < low:
        low, high = high, low
    value = rng.uniform(low, high)
    return round(value) if is_int else round(value, 4)


def synthesize(
    schema: dict[str, Any],
    rng: random.Random,
    *,
    root: dict[str, Any] | None = None,
    name: str = "",
    depth: int = 0,
) -> Any:
    """Return a deterministic instance that satisfies ``schema``."""
    if depth > _MAX_DEPTH or not isinstance(schema, dict):
        return None
    root = root if root is not None else schema

    if "$ref" in schema and isinstance(schema["$ref"], str):
        return synthesize(
            resolve_ref(root, schema["$ref"]), rng, root=root, name=name, depth=depth + 1
        )
    if "allOf" in schema:
        return synthesize(_merge_all_of(schema, root), rng, root=root, name=name, depth=depth + 1)
    if "const" in schema:
        return schema["const"]
    for key in ("anyOf", "oneOf"):
        options = schema.get(key)
        if isinstance(options, list) and options:
            return synthesize(_pick_branch(options), rng, root=root, name=name, depth=depth + 1)
    if schema.get("enum"):
        return rng.choice(list(schema["enum"]))
    if "default" in schema:
        return schema["default"]

    declared = schema.get("type")
    if isinstance(declared, list):
        declared = next(
            (item for item in declared if item != "null"), declared[0] if declared else None
        )

    if declared == "object" or "properties" in schema:
        properties: dict[str, Any] = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        result: dict[str, Any] = {}
        for prop_name, prop_schema in properties.items():
            if prop_name not in required and rng.random() < 0.08:
                continue
            result[prop_name] = synthesize(
                prop_schema, rng, root=root, name=prop_name, depth=depth + 1
            )
        return result

    if declared == "array" or "items" in schema:
        items = schema.get("items") or {}
        min_items = int(schema.get("minItems", 0) or 0)
        max_items = schema.get("maxItems")
        count = max(min_items, 1)
        if max_items is not None:
            count = min(count, int(max_items))
        return [synthesize(items, rng, root=root, name=name, depth=depth + 1) for _ in range(count)]

    if declared == "string":
        return _string_value(schema, rng, name)
    if declared in {"integer", "number"}:
        return _number_value(schema, rng)
    if declared == "boolean":
        return rng.random() < 0.7
    if declared == "null":
        return None
    return None
