import test from "node:test";
import assert from "node:assert/strict";

import {
  claimStats,
  evidenceStats,
  foldStages,
  initialState,
  patchRun,
  reducer,
  sectionBadge,
  selectActiveRun,
  shouldRefetch,
} from "../js/store.js";

const run = {
  id: "run_1",
  status: "running",
  sections: [
    {
      plan: { id: "s1" },
      claims: [
        { id: "s1c1", verified: true },
        { id: "s1c2", verified: false },
      ],
    },
    { plan: { id: "s2" }, claims: [] },
  ],
  evidence: [{ id: "ev1", status: "verified" }, { id: "ev2", status: "unreachable" }],
  quality: null,
};

test("reducer loads runs and selects a run", () => {
  let state = reducer(initialState, { type: "runs/loaded", runs: [{ id: "run_1" }] });
  assert.equal(state.runs.length, 1);

  state = reducer(state, { type: "run/selected", id: "run_1" });
  assert.equal(state.currentId, "run_1");
  assert.equal(state.run, null);

  state = reducer(state, { type: "run/loaded", run });
  assert.equal(selectActiveRun(state).id, "run_1");
});

test("run/selected clears a stale run", () => {
  let state = reducer(initialState, { type: "run/loaded", run });
  state = reducer(state, { type: "run/selected", id: "run_2" });
  assert.equal(state.run, null);
  assert.equal(state.currentId, "run_2");
});

test("events are capped so memory stays bounded", () => {
  const events = Array.from({ length: 700 }, (_, index) => ({ type: "log", data: { index } }));
  const state = reducer(initialState, { type: "events/appended", events });
  assert.equal(state.events.length, 600);
  assert.equal(state.events.at(-1).data.index, 699);
});

test("tab and streaming actions", () => {
  let state = reducer(initialState, { type: "tab/changed", tab: "quality" });
  assert.equal(state.tab, "quality");
  state = reducer(state, { type: "streaming/set", streaming: true });
  assert.equal(state.streaming, true);
});

test("patchRun applies status and quality events", () => {
  const active = patchRun(run, { type: "run_status", data: { status: "revising" } });
  assert.equal(active.status, "revising");

  const scored = patchRun(run, {
    type: "quality_scored",
    data: { score: 82.5, grade: "B", passed: true, failed_gates: [], metrics: [], issues: [] },
  });
  assert.equal(scored.quality.score, 82.5);
  assert.equal(scored.quality.passed, true);

  const finished = patchRun(run, { type: "run_finished", data: { status: "completed" } });
  assert.equal(finished.status, "completed");

  assert.equal(patchRun(null, { type: "run_status", data: {} }), null);
  assert.equal(patchRun(run, { type: "unknown", data: {} }), run);
});

test("foldStages orders known stages and tracks durations", () => {
  const stages = foldStages([
    { type: "stage_started", data: { stage: "plan" } },
    { type: "stage_finished", data: { stage: "plan", duration_ms: 42 } },
    { type: "stage_started", data: { stage: "brief" } },
    { type: "stage_finished", data: { stage: "brief", duration_ms: 1 } },
    { type: "stage_started", data: { stage: "custom" } },
  ]);
  assert.deepEqual(
    stages.map((stage) => stage.stage),
    ["brief", "plan", "custom"],
  );
  assert.equal(stages[1].status, "completed");
  assert.equal(stages[1].duration, 42);
  assert.equal(stages[2].status, "running");
});

test("foldStages marks failed stages", () => {
  const stages = foldStages([
    { type: "stage_started", data: { stage: "draft" } },
    { type: "log", data: { stage: "draft", level: "error", message: "boom" } },
  ]);
  assert.equal(stages[0].status, "failed");
});

test("shouldRefetch only fires for state-changing events", () => {
  assert.equal(shouldRefetch("quality_scored"), true);
  assert.equal(shouldRefetch("artifact_written"), true);
  assert.equal(shouldRefetch("log"), false);
  assert.equal(shouldRefetch("usage"), false);
});

test("claimStats and evidenceStats summarise a run", () => {
  assert.deepEqual(claimStats(run), { total: 2, verified: 1, coverage: 50 });
  assert.deepEqual(evidenceStats(run), {
    verified: 1,
    unreachable: 1,
    blocked: 0,
    unchecked: 0,
    total: 2,
  });
  assert.deepEqual(claimStats(null), { total: 0, verified: 0, coverage: 0 });
});

test("sectionBadge reflects verification state", () => {
  assert.deepEqual(sectionBadge({ claims: [] }), { text: "no claims", tone: "" });
  assert.deepEqual(
    sectionBadge({ claims: [{ verified: true }, { verified: true }] }),
    { text: "2 cited", tone: "pass" },
  );
  assert.deepEqual(sectionBadge({ claims: [{ verified: false }] }), { text: "uncited", tone: "fail" });
  assert.deepEqual(
    sectionBadge({ claims: [{ verified: true }, { verified: false }] }),
    { text: "1/2 cited", tone: "warn" },
  );
});
