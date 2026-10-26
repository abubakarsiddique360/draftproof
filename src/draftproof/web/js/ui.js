/** Tiny DOM helpers. All text is inserted with textContent. */

export function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props ?? {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class" || key === "className") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "html") node.innerHTML = value;
    else if (key === "dataset") Object.assign(node.dataset, value);
    else if (key === "style") {
      for (const [property, raw] of Object.entries(value)) {
        if (property.startsWith("--")) node.style.setProperty(property, String(raw));
        else node.style[property] = raw;
      }
    } else if (key.startsWith("on") && typeof value === "function") {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (value === true) node.setAttribute(key, "");
    else node.setAttribute(key, String(value));
  }
  append(node, children);
  return node;
}

export function append(node, children) {
  for (const child of children ?? []) {
    if (child === null || child === undefined || child === false) continue;
    if (Array.isArray(child)) append(node, child);
    else if (child instanceof Node) node.appendChild(child);
    else node.appendChild(document.createTextNode(String(child)));
  }
  return node;
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
  return node;
}

export function replace(node, ...children) {
  clear(node);
  append(node, children);
  return node;
}

export function badge(text, tone = "") {
  return el("span", { class: `badge${tone ? ` badge-${tone}` : ""}` }, text);
}

export function stat(label, value, hint) {
  return el(
    "div",
    { class: "card stat" },
    el("span", { class: "label" }, label),
    el("span", { class: "value" }, value),
    hint ? el("span", { class: "hint" }, hint) : null,
  );
}

export function dialogPrompt({ title, message, value = "", confirmLabel = "Submit" }) {
  return new Promise((resolve) => {
    const textarea = el("textarea", { rows: 4, class: "field-input", id: "prompt-notes" }, value);
    const dialog = el(
      "dialog",
      { class: "dialog", "aria-label": title },
      el(
        "form",
        { method: "dialog" },
        el("header", { class: "dialog-head" }, el("h2", {}, title)),
        message ? el("p", { class: "muted" }, message) : null,
        el("div", { class: "field" }, el("label", { for: "prompt-notes" }, "Notes"), textarea),
        el(
          "footer",
          { class: "dialog-foot" },
          el("button", { class: "btn btn-ghost", type: "button", onclick: () => close(null) }, "Cancel"),
          el("button", { class: "btn btn-primary", type: "submit" }, confirmLabel),
        ),
      ),
    );

    const close = (result) => {
      dialog.close();
      dialog.remove();
      resolve(result);
    };

    dialog.addEventListener("close", () => {
      if (dialog.isConnected) close(null);
    });
    dialog.querySelector("form").addEventListener("submit", (event) => {
      event.preventDefault();
      close(textarea.value.trim());
    });

    document.body.appendChild(dialog);
    dialog.showModal();
    textarea.focus();
  });
}
