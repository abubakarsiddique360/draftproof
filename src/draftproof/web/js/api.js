export class ApiError extends Error {
  constructor(message, { code = "request_failed", status = 0, hint = null } = {}) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.hint = hint;
  }
}

export class ApiClient {
  constructor({ baseUrl = "/api/v1", apiKey = "" } = {}) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.apiKey = apiKey;
  }

  setKey(apiKey) {
    this.apiKey = apiKey ?? "";
  }

  get authHeaders() {
    return this.apiKey ? { "X-API-Key": this.apiKey } : {};
  }

  async request(path, { method = "GET", body, signal } = {}) {
    const headers = { Accept: "application/json", ...this.authHeaders };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    let response;
    try {
      response = await fetch(`${this.baseUrl}${path}`, {
        method,
        headers,
        signal,
        cache: "no-store",
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch (error) {
      if (error.name === "AbortError") throw error;
      throw new ApiError("Could not reach the DraftProof API", { code: "network_error" });
    }
    if (response.status === 204) return null;
    const text = await response.text();
    let payload = null;
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch {
        payload = null;
      }
    }
    if (!response.ok) {
      const detail = payload && payload.error ? payload.error : {};
      throw new ApiError(detail.message || `Request failed (${response.status})`, {
        code: detail.code || "request_failed",
        hint: detail.hint || null,
        status: response.status,
      });
    }
    return payload;
  }

  meta() {
    return this.request("/meta");
  }

  health() {
    return this.request("/health");
  }

  rubric() {
    return this.request("/rubric");
  }

  listRuns(limit = 30) {
    return this.request(`/runs?limit=${encodeURIComponent(limit)}`);
  }

  getRun(runId) {
    return this.request(`/runs/${encodeURIComponent(runId)}`);
  }

  createRun(payload) {
    return this.request("/runs", { method: "POST", body: payload });
  }

  cancelRun(runId) {
    return this.request(`/runs/${encodeURIComponent(runId)}`, { method: "DELETE" });
  }

  resumeRun(runId) {
    return this.request(`/runs/${encodeURIComponent(runId)}/resume`, { method: "POST" });
  }

  review(runId, payload) {
    return this.request(`/runs/${encodeURIComponent(runId)}/review`, { method: "POST", body: payload });
  }

  regenerateSection(runId, sectionId, payload) {
    return this.request(
      `/runs/${encodeURIComponent(runId)}/sections/${encodeURIComponent(sectionId)}/regenerate`,
      { method: "POST", body: payload },
    );
  }

  streamUrl(runId, after = 0) {
    return `${this.baseUrl}/runs/${encodeURIComponent(runId)}/events?after=${encodeURIComponent(after)}`;
  }

  artifactUrl(runId, kind) {
    return `${this.baseUrl}/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(kind)}`;
  }

  async artifactText(runId, kind) {
    const response = await fetch(this.artifactUrl(runId, kind), {
      headers: { Accept: "*/*", ...this.authHeaders },
      cache: "no-store",
    });
    if (!response.ok) {
      throw new ApiError(`Artifact ${kind} is not available`, { status: response.status });
    }
    return response.text();
  }

  async downloadArtifact(runId, kind) {
    const response = await fetch(this.artifactUrl(runId, kind), {
      headers: { Accept: "*/*", ...this.authHeaders },
      cache: "no-store",
    });
    if (!response.ok) {
      throw new ApiError(`Artifact ${kind} is not available`, { status: response.status });
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filenameFor(runId, kind);
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }

  async openArtifact(runId, kind) {
    const response = await fetch(this.artifactUrl(runId, kind), {
      headers: { Accept: "*/*", ...this.authHeaders },
      cache: "no-store",
    });
    if (!response.ok) {
      throw new ApiError(`Artifact ${kind} is not available`, { status: response.status });
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    window.open(url, "_blank", "noopener");
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  }
}

const EXTENSIONS = {
  markdown: "md",
  html: "html",
  jsonld: "jsonld.json",
  social: "social.json",
  manifest: "manifest.json",
  quality: "quality.json",
  outline: "outline.json",
};

export function filenameFor(runId, kind) {
  const extension = EXTENSIONS[kind] ?? "txt";
  return `draftproof-${runId}-${kind}.${extension}`;
}
