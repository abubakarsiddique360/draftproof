/**
 * Server-Sent Events client built on fetch so that auth headers can be sent
 * (the native EventSource API cannot set headers).
 */

export function createSseParser() {
  let buffer = "";
  return {
    get pending() {
      return buffer;
    },
    push(chunk) {
      buffer += chunk;
      const events = [];
      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const parsed = parseFrame(frame);
        if (parsed) events.push(parsed);
        boundary = buffer.indexOf("\n\n");
      }
      return events;
    },
  };
}

export function parseFrame(frame) {
  const lines = String(frame ?? "").split("\n");
  let id = null;
  let type = "message";
  const data = [];
  for (const line of lines) {
    if (!line || line.startsWith(":")) continue;
    const separator = line.indexOf(":");
    const field = separator === -1 ? line : line.slice(0, separator);
    let value = separator === -1 ? "" : line.slice(separator + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "id") {
      const parsedId = Number(value);
      if (Number.isFinite(parsedId)) id = parsedId;
    } else if (field === "event") {
      type = value || type;
    } else if (field === "data") {
      data.push(value);
    }
  }
  if (!data.length) return null;
  const raw = data.join("\n");
  let payload = raw;
  try {
    payload = JSON.parse(raw);
  } catch {
    payload = raw;
  }
  return { id, type, data: payload };
}

export async function streamEvents(url, { headers = {}, signal, onEvent, onError } = {}) {
  let response;
  try {
    response = await fetch(url, {
      headers: { Accept: "text/event-stream", ...headers },
      signal,
      cache: "no-store",
    });
  } catch (error) {
    if (error.name === "AbortError") return;
    if (onError) onError(error);
    return;
  }
  if (!response.ok || !response.body) {
    if (onError) onError(new Error(`Stream failed with status ${response.status}`));
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const parser = createSseParser();

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      for (const event of parser.push(decoder.decode(value, { stream: true }))) {
        onEvent(event);
      }
    }
  } catch (error) {
    if (error.name !== "AbortError" && onError) onError(error);
  } finally {
    reader.releaseLock();
  }
}
