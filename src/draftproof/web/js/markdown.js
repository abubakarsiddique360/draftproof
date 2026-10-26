/**
 * Small, safe Markdown renderer.
 *
 * Raw HTML in the source is escaped, and link targets are restricted to
 * http(s) and same-origin relative URLs. Nothing here ever inserts untrusted
 * markup: every string passes through escapeHtml first.
 */

const ESCAPES = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

export function escapeHtml(text) {
  return String(text ?? "").replace(/[&<>"']/g, (character) => ESCAPES[character]);
}

export function safeHref(href) {
  const value = String(href ?? "").trim();
  if (!value) return null;
  if (value.startsWith("//")) return null;
  if (/^https?:\/\//i.test(value)) return value;
  if (/^(\/|#|\.\/|\.\.\/)/.test(value)) return value;
  return null;
}

const TOKEN = "\u0000";

export function renderInline(text) {
  const codeSpans = [];
  let output = escapeHtml(text);
  output = output.replace(/`([^`]+)`/g, (_match, code) => {
    codeSpans.push(code);
    return `${TOKEN}${codeSpans.length - 1}${TOKEN}`;
  });
  output = output.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (match, label, href) => {
    const safe = safeHref(href);
    if (!safe) return label;
    return `<a href="${safe}" target="_blank" rel="noopener noreferrer nofollow">${label}</a>`;
  });
  output = output.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  output = output.replace(/(^|[\s(])\*([^*\n]+)\*(?=[\s).,;:!?]|$)/g, "$1<em>$2</em>");
  output = output.replace(/_{2}([^_]+)_{2}/g, "<strong>$1</strong>");
  output = output.replace(new RegExp(`${TOKEN}(\\d+)${TOKEN}`, "g"), (_match, index) => {
    return `<code>${codeSpans[Number(index)]}</code>`;
  });
  return output;
}

export function renderMarkdown(markdown) {
  const lines = String(markdown ?? "").replace(/\r\n/g, "\n").split("\n");
  const html = [];
  let paragraph = [];
  let list = null;

  const flushParagraph = () => {
    if (paragraph.length) {
      html.push(`<p>${renderInline(paragraph.join(" "))}</p>`);
      paragraph = [];
    }
  };

  const flushList = () => {
    if (!list) return;
    const items = list.items.map((item) => `<li>${renderInline(item)}</li>`).join("");
    html.push(`<${list.tag}>${items}</${list.tag}>`);
    list = null;
  };

  let index = 0;
  while (index < lines.length) {
    const line = lines[index];

    if (/^\s*```/.test(line)) {
      flushParagraph();
      flushList();
      const language = line.trim().slice(3).trim();
      const body = [];
      index += 1;
      while (index < lines.length && !/^\s*```/.test(lines[index])) {
        body.push(lines[index]);
        index += 1;
      }
      index += 1;
      const className = language ? ` class="language-${escapeHtml(language)}"` : "";
      html.push(`<pre><code${className}>${escapeHtml(body.join("\n"))}</code></pre>`);
      continue;
    }

    if (!line.trim()) {
      flushParagraph();
      flushList();
      index += 1;
      continue;
    }

    const heading = /^(#{1,4})\s+(.*)$/.exec(line);
    if (heading) {
      flushParagraph();
      flushList();
      const level = Math.min(4, heading[1].length);
      html.push(`<h${level}>${renderInline(heading[2])}</h${level}>`);
      index += 1;
      continue;
    }

    const quote = /^>\s?(.*)$/.exec(line);
    if (quote) {
      flushParagraph();
      flushList();
      html.push(`<blockquote>${renderInline(quote[1])}</blockquote>`);
      index += 1;
      continue;
    }

    if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) {
      flushParagraph();
      flushList();
      html.push("<hr>");
      index += 1;
      continue;
    }

    const bullet = /^\s*[-*+]\s+(.*)$/.exec(line);
    if (bullet) {
      flushParagraph();
      if (!list || list.tag !== "ul") {
        flushList();
        list = { tag: "ul", items: [] };
      }
      list.items.push(bullet[1]);
      index += 1;
      continue;
    }

    const ordered = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    if (ordered) {
      flushParagraph();
      if (!list || list.tag !== "ol") {
        flushList();
        list = { tag: "ol", items: [] };
      }
      list.items.push(ordered[1]);
      index += 1;
      continue;
    }

    paragraph.push(line.trim());
    index += 1;
  }

  flushParagraph();
  flushList();
  return html.join("\n");
}
