import { ApiClient } from "./api.js";
import {
  claimStats,
  evidenceStats,
  foldStages,
  initialState,
  ARTIFACT_KINDS,
  patchRun,
  reducer,
  sectionBadge,
  selectActiveRun,
  shouldRefetch,
} from "./store.js";
import { renderMarkdown } from "./markdown.js";
import { streamEvents } from "./sse.js";
import { badge, clear, dialogPrompt, el, replace, stat } from "./ui.js";
import {
  formatBytes,
  formatCost,
  formatDuration,
  formatNumber,
  formatTime,
  isTerminal,
  relativeTime,
  scoreTone,
  statusLabel,
  summarizeEvent,
  titleCase,
  truncate,
} from "./format.js";

const api = new ApiClient();
let state = { ...initialState };
let streamController = null;
let streamRunId = null;
let refreshTimer = null;
const manifestCache = new Map();
const manifestPending = new Set();

const PANELS = ["overview", "live", "draft", "quality", "sources", "artifacts", "manifest"];

const $ = (id) => document.getElementById(id);

function dispatch(action) {
  state = reducer(state, action);
  render();
}

function notify(message, kind = "info") {
  const toast = $("toast");
  if (!toast) return;
  toast.textContent = message;
  toast.className = `toast${kind === "error" ? " error" : ""}`;
  toast.hidden = false;
  clearTimeout(notify.timer);
  notify.timer = setTimeout(() => {
    toast.hidden = true;
  }, 5200);
}

function describeError(error) {
  const hint = error && error.hint ? ` (${error.hint})` : "";
  return `${error && error.message ? error.message : "Unexpected error"}${hint}`;
}

/* ------------------------------------------------------------------ */
/* Data loading                                                        */
/* ------------------------------------------------------------------ */
async function refreshRuns() {
  try {
    const page = await api.listRuns(30);
    dispatch({ type: "runs/loaded", runs: page.items ?? [] });
  } catch (error) {
    if (error.status === 401) {
      notify("Enter your API key in the sidebar to load runs.", "error");
      return;
    }
    notify(describeError(error), "error");
  }
}

async function loadRun(runId) {
  try {
    const run = await api.getRun(runId);
    dispatch({ type: "run/loaded", run });
    return run;
  } catch (error) {
    notify(describeError(error), "error");
    return null;
  }
}

async function selectRun(runId) {
  if (!runId) return;
  stopStream();
  dispatch({ type: "run/selected", id: runId });
  const run = await loadRun(runId);
  if (!run) return;
  history.replaceState(null, "", `#run=${runId}`);
  if (!isTerminal(run.status)) {
    dispatch({ type: "tab/changed", tab: "live" });
  }
  startStream(runId);
}

function stopStream() {
  if (streamController) streamController.abort();
  streamController = null;
  streamRunId = null;
  dispatch({ type: "streaming/set", streaming: false });
}

function scheduleRefresh(runId) {
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(() => {
    if (state.currentId === runId) loadRun(runId);
    refreshRuns();
  }, 350);
}

async function startStream(runId) {
  stopStream();
  streamRunId = runId;
  streamController = new AbortController();
  dispatch({ type: "streaming/set", streaming: true });
  await streamEvents(api.streamUrl(runId, 0), {
    headers: api.authHeaders,
    signal: streamController.signal,
    onEvent: (event) => {
      if (streamRunId !== runId) return;
      dispatch({ type: "events/appended", events: [event] });
      if (event.type === "run_status" || event.type === "quality_scored" || event.type === "run_finished") {
        dispatch({ type: "run/loaded", run: patchRun(state.run, event) });
      }
      if (shouldRefetch(event.type)) scheduleRefresh(runId);
    },
    onError: (error) => {
      if (streamRunId === runId) notify(describeError(error), "error");
    },
  });
  if (streamRunId === runId) {
    dispatch({ type: "streaming/set", streaming: false });
  }
}

/* ------------------------------------------------------------------ */
/* Rendering                                                           */
/* ------------------------------------------------------------------ */
function render() {
  renderRunList();
  renderHeader();
  renderTabs();
  for (const panel of PANELS) {
    const node = $(`panel-${panel}`);
    if (node) node.hidden = state.tab !== panel;
  }
  const run = selectActiveRun(state);
  if (state.tab === "overview") renderOverview(run);
  else if (state.tab === "live") renderLive();
  else if (state.tab === "draft") renderDraft(run);
  else if (state.tab === "quality") renderQuality(run);
  else if (state.tab === "sources") renderSources(run);
  else if (state.tab === "artifacts") renderArtifacts(run);
  else if (state.tab === "manifest") renderManifest(run);
}

function renderRunList() {
  const list = $("run-list");
  if (!list) return;
  clear(list);
  if (!state.runs.length) {
    list.appendChild(el("li", { class: "run-empty" }, "No runs yet. Start your first draft."));
    return;
  }
  for (const run of state.runs) {
    const item = el(
      "li",
      {},
      el(
        "button",
        {
          class: "run-item",
          type: "button",
          "aria-current": String(run.id === state.currentId),
          onclick: () => selectRun(run.id),
        },
        el("span", { class: "topic" }, run.topic),
        el(
          "span",
          { class: "meta" },
          el("span", { class: `dot dot-${run.status}` }),
          el("span", {}, statusLabel(run.status)),
          run.score != null ? el("span", {}, `${Number(run.score).toFixed(0)}/100`) : null,
          el("span", { class: "dim" }, relativeTime(run.created_at)),
        ),
      ),
    );
    list.appendChild(item);
  }
}

function renderHeader() {
  const run = selectActiveRun(state);
  $("run-title").textContent = run?.outline?.title ?? run?.brief?.topic ?? "DraftProof Studio";
  $("run-subtitle").textContent =
    run?.outline?.thesis ??
    "Evidence-first drafting: plan, research, draft, verify claims, score, revise, publish.";

  const actions = $("run-actions");
  clear(actions);
  if (!run) return;

  actions.appendChild(badge(statusLabel(run.status), statusTone(run.status)));
  if (run.quality) {
    actions.appendChild(
      badge(
        `${Number(run.quality.score).toFixed(1)} · ${run.quality.grade}`,
        run.quality.passed ? "pass" : "fail",
      ),
    );
  }
  if (state.streaming) actions.appendChild(badge("live", "info"));

  if (!isTerminal(run.status) && run.status !== "awaiting_review") {
    actions.appendChild(
      el(
        "button",
        { class: "btn btn-danger", type: "button", onclick: () => cancelRun(run.id) },
        "Cancel",
      ),
    );
  }
  if (["failed", "cancelled"].includes(run.status)) {
    actions.appendChild(
      el("button", { class: "btn", type: "button", onclick: () => resumeRun(run.id) }, "Resume"),
    );
  }
  if (run.status === "awaiting_review") {
    actions.appendChild(
      el("button", { class: "btn btn-primary", type: "button", onclick: () => approveRun(run.id) }, "Approve"),
    );
    actions.appendChild(
      el("button", { class: "btn", type: "button", onclick: () => requestChanges(run.id) }, "Request changes"),
    );
  } else if (run.status === "completed") {
    actions.appendChild(
      el("button", { class: "btn", type: "button", onclick: () => requestChanges(run.id) }, "Request changes"),
    );
  }
}

function statusTone(status) {
  if (status === "completed") return "pass";
  if (status === "failed") return "fail";
  if (status === "awaiting_review") return "warn";
  if (["running", "revising", "queued"].includes(status)) return "info";
  return "";
}

function renderTabs() {
  for (const tab of document.querySelectorAll(".tab")) {
    tab.setAttribute("aria-selected", String(tab.dataset.tab === state.tab));
  }
}

function renderOverview(run) {
  const body = $("overview-body");
  const empty = $("overview-empty");
  if (!run) {
    body.hidden = true;
    empty.hidden = false;
    return;
  }
  empty.hidden = true;
  body.hidden = false;

  const claims = claimStats(run);
  const evidence = evidenceStats(run);
  const stageRows = foldStages(state.events);

  const stats = el(
    "div",
    { class: "grid-3" },
    stat(
      "Quality",
      run.quality ? Number(run.quality.score).toFixed(1) : "—",
      run.quality ? `${run.quality.grade} · ${run.quality.passed ? "gates passed" : "gates failed"}` : "pending",
    ),
    stat("Claims verified", `${claims.verified}/${claims.total}`, `${claims.coverage}% coverage`),
    stat("Sources", String(evidence.total), `${evidence.verified} verified`),
    stat(
      "Usage",
      formatNumber(run.usage.total_tokens),
      `${run.usage.calls} calls · ${formatCost(run.usage.cost_usd)}`,
    ),
  );

  const facts = el(
    "div",
    { class: "card" },
    el("div", { class: "card-head" }, el("h3", {}, "Run facts")),
    el(
      "dl",
      { class: "meta-info" },
      fact("Run", run.id),
      fact("Provider", run.provider),
      fact("Model", run.model),
      fact("Created", relativeTime(run.created_at)),
      fact("Sections", String(run.sections.length)),
      fact("Verification", run.quality ? titleCase(state.meta?.verification ?? "") : "pending"),
    ),
    run.error ? el("p", { class: "issue issue-high" }, run.error) : null,
  );

  const outline = el(
    "div",
    { class: "card" },
    el(
      "div",
      { class: "card-head" },
      el("h3", {}, "Outline"),
      run.outline ? badge(`${run.outline.sections.length} sections`, "info") : null,
    ),
    run.outline
      ? el(
          "div",
          { class: "stack" },
          el("p", { class: "muted" }, run.outline.thesis),
          el(
            "ol",
            { class: "claim-list" },
            run.outline.sections.map((section) =>
              el(
                "li",
                {},
                el("p", {}, `${section.title}`),
                el(
                  "p",
                  { class: "note" },
                  `${section.target_words} words${section.requires_code ? " · code" : ""}${
                    section.requires_evidence ? " · needs sources" : ""
                  }`,
                ),
              ),
            ),
          ),
        )
      : el("p", { class: "muted" }, "Waiting for the planner."),
  );

  const timeline = el(
    "div",
    { class: "card" },
    el("div", { class: "card-head" }, el("h3", {}, "Pipeline")),
    stageRows.length
      ? el(
          "ol",
          { class: "claim-list" },
          stageRows.map((row) =>
            el(
              "li",
              {},
              el("p", {}, `${titleCase(row.stage)} — ${row.status}${row.duration ? ` · ${formatDuration(row.duration)}` : ""}`),
            ),
          ),
        )
      : el("p", { class: "muted" }, "No stage events captured yet."),
  );

  replace(
    body,
    stats,
    el("div", { class: "grid-2" }, outline, facts),
    timeline,
  );
}

function fact(label, value) {
  return el("div", {}, el("dt", {}, label), el("dd", {}, value));
}

function renderLive() {
  const log = $("event-log");
  if (!log) return;
  clear(log);
  if (!state.events.length) {
    log.appendChild(el("li", { class: "event" }, el("span", { class: "body" }, "Waiting for events…")));
    return;
  }
  for (const event of state.events) {
    const data = event.data && typeof event.data === "object" ? event.data : {};
    const level = data.level === "error" || event.type === "warning" ? "error" : "info";
    log.appendChild(
      el(
        "li",
        { class: `event level-${level}` },
        el("time", {}, formatTime(data._at ?? new Date().toISOString())),
        el("span", { class: "type" }, event.type),
        el("span", { class: "body" }, summarizeEvent(event)),
      ),
    );
  }
  log.scrollTop = log.scrollHeight;
}

function renderDraft(run) {
  const body = $("draft-body");
  if (!run) {
    replace(body, el("div", { class: "empty-state" }, el("h2", {}, "No draft selected")));
    return;
  }
  if (!run.sections.length) {
    replace(body, el("div", { class: "empty-state" }, el("h2", {}, "Draft pending"), el("p", { class: "muted" }, "Sections appear as soon as the writer stage finishes.")));
    return;
  }
  const cards = run.sections.map((section) => {
    const claims = section.claims ?? [];
    const verified = claims.filter((claim) => claim.verified).length;
    const badgeInfo = sectionBadge(section);
    const markdown = el("div", {
      class: "markdown clamp",
      html: renderMarkdown(section.markdown ?? ""),
    });
    const toggle =
      (section.markdown ?? "").length > 600
        ? el(
            "button",
            {
              class: "btn btn-ghost btn-tiny",
              type: "button",
              onclick: () => {
                const open = markdown.classList.toggle("open");
                toggle.textContent = open ? "Collapse" : "Expand";
              },
            },
            "Expand",
          )
        : null;

    return el(
      "article",
      { class: "card section-card" },
      el(
        "div",
        { class: "card-head" },
        el(
          "div",
          {},
          el("h3", {}, section.plan.title),
          el(
            "p",
            { class: "dim" },
            `${(section.markdown ?? "").split(/\s+/).filter(Boolean).length} words · attempt ${section.attempt} · grounding ${Math.round((section.grounding ?? 0) * 100)}%`,
          ),
        ),
        el(
          "div",
          { class: "actions" },
          badge(badgeInfo.text, badgeInfo.tone),
          el(
            "button",
            {
              class: "btn btn-ghost btn-tiny",
              type: "button",
              onclick: () => requestChanges(run.id, section.plan.id),
            },
            "Regenerate",
          ),
        ),
      ),
      markdown,
      toggle,
      claims.length
        ? el(
            "details",
            {},
            el("summary", {}, `${claims.length} claims · ${verified} verified`),
            el(
              "ul",
              { class: "claim-list" },
              claims.map((claim) =>
                el(
                  "li",
                  { class: "claim" },
                  badge(claim.verified ? "verified" : "open", claim.verified ? "pass" : "fail"),
                  el(
                    "div",
                    {},
                    el("p", {}, claim.text),
                    claim.note ? el("p", { class: "note" }, claim.note) : null,
                  ),
                ),
              ),
            ),
          )
        : el("p", { class: "dim" }, "No claims extracted for this section."),
    );
  });

  replace(body, ...cards);
}

function renderQuality(run) {
  const body = $("quality-body");
  if (!run || !run.quality) {
    replace(
      body,
      el(
        "div",
        { class: "empty-state" },
        el("h2", {}, "No score yet"),
        el("p", { class: "muted" }, "The rubric runs once the first draft and claim verification are complete."),
      ),
    );
    return;
  }
  const quality = run.quality;
  const ring = el(
    "div",
    { class: `score-ring${quality.passed ? "" : " fail"}`, style: { "--value": String(quality.score) } },
    el("span", {}, Number(quality.score).toFixed(1)),
  );

  const hero = el(
    "div",
    { class: "card score-hero" },
    ring,
    el(
      "div",
      { class: "stack" },
      el("h2", {}, quality.passed ? "Publishable" : "Blocked by gates"),
      el(
        "p",
        { class: "muted" },
        quality.passed
          ? "Every rubric gate passed. The draft is ready to publish."
          : `Failing gates: ${(quality.failed_gates ?? []).join(", ") || "unknown"}`,
      ),
      el(
        "div",
        { class: "actions" },
        badge(`Grade ${quality.grade}`, quality.passed ? "pass" : "fail"),
        badge(`${(quality.metrics ?? []).length} metrics`, "info"),
        badge(`${(quality.issues ?? []).length} issues`, (quality.issues ?? []).length ? "warn" : "info"),
      ),
    ),
  );

  const metrics = el(
    "div",
    { class: "card" },
    el("div", { class: "card-head" }, el("h3", {}, "Metrics")),
    el(
      "div",
      { class: "stack" },
      (quality.metrics ?? []).map((metric) => {
        const tone = scoreTone(metric.score);
        return el(
          "div",
          { class: "metric-row" },
          el("span", { class: "name" }, `${metric.label} (${metric.weight.toFixed(2)})`),
          el(
            "div",
            { class: `bar${tone === "pass" ? "" : tone === "warn" ? " warn" : " bad"}` },
            el("span", { style: { width: `${Math.max(2, Number(metric.score) || 0)}%` } }),
          ),
          el("span", { class: "score" }, Number(metric.score).toFixed(0)),
          el("span", { class: "metric-detail" }, metric.detail),
        );
      }),
    ),
  );

  const gates = state.rubric
    ? el(
        "div",
        { class: "card" },
        el("div", { class: "card-head" }, el("h3", {}, "Gates")),
        el(
          "div",
          { class: "stack" },
          state.rubric.gates.map((gate) => {
            const failed = (quality.failed_gates ?? []).includes(gate.key);
            return el(
              "div",
              { class: "row" },
              badge(`${gate.key} ≥ ${gate.minimum}${gate.condition !== "always" ? ` (${gate.condition})` : ""}`, failed ? "fail" : "pass"),
            );
          }),
        ),
      )
    : null;

  const issues = (quality.issues ?? []).length
    ? el(
        "div",
        { class: "card" },
        el("div", { class: "card-head" }, el("h3", {}, "Editorial notes")),
        el(
          "div",
          { class: "stack" },
          quality.issues.map((issue) =>
            el(
              "div",
              { class: `issue issue-${issue.severity}` },
              el("strong", {}, `${issue.severity.toUpperCase()}${issue.section_id ? ` · ${issue.section_id}` : ""}`),
              el("p", {}, issue.message),
              issue.directive ? el("p", { class: "fix" }, `Fix: ${issue.directive}`) : null,
            ),
          ),
        ),
      )
    : null;

  replace(body, hero, metrics, gates, issues);
}

function renderSources(run) {
  const body = $("sources-body");
  if (!run) {
    replace(body, el("div", { class: "empty-state" }, el("h2", {}, "No run selected")));
    return;
  }
  if (!run.evidence.length) {
    replace(
      body,
      el(
        "div",
        { class: "empty-state" },
        el("h2", {}, "No sources"),
        el("p", { class: "muted" }, "This run had no retrieved evidence. Either research was disabled or nothing matched the topic."),
      ),
    );
    return;
  }
  const rows = run.evidence.map((item) =>
    el(
      "tr",
      {},
      el("td", {}, el("a", { href: item.url, target: "_blank", rel: "noopener noreferrer nofollow" }, item.title), el("span", { class: "url" }, item.url)),
      el("td", { class: "mono" }, item.domain),
      el("td", {}, badge(item.status, item.status === "verified" ? "pass" : item.status === "unchecked" ? "" : "warn")),
      el("td", {}, `${Math.round((item.overlap ?? 0) * 100)}%`),
      el("td", { class: "dim" }, item.published_at ?? "—"),
    ),
  );
  replace(
    body,
    el(
      "div",
      { class: "table-wrap" },
      el(
        "table",
        {},
        el("thead", {}, el("tr", {}, ["Source", "Domain", "Status", "Support", "Published"].map((label) => el("th", {}, label)))),
        el("tbody", {}, rows),
      ),
    ),
  );
}

function renderArtifacts(run) {
  const body = $("artifacts-body");
  if (!run) {
    replace(body, el("div", { class: "empty-state" }, el("h2", {}, "No run selected")));
    return;
  }
  const available = new Set((run.artifacts ?? []).map((artifact) => artifact.kind));
  if (!available.size) {
    replace(
      body,
      el(
        "div",
        { class: "empty-state" },
        el("h2", {}, "Nothing published yet"),
        el("p", { class: "muted" }, "Artifacts are written when the run reaches the publish stage."),
      ),
    );
    return;
  }
  const cards = ARTIFACT_KINDS.filter((entry) => available.has(entry.kind)).map((entry) => {
    const artifact = run.artifacts.find((item) => item.kind === entry.kind);
    return el(
      "div",
      { class: "artifact" },
      el("span", { class: "kind" }, entry.label),
      el("span", {}, entry.hint),
      el("span", { class: "size" }, `${formatBytes(artifact?.bytes ?? 0)} · ${truncate(artifact?.sha256 ?? "", 14)}`),
      el(
        "div",
        { class: "actions" },
        ["html", "markdown"].includes(entry.kind)
          ? el(
              "button",
              { class: "btn btn-ghost btn-tiny", type: "button", onclick: () => openArtifact(run.id, entry.kind) },
              "Open",
            )
          : null,
        el(
          "button",
          { class: "btn btn-ghost btn-tiny", type: "button", onclick: () => downloadArtifact(run.id, entry.kind) },
          "Download",
        ),
      ),
    );
  });
  replace(body, el("div", { class: "artifact-grid" }, cards));
}

function renderManifest(run) {
  const node = $("manifest-body");
  if (!run) {
    node.textContent = "Select a completed run to view its manifest.";
    return;
  }
  const cached = manifestCache.get(run.id);
  if (cached) {
    node.textContent = cached;
    return;
  }
  if (!(run.artifacts ?? []).some((artifact) => artifact.kind === "manifest")) {
    node.textContent = "The manifest is written at the end of the publish stage.";
    return;
  }
  node.textContent = "Loading manifest…";
  if (manifestPending.has(run.id)) return;
  manifestPending.add(run.id);
  api
    .artifactText(run.id, "manifest")
    .then((text) => {
      manifestCache.set(run.id, text);
      if (state.currentId === run.id && state.tab === "manifest") node.textContent = text;
    })
    .catch((error) => {
      node.textContent = describeError(error);
    })
    .finally(() => manifestPending.delete(run.id));
}

/* ------------------------------------------------------------------ */
/* Actions                                                             */
/* ------------------------------------------------------------------ */
async function cancelRun(runId) {
  try {
    const result = await api.cancelRun(runId);
    notify(result.cancelled ? "Cancellation requested" : "Run is already finished");
    await loadRun(runId);
  } catch (error) {
    notify(describeError(error), "error");
  }
}

async function resumeRun(runId) {
  try {
    await api.resumeRun(runId);
    notify("Run resumed from the last checkpoint");
    dispatch({ type: "tab/changed", tab: "live" });
    await loadRun(runId);
    startStream(runId);
  } catch (error) {
    notify(describeError(error), "error");
  }
}

async function approveRun(runId) {
  try {
    const run = await api.review(runId, { decision: "approve", notes: "" });
    dispatch({ type: "run/loaded", run });
    notify("Run approved and published");
    await refreshRuns();
  } catch (error) {
    notify(describeError(error), "error");
  }
}

async function requestChanges(runId, sectionId = null) {
  const notes = await dialogPrompt({
    title: sectionId ? "Regenerate section" : "Request changes",
    message: sectionId
      ? "Tell the editor what to fix in this section. The run is re-drafted, re-verified and re-scored."
      : "Describe the editorial changes. Every section is re-drafted with these directives.",
    confirmLabel: "Re-run pipeline",
  });
  if (notes === null) return;
  try {
    if (sectionId) {
      await api.regenerateSection(runId, sectionId, { notes });
    } else {
      await api.review(runId, { decision: "request_changes", notes });
    }
    notify("Revision queued");
    dispatch({ type: "tab/changed", tab: "live" });
    await loadRun(runId);
    startStream(runId);
  } catch (error) {
    notify(describeError(error), "error");
  }
}

async function openArtifact(runId, kind) {
  try {
    await api.openArtifact(runId, kind);
  } catch (error) {
    notify(describeError(error), "error");
  }
}

async function downloadArtifact(runId, kind) {
  try {
    await api.downloadArtifact(runId, kind);
  } catch (error) {
    notify(describeError(error), "error");
  }
}

/* ------------------------------------------------------------------ */
/* Wiring                                                              */
/* ------------------------------------------------------------------ */
function initDialog() {
  const dialog = $("new-run-dialog");
  const form = $("new-run-form");

  document.addEventListener("click", (event) => {
    const action = event.target.closest("[data-action]");
    if (!action) return;
    if (action.dataset.action === "new-run") dialog.showModal();
    if (action.dataset.action === "close-dialog") dialog.close();
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(form);
    const error = $("form-error");
    error.hidden = true;
    const payload = {
      topic: String(data.get("topic") ?? "").trim(),
      audience: String(data.get("audience") ?? "").trim() || "software engineers",
      content_type: String(data.get("content_type") ?? "explainer"),
      tone: String(data.get("tone") ?? "practical"),
      target_words: Number(data.get("target_words") ?? 1400),
      sources_required: data.get("sources_required") === "on",
      key_points: String(data.get("key_points") ?? "")
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean),
    };
    try {
      const created = await api.createRun(payload);
      dialog.close();
      form.reset();
      $("field-sources").checked = true;
      await refreshRuns();
      await selectRun(created.run_id);
      dispatch({ type: "tab/changed", tab: "live" });
    } catch (caught) {
      error.textContent = describeError(caught);
      error.hidden = false;
    }
  });
}

function initTabs() {
  for (const tab of document.querySelectorAll(".tab")) {
    tab.addEventListener("click", () => dispatch({ type: "tab/changed", tab: tab.dataset.tab }));
  }
}

function initSidebar() {
  $("new-run").addEventListener("click", () => $("new-run-dialog").showModal());
  $("refresh-runs").addEventListener("click", () => refreshRuns());

  const keyInput = $("api-key");
  keyInput.value = localStorage.getItem("draftproof.apiKey") ?? "";
  api.setKey(keyInput.value);
  keyInput.addEventListener("change", () => {
    const value = keyInput.value.trim();
    localStorage.setItem("draftproof.apiKey", value);
    api.setKey(value);
    dispatch({ type: "apiKey/changed", apiKey: value });
    refreshRuns();
  });
}

async function init() {
  initSidebar();
  initTabs();
  initDialog();

  try {
    const meta = await api.meta();
    dispatch({ type: "meta/loaded", meta });
    $("meta-provider").textContent = (meta.provider_chain ?? []).join(" → ");
    $("meta-retriever").textContent = titleCase(meta.retriever ?? "");
    $("meta-verification").textContent = titleCase(meta.verification ?? "");
    if (meta.api_key_required) {
      $("api-key").placeholder = "required";
      notify("This server requires an API key. Add it in the sidebar.", "error");
    }
  } catch (error) {
    notify(describeError(error), "error");
  }

  try {
    const rubric = await api.rubric();
    dispatch({ type: "rubric/loaded", rubric });
  } catch {
    /* the rubric view degrades gracefully */
  }

  await refreshRuns();
  const fromHash = location.hash.startsWith("#run=") ? location.hash.slice(5) : "";
  if (fromHash) {
    await selectRun(fromHash);
  } else if (state.runs.length) {
    await selectRun(state.runs[0].id);
  }

  setInterval(() => {
    if (!document.hidden) refreshRuns();
  }, 20_000);
}

init();
