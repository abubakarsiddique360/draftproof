import test from "node:test";
import assert from "node:assert/strict";

import {
  eventLevel,
  formatBytes,
  formatCost,
  formatDuration,
  formatNumber,
  gradeFor,
  isTerminal,
  relativeTime,
  scoreTone,
  statusLabel,
  summarizeEvent,
  titleCase,
  truncate,
} from "../js/format.js";

test("formatBytes scales units", () => {
  assert.equal(formatBytes(0), "0 B");
  assert.equal(formatBytes(512), "512 B");
  assert.equal(formatBytes(2048), "2.0 kB");
  assert.equal(formatBytes(5 * 1024 * 1024), "5.00 MB");
});

test("formatDuration switches units", () => {
  assert.equal(formatDuration(250), "250 ms");
  assert.equal(formatDuration(1500), "1.5 s");
  assert.equal(formatDuration(65_000), "1m 5s");
});

test("formatCost keeps small amounts visible", () => {
  assert.equal(formatCost(0), "$0.00");
  assert.equal(formatCost(0.0042), "$0.0042");
  assert.equal(formatCost(1.5), "$1.50");
});

test("formatNumber adds separators", () => {
  assert.equal(formatNumber(1234567), new Intl.NumberFormat().format(1234567));
  assert.equal(formatNumber("nope"), "0");
});

test("statusLabel humanizes unknown states", () => {
  assert.equal(statusLabel("awaiting_review"), "Awaiting review");
  assert.equal(statusLabel("weird_state"), "weird state");
  assert.equal(statusLabel(undefined), "unknown");
});

test("relativeTime handles ranges", () => {
  const now = Date.parse("2026-01-01T12:00:00Z");
  assert.equal(relativeTime("2026-01-01T11:59:30Z", now), "just now");
  assert.equal(relativeTime("2026-01-01T11:30:00Z", now), "30 min ago");
  assert.equal(relativeTime("2026-01-01T09:00:00Z", now), "3 h ago");
  assert.equal(relativeTime("2025-12-30T12:00:00Z", now), "2 days ago");
  assert.equal(relativeTime("not a date", now), "—");
});

test("scoreTone and gradeFor agree", () => {
  assert.equal(scoreTone(95), "pass");
  assert.equal(scoreTone(70), "warn");
  assert.equal(scoreTone(10), "fail");
  assert.equal(scoreTone(undefined), "idle");
  assert.equal(gradeFor(95), "A");
  assert.equal(gradeFor(84), "B");
  assert.equal(gradeFor(20), "F");
});

test("truncate respects the limit", () => {
  assert.equal(truncate("hello", 10), "hello");
  assert.equal(truncate("hello world", 8), "hello w…");
});

test("titleCase expands separators", () => {
  assert.equal(titleCase("awaiting_review"), "Awaiting Review");
  assert.equal(titleCase("local-corpus"), "Local Corpus");
});

test("isTerminal knows final states", () => {
  assert.equal(isTerminal("completed"), true);
  assert.equal(isTerminal("failed"), true);
  assert.equal(isTerminal("running"), false);
  assert.equal(isTerminal("awaiting_review"), false);
});

test("summarizeEvent covers key event types", () => {
  assert.match(summarizeEvent({ type: "outline_ready", data: { title: "T", sections: [1, 2] } }), /2 sections/);
  assert.match(
    summarizeEvent({ type: "verification_ready", data: { verified_claims: 3, total_claims: 4, coverage: 0.75 } }),
    /3\/4 claims verified \(75%\)/,
  );
  assert.match(summarizeEvent({ type: "quality_scored", data: { score: 81.5, grade: "B", passed: true } }), /81\.5/);
  assert.match(summarizeEvent({ type: "run_finished", data: { status: "failed", error: "boom" } }), /Failed: boom/);
  assert.equal(summarizeEvent({ type: "unknown_event", data: {} }), "unknown_event");
});

test("eventLevel flags problems", () => {
  assert.equal(eventLevel({ type: "warning", data: {} }), "warn");
  assert.equal(eventLevel({ type: "log", data: { level: "error" } }), "error");
  assert.equal(eventLevel({ type: "run_finished", data: { status: "failed" } }), "error");
  assert.equal(eventLevel({ type: "stage_started", data: {} }), "info");
});
