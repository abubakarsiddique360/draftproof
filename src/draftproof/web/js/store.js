/** Pure state helpers for the studio UI (no DOM access, unit tested). */

export const initialState = {
  runs: [],
  currentId: null,
  run: null,
  meta: null,
  rubric: null,
  events: [],
  tab: "overview",
  apiKey: "",
  error: null,
  streaming: false,
};

export function reducer(state, action) {
  switch (action.type) {
    case "meta/loaded":
      return { ...state, meta: action.meta };
    case "rubric/loaded":
      return { ...state, rubric: action.rubric };
    case "runs/loaded":
      return { ...state, runs: action.runs ?? [] };
    case "run/loaded":
      return action.run
        ? { ...state, run: action.run, currentId: action.run.id }
        : { ...state, run: null };
    case "run/selected":
      return {
        ...state,
        currentId: action.id,
        run: state.run && state.run.id === action.id ? state.run : null,
        events: [],
      };
    case "events/appended":
      return { ...state, events: [...state.events, ...(action.events ?? [])].slice(-600) };
    case "events/cleared":
      return { ...state, events: [] };
    case "tab/changed":
      return { ...state, tab: action.tab };
    case "apiKey/changed":
      return { ...state, apiKey: action.apiKey };
    case "error/set":
      return { ...state, error: action.error };
    case "streaming/set":
      return { ...state, streaming: Boolean(action.streaming) };
    default:
      return state;
  }
}

export function selectActiveRun(state) {
  if (!state.run) return null;
  if (state.currentId && state.run.id !== state.currentId) return null;
  return state.run;
}

export function patchRun(run, event) {
  if (!run || !event) return run;
  const data = event.data && typeof event.data === "object" ? event.data : {};
  switch (event.type) {
    case "run_status":
      return data.status ? { ...run, status: data.status } : run;
    case "quality_scored":
      return {
        ...run,
        quality: {
          score: Number(data.score) || 0,
          grade: data.grade ?? run.quality?.grade ?? "?",
          passed: Boolean(data.passed),
          failed_gates: data.failed_gates ?? [],
          metrics: data.metrics ?? [],
          issues: data.issues ?? [],
          summary: run.quality?.summary ?? "",
        },
      };
    case "run_finished":
      return data.status ? { ...run, status: data.status } : run;
    default:
      return run;
  }
}

export const STAGE_ORDER = [
  "brief",
  "plan",
  "research",
  "draft",
  "claims",
  "verify",
  "critique",
  "revise",
  "publish",
];

export function foldStages(events) {
  const stages = new Map();
  for (const event of events ?? []) {
    const data = event.data && typeof event.data === "object" ? event.data : {};
    if (event.type === "stage_started" && data.stage) {
      stages.set(data.stage, { stage: data.stage, status: "running", duration: null });
    } else if (event.type === "stage_finished" && data.stage) {
      stages.set(data.stage, {
        stage: data.stage,
        status: "completed",
        duration: Number(data.duration_ms) || 0,
      });
    } else if (event.type === "log" && data.level === "error" && data.stage) {
      stages.set(data.stage, { stage: data.stage, status: "failed", duration: null });
    }
  }
  const known = STAGE_ORDER.filter((stage) => stages.has(stage));
  const extra = [...stages.keys()].filter((stage) => !STAGE_ORDER.includes(stage));
  return [...known, ...extra].map((stage) => stages.get(stage));
}

const REFETCH_EVENTS = new Set([
  "outline_ready",
  "evidence_ready",
  "section_ready",
  "quality_scored",
  "artifact_written",
  "revision_finished",
  "run_status",
  "run_finished",
]);

export function shouldRefetch(eventType) {
  return REFETCH_EVENTS.has(eventType);
}

export function claimStats(run) {
  const claims = (run?.sections ?? []).flatMap((section) => section.claims ?? []);
  const verified = claims.filter((claim) => claim.verified).length;
  return {
    total: claims.length,
    verified,
    coverage: claims.length ? Math.round((verified / claims.length) * 100) : 0,
  };
}

export function evidenceStats(run) {
  const counts = { verified: 0, unreachable: 0, blocked: 0, unchecked: 0 };
  for (const item of run?.evidence ?? []) {
    if (Object.hasOwn(counts, item.status)) counts[item.status] += 1;
  }
  return { ...counts, total: (run?.evidence ?? []).length };
}

export const ARTIFACT_KINDS = [
  { kind: "markdown", label: "Markdown", hint: "Publish-ready article with front matter" },
  { kind: "html", label: "HTML", hint: "Self-contained page with inline styles" },
  { kind: "jsonld", label: "JSON-LD", hint: "schema.org Article metadata" },
  { kind: "social", label: "Social pack", hint: "Thread and LinkedIn copy" },
  { kind: "manifest", label: "Manifest", hint: "Full provenance record" },
  { kind: "quality", label: "Quality", hint: "Rubric scores and issues" },
  { kind: "outline", label: "Outline", hint: "The approved plan" },
];

export function sectionBadge(section) {
  const claims = section.claims ?? [];
  if (!claims.length) return { text: "no claims", tone: "" };
  const verified = claims.filter((claim) => claim.verified).length;
  if (verified === claims.length) return { text: `${verified} cited`, tone: "pass" };
  if (verified === 0) return { text: "uncited", tone: "fail" };
  return { text: `${verified}/${claims.length} cited`, tone: "warn" };
}
