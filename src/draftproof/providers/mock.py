"""Deterministic offline provider.

The mock provider does two things:

* it synthesizes schema-valid JSON for structured stages, either generically
  from the JSON schema or with hand-written fixtures for the two schemas that
  matter for content quality (``outline`` and ``claims``);
* it writes coherent Markdown for drafting stages, including citations to the
  evidence catalogue embedded in the prompt.

Everything is seeded from the request, so identical inputs always produce
identical output. That makes demos, documentation examples and the test suite
reproducible and dependency free.
"""

from __future__ import annotations

import hashlib
import random
import re
import time
from typing import Any

from draftproof.providers.base import Completion, CompletionRequest
from draftproof.providers.jsonschema_mock import synthesize

_EVIDENCE_LINE = re.compile(
    r"^-\s+(?P<id>[A-Za-z0-9_-]+)\s*\|\s*(?P<title>.*?)\s*\|\s*(?P<url>https?://\S+)\s*$"
)
_LINK = re.compile(r"\[(?P<label>[^\]]+)\]\((?P<url>https?://[^)\s]+)\)")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

_LEADS = (
    "For a first pass",
    "In practice",
    "At the boundary",
    "Under load",
    "During review",
    "On the first release",
    "In the smallest viable design",
    "When the system is quiet",
    "While the team is small",
    "In a mature codebase",
    "Across environments",
    "At the edge of the budget",
    "Before the first deploy",
    "In the runbook",
    "After an incident",
    "On a busy day",
)

_ACTIONS = (
    "keep the option set small",
    "name the invariant first",
    "measure before you optimise",
    "write the failure case down",
    "set an explicit budget",
    "remove the unused path",
    "prefer explicit over implicit",
    "record the decision",
    "split the long step",
    "make the default safe",
    "keep the vocabulary stable",
    "test the unhappy path",
    "pin the schema version",
    "log the identifier",
    "bound the retry count",
    "watch the tail latency",
)

_REASONS = (
    "because every extra branch is a future incident",
    "since the slow path is the one users notice",
    "so the next change stays cheap",
    "which keeps the rollback simple",
    "because hidden state is hard to debug",
    "so reviews stay focused",
    "which makes the metric trustworthy",
    "since the boundary is where defects appear",
    "so the cost stays visible",
    "which keeps the blast radius small",
    "because clarity compounds",
    "so the team can move quickly",
    "since surprises arrive in production",
    "which keeps the invariant checkable",
    "because the alternative is guesswork",
    "so the runbook stays short",
)

_OPENERS = (
    "{title} is easier to reason about once the moving parts are named.",
    "Most teams meet {title} long before they have a plan for it.",
    "The useful question behind {title} is not whether it works, but when it stops working.",
    "Treat {title} as an engineering surface, not a slogan.",
)

_CLOSERS = (
    "Applied consistently, that checklist keeps {title} predictable as the system grows.",
    "Instrument one real workflow for {title} and compare the result with the plan above.",
    "Once these pieces are in place, {title} becomes a routine part of the delivery pipeline.",
    "The next review of {title} should start from the measurements described here.",
)

_EVIDENCE_FRAMES = (
    "The analysis in {links} supports this part of {title}.",
    "{links} documents the same behaviour for {title}.",
    "The write-up in {links} matches what {title} needs.",
    "{links} describes the mechanism behind {title}.",
)

_AUDIENCE_TAILS = (
    "Readers in {audience} should treat that as the baseline for {title}.",
    "That baseline is what {audience} need before {title} can scale.",
    "For {audience}, the baseline behind {title} is the useful part.",
    "The baseline holds for {audience} working on {title} as well.",
)

_SEQUENCE = re.compile(r"^Section id:\s*s(\d+)\s*$", re.MULTILINE)


def _sentence_pool(seed: int) -> list[str]:
    """Build 256 sentences with unique action/reason pairs.

    Unique pairs guarantee that no 12-word passage is shared between two
    sentences, so an offline run scores realistically on repetition.
    """
    pairs = [(action, reason) for action in _ACTIONS for reason in _REASONS]
    rng = random.Random(f"pool:{seed}")
    rng.shuffle(pairs)
    return [
        f"{_LEADS[index % len(_LEADS)]}, {action}, {reason}."
        for index, (action, reason) in enumerate(pairs)
    ]


_TOPIC_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "how",
        "in",
        "into",
        "is",
        "it",
        "of",
        "on",
        "or",
        "the",
        "to",
        "vs",
        "with",
        "why",
        "what",
        "when",
        "your",
        "you",
        "we",
        "our",
        "this",
        "that",
        "these",
        "those",
        "guide",
        "practical",
    ]
)

_MAX_SECTION_WORDS = 1200


def _slug(value: str, *, fallback: str = "section") -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    if not slug:
        return fallback
    if slug[0].isdigit():
        slug = f"step_{slug}"
    return slug[:40]


def _keywords(text: str, limit: int = 6) -> list[str]:
    words = [word.strip(".,:;()[]\"'").lower() for word in text.split()]
    seen: set[str] = set()
    result: list[str] = []
    for word in words:
        if len(word) < 4 or word in _TOPIC_STOPWORDS or word in seen:
            continue
        seen.add(word)
        result.append(word)
        if len(result) >= limit:
            break
    return result


def _field(prompt: str, label: str) -> str | None:
    match = re.search(rf"^{re.escape(label)}:\s*(?P<value>.+)$", prompt, flags=re.MULTILINE)
    return match.group("value").strip() if match else None


def _block(prompt: str, label: str) -> list[str]:
    match = re.search(
        rf"^{re.escape(label)}:\s*$\n(?P<body>(?:[ \t]*-.*\n?)*)",
        prompt,
        flags=re.MULTILINE,
    )
    if not match:
        return []
    items: list[str] = []
    for line in match.group("body").splitlines():
        cleaned = line.strip().lstrip("-").strip()
        if cleaned:
            items.append(cleaned)
    return items


def _evidence(prompt: str) -> list[tuple[str, str, str]]:
    found: list[tuple[str, str, str]] = []
    for line in prompt.splitlines():
        match = _EVIDENCE_LINE.match(line.strip())
        if match:
            found.append((match.group("id"), match.group("title"), match.group("url")))
    return found


def _count_words(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]*", text))


class MockProvider:
    """Offline, deterministic provider used for demos, tests and CI."""

    name = "mock"
    kind = "mock"

    def __init__(self, model: str = "mock-writer-1", seed: int = 7) -> None:
        self.model = model
        self.seed = seed
        self._pool = _sentence_pool(seed)

    # ------------------------------------------------------------------
    # Provider protocol
    # ------------------------------------------------------------------
    def complete(self, request: CompletionRequest) -> Completion:
        started = time.perf_counter()
        prompt = request.system_prompt() + "\n" + request.user_prompt()
        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        rng = random.Random(f"{self.seed}:{request.task}:{digest}")

        if request.schema is not None:
            payload = self._structured(request, rng)
            text = _json_dumps(payload)
        else:
            text = self._prose(request, rng)

        latency_ms = int((time.perf_counter() - started) * 1000)
        return Completion(
            text=text,
            provider=self.name,
            model=self.model,
            prompt_tokens=max(1, len(prompt) // 4),
            completion_tokens=max(1, len(text) // 4),
            cost_usd=0.0,
            latency_ms=latency_ms,
        )

    # ------------------------------------------------------------------
    # Structured stages
    # ------------------------------------------------------------------
    def _structured(self, request: CompletionRequest, rng: random.Random) -> Any:
        if request.schema is None:  # pragma: no cover - guarded by the caller
            raise ValueError("structured output requires a schema")
        if request.schema.name == "outline":
            return self._outline(request.user_prompt(), rng)
        if request.schema.name == "claims":
            return self._claims(request.user_prompt())
        return synthesize(request.schema.schema, rng, name=request.schema.name)

    def _outline(self, prompt: str, rng: random.Random) -> dict[str, Any]:
        topic = _field(prompt, "Topic") or "the requested topic"
        audience = _field(prompt, "Audience") or "software engineers"
        target_words = int(_field(prompt, "Target words") or "1400")
        key_points = _block(prompt, "Key points") or _block(prompt, "Must include")
        evidence_available = (_field(prompt, "Evidence available") or "false").lower() == "true"

        short = topic.strip().rstrip(".") or "the topic"
        if len(short) > 48:
            short = short[:45].rsplit(" ", 1)[0] + "..."

        candidates = [
            f"Why {short} matters",
            f"How {short} works under the hood",
            f"Building a minimal {short} prototype",
            f"Measuring {short} in production",
            "Failure modes and edge cases",
            "Performance and cost trade-offs",
            "A production readiness checklist",
            "Where to go next",
        ]
        section_count = max(4, min(8, round(target_words / 260)))
        titles = candidates[:section_count]

        base = max(120, target_words // section_count)
        sections: list[dict[str, Any]] = []
        for index, title in enumerate(titles, start=1):
            points = list(key_points[index - 1 : index + 2])
            fallbacks = [
                f"Define the invariant behind {title.lower()}",
                f"Show a concrete workflow for {title.lower()}",
                f"Name the failure mode of {title.lower()}",
            ]
            for fallback in fallbacks:
                if len(points) >= 3:
                    break
                points.append(fallback)
            sections.append(
                {
                    "id": f"s{index}",
                    "title": title,
                    "goal": (
                        f"Give {audience} a working model of {title.lower()} "
                        "that they can apply immediately."
                    ),
                    "key_points": points[:4],
                    "target_words": max(80, min(_MAX_SECTION_WORDS, base)),
                    "requires_evidence": evidence_available,
                    "requires_code": index == 3,
                }
            )

        return {
            "title": f"{short[0].upper()}{short[1:]}: a practical field guide",
            "subtitle": f"What {audience} actually need to ship it",
            "thesis": (
                f"{short} is best treated as an engineering discipline: define the invariant, "
                f"instrument the path, and make the failure mode cheap to detect."
            ),
            "meta_description": (
                f"A practical guide to {short} for {audience}, covering design choices, "
                f"verification, performance limits and a production checklist."
            ),
            "tags": _keywords(topic, limit=5) or ["engineering"],
            "sections": sections,
        }

    def _claims(self, prompt: str) -> dict[str, Any]:
        evidence = _evidence(prompt)
        by_url = {url: evidence_id for evidence_id, _title, url in evidence}
        body = prompt
        marker = "Section text:"
        if marker in prompt:
            body = prompt.split(marker, 1)[1]
        if "Evidence catalog:" in body:
            body = body.split("Evidence catalog:", 1)[0]

        claims: list[dict[str, Any]] = []
        seen: set[str] = set()
        for sentence in _SENTENCE_SPLIT.split(" ".join(body.split())):
            links = list(_LINK.finditer(sentence))
            if not links:
                continue
            plain = _LINK.sub(lambda match: match.group("label"), sentence).strip(" -")
            ids = [by_url[link.group("url")] for link in links if link.group("url") in by_url]
            key = plain.lower()
            if not ids or key in seen or len(plain) < 24:
                continue
            seen.add(key)
            claims.append({"text": plain[:400], "evidence_ids": ids})
            if len(claims) >= 4:
                break

        if not claims:
            for sentence in _SENTENCE_SPLIT.split(" ".join(body.split())):
                plain = sentence.strip(" -#")
                if len(plain) < 40:
                    continue
                claims.append({"text": plain[:400], "evidence_ids": []})
                if len(claims) >= 2:
                    break

        return {"claims": claims}

    # ------------------------------------------------------------------
    # Prose stages
    # ------------------------------------------------------------------
    def _prose(self, request: CompletionRequest, rng: random.Random) -> str:
        if request.task in {"draft_section", "revise_section"}:
            return self._section(request, rng)
        if request.schema is None and request.task == "generic":
            return (
                "This is a deterministic offline response produced by the mock provider. "
                "Configure a real provider to generate model-written content."
            )
        return (
            f"Offline mock output for task '{request.task}'. "
            "It is deterministic and safe to use in tests."
        )

    def _section(self, request: CompletionRequest, rng: random.Random) -> str:
        prompt = request.user_prompt()
        title = _field(prompt, "Section title") or "Overview"
        goal = _field(prompt, "Goal") or "Explain the topic clearly."
        audience = _field(prompt, "Audience") or "software engineers"
        target_words = int(_field(prompt, "Target words") or "240")
        target_words = max(80, min(_MAX_SECTION_WORDS, target_words))
        key_points = _block(prompt, "Key points")
        directives = _block(prompt, "Directives")
        requires_code = (_field(prompt, "Requires code") or "false").lower() == "true"
        evidence = _evidence(prompt)
        revising = request.task == "revise_section"

        index_match = _SEQUENCE.search(prompt)
        section_index = int(index_match.group(1)) if index_match else 1
        window = 32
        offset = ((section_index - 1) * window) % len(self._pool)
        sentences = self._pool[offset : offset + window]
        if len(sentences) < 8:  # pragma: no cover - defensive wrap
            sentences = self._pool[:window]
        cursor = 0

        parts: list[str] = [f"## {title}", ""]
        opener = rng.choice(_OPENERS).format(title=title)
        parts.append(f"{opener} {goal}")
        parts.append("")

        if key_points:
            parts.append("### What this section covers")
            parts.append("")
            for point in key_points:
                parts.append(f"- **{point.rstrip('.')}**. {sentences[cursor % len(sentences)]}")
                cursor += 1
            parts.append("")

        if evidence:
            item = evidence[(section_index - 1) % len(evidence)]
            links = f"[{item[1]}]({item[2]})"
            frame = _EVIDENCE_FRAMES[(section_index - 1) % len(_EVIDENCE_FRAMES)]
            tail = _AUDIENCE_TAILS[(section_index - 1) % len(_AUDIENCE_TAILS)]
            parts.append(
                frame.format(links=links, title=title.lower())
                + " "
                + tail.format(audience=audience, title=title.lower())
            )
            parts.append("")

        if directives:
            parts.append(
                "This revision addresses the editorial notes: "
                + "; ".join(directive.rstrip(".") for directive in directives[:3])
                + "."
            )
            parts.append("")

        if requires_code:
            parts.append(self._code_sample(title))
            parts.append("")

        words = _count_words("\n".join(parts))
        while words < int(target_words * 0.95) and cursor < len(sentences):
            sentence = sentences[cursor]
            cursor += 1
            parts.append(sentence)
            if cursor % 2 == 0:
                parts.append("")
            words += _count_words(sentence)
        while words < int(target_words * 0.85):  # pragma: no cover - long targets
            parts.append(rng.choice(sentences))
            words += 12

        parts.append("")
        parts.append(rng.choice(_CLOSERS).format(title=title))
        if revising:
            parts.append("")
            parts.append(
                "The revised text keeps the original structure while tightening claims "
                "and citations."
            )
        return "\n".join(parts).strip()

    def _code_sample(self, title: str) -> str:
        slug = _slug(title)
        camel = "".join(part.capitalize() for part in slug.split("_")) or "Section"
        return (
            "```python\n"
            "from dataclasses import dataclass\n"
            "\n"
            "\n"
            "@dataclass(frozen=True)\n"
            f"class {camel}Config:\n"
            '    """Configuration for one reproducible experiment."""\n'
            "\n"
            "    retries: int = 3\n"
            "    timeout_s: float = 2.5\n"
            "\n"
            "\n"
            f"def run_{slug}(payload: dict[str, object]) -> dict[str, object]:\n"
            '    """Run one step and return a small result envelope."""\n'
            "    if not payload:\n"
            '        raise ValueError("payload must not be empty")\n'
            f'    return {{"step": "{slug}", "status": "ok", "items": len(payload)}}\n'
            "```"
        )


def _json_dumps(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, indent=2)
