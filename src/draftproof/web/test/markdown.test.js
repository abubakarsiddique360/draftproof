import test from "node:test";
import assert from "node:assert/strict";

import { escapeHtml, renderInline, renderMarkdown, safeHref } from "../js/markdown.js";

test("escapeHtml neutralises markup", () => {
  assert.equal(escapeHtml('<script>"x"</script>'), "&lt;script&gt;&quot;x&quot;&lt;/script&gt;");
});

test("safeHref allows http(s) and relative links only", () => {
  assert.equal(safeHref("https://example.com"), "https://example.com");
  assert.equal(safeHref("/docs"), "/docs");
  assert.equal(safeHref("#anchor"), "#anchor");
  assert.equal(safeHref("javascript:alert(1)"), null);
  assert.equal(safeHref("data:text/html,evil"), null);
  assert.equal(safeHref("//evil.example.com"), null);
  assert.equal(safeHref(""), null);
});

test("renderInline escapes raw html and formats emphasis", () => {
  const html = renderInline("Hello <script>alert(1)</script> **bold** and *italic*");
  assert.ok(!html.includes("<script"));
  assert.ok(html.includes("<strong>bold</strong>"));
  assert.ok(html.includes("<em>italic</em>"));
});

test("renderInline drops unsafe link targets but keeps the label", () => {
  const html = renderInline("[click](javascript:alert(1))");
  assert.ok(!html.includes("javascript:"));
  assert.ok(html.includes("click"));
});

test("renderInline keeps safe links with rel attributes", () => {
  const html = renderInline("[docs](https://example.com/page)");
  assert.match(html, /href="https:\/\/example\.com\/page"/);
  assert.match(html, /rel="noopener noreferrer nofollow"/);
});

test("renderInline preserves code spans", () => {
  const html = renderInline("use `**not bold**` here");
  assert.ok(html.includes("<code>**not bold**</code>"));
  assert.ok(!html.includes("<strong>"));
});

test("renderMarkdown builds headings, lists and paragraphs", () => {
  const html = renderMarkdown("## Title\n\nFirst para.\nSecond line.\n\n- one\n- two\n\n1. first\n");
  assert.match(html, /<h2>Title<\/h2>/);
  assert.match(html, /<p>First para\. Second line\.<\/p>/);
  assert.match(html, /<ul><li>one<\/li><li>two<\/li><\/ul>/);
  assert.match(html, /<ol><li>first<\/li><\/ol>/);
});

test("renderMarkdown renders fenced code as escaped text", () => {
  const html = renderMarkdown("```python\nprint('<x>')\n```");
  assert.match(html, /<pre><code class="language-python">print\(&#39;&lt;x&gt;&#39;\)<\/code><\/pre>/);
  assert.ok(!html.includes("<x>"));
});

test("renderMarkdown escapes raw html blocks", () => {
  const html = renderMarkdown("<img src=x onerror=alert(1)>");
  assert.ok(!html.includes("<img"));
  assert.ok(html.includes("&lt;img"));
});

test("renderMarkdown handles blockquotes and rules", () => {
  const html = renderMarkdown("> quoted\n\n---\n");
  assert.match(html, /<blockquote>quoted<\/blockquote>/);
  assert.match(html, /<hr>/);
});

test("renderMarkdown tolerates empty input", () => {
  assert.equal(renderMarkdown(undefined), "");
  assert.equal(renderMarkdown(""), "");
});
