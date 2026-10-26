import test from "node:test";
import assert from "node:assert/strict";

import { createSseParser, parseFrame } from "../js/sse.js";

test("parseFrame reads id, event and JSON data", () => {
  const frame = 'id: 12\nevent: section_ready\ndata: {"section_id":"s1","words":240}';
  const parsed = parseFrame(frame);
  assert.equal(parsed.id, 12);
  assert.equal(parsed.type, "section_ready");
  assert.deepEqual(parsed.data, { section_id: "s1", words: 240 });
});

test("parseFrame keeps non-JSON payloads as strings", () => {
  const parsed = parseFrame("event: note\ndata: plain text");
  assert.equal(parsed.type, "note");
  assert.equal(parsed.data, "plain text");
  assert.equal(parsed.id, null);
});

test("parseFrame joins multi-line data", () => {
  const parsed = parseFrame('event: multi\ndata: {"a":\ndata: 1}');
  assert.deepEqual(parsed.data, { a: 1 });
});

test("parseFrame ignores comments and empty frames", () => {
  assert.equal(parseFrame(": keep-alive"), null);
  assert.equal(parseFrame(""), null);
});

test("parser handles frames split across chunks", () => {
  const parser = createSseParser();
  assert.deepEqual(parser.push("id: 1\nevent: log\nda"), []);
  const events = parser.push('ta: {"message":"hi"}\n\n');
  assert.equal(events.length, 1);
  assert.deepEqual(events[0].data, { message: "hi" });
});

test("parser returns several frames from one chunk", () => {
  const parser = createSseParser();
  const events = parser.push(
    'id: 1\nevent: a\ndata: {}\n\nid: 2\nevent: b\ndata: {"x":1}\n\n: heartbeat\n\n',
  );
  assert.deepEqual(
    events.map((event) => event.type),
    ["a", "b"],
  );
  assert.equal(parser.pending, "");
});

test("parser keeps partial frames buffered", () => {
  const parser = createSseParser();
  parser.push("id: 5\nevent: x\ndata: {}");
  assert.equal(parser.pending, "id: 5\nevent: x\ndata: {}");
  const events = parser.push("\n\n");
  assert.equal(events.length, 1);
  assert.equal(events[0].id, 5);
});
