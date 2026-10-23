// Reusable UI pieces: element builder, status badge, toasts, dialogs, sheets and
// loading/empty/error states.
//
// Everything that shows repository data goes through h()

import { DEBT_LABELS, STATUS_LABELS } from "./format.js";

/** Create an element: h("a", { href: "#/", class: "btn" }, "Text", childNode). */
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs)) {
    if (value == null || value === false) continue;
    if (name.startsWith("on")) el.addEventListener(name.slice(2).toLowerCase(), value);
    else if (name === "class") el.className = value;
    else el.setAttribute(name, value === true ? "" : value);
  }
  for (const child of children.flat(Infinity)) {
    if (child == null || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

// Icons are fixed SVG markup written here, never built from API data.
const ICONS = {
  fresh: '<path d="M2 6.5 4.8 9 10 3" fill="none" stroke="currentColor" stroke-width="1.8"/>',
  ageing:
    '<circle cx="6" cy="6" r="4.5" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M6 1.5a4.5 4.5 0 0 1 0 9Z" fill="currentColor"/>',
  stale: '<path d="M6 1 11 10.5H1Z" fill="currentColor"/>',
  unknown:
    '<circle cx="6" cy="6" r="4.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-dasharray="2 1.5"/>',
  error: '<path d="M3 3l6 6M9 3 3 9" stroke="currentColor" stroke-width="1.8"/>',
};

export function icon(name) {
  const template = document.createElement("template");
  template.innerHTML = `<svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true">${ICONS[name]}</svg>`;
  return template.content.firstChild;
}

/** Freshness status: an icon and a word, so it never relies on colour alone. */
export function statusBadge(status) {
  return h("span", { class: `status status-${status}` }, icon(status), STATUS_LABELS[status]);
}

// Debt bands reuse the status colours and icons: Low = fresh, Moderate = ageing, High = stale.
const BAND_STYLE = { low: "fresh", moderate: "ageing", high: "stale" };

/** Prompt Debt Score, e.g. "▲ 47 Moderate": icon, number and word. Without a score,
 * just the band ("▲ Moderate"). */
export function debtBadge(score, band) {
  const style = BAND_STYLE[band];
  const text = score === null ? DEBT_LABELS[band] : `${score} ${DEBT_LABELS[band]}`;
  return h(
    "span",
    { class: `status status-${style}`, title: "Prompt Debt Score (0–100)" },
    icon(style),
    text,
  );
}

export function spinner() {
  return h("span", { class: "spinner", "aria-hidden": "true" });
}

/** Placeholder rows shown while a list loads. */
export function skeletonList(rows = 3) {
  const items = [];
  for (let i = 0; i < rows; i += 1) {
    items.push(h("div", { class: "skeleton" }), h("div", { class: "skeleton short" }));
  }
  return h("div", { "aria-busy": "true", "aria-label": "Loading" }, items);
}

export function emptyState(title, text, action) {
  return h("div", { class: "empty" }, h("h2", {}, title), h("p", { class: "muted" }, text), action);
}

export function errorState(message, onRetry) {
  return h(
    "div",
    { class: "error-state", role: "alert" },
    h("p", {}, message),
    h("button", { class: "btn", type: "button", onclick: onRetry }, "Retry"),
  );
}

/** Brief message at the bottom of the screen, announced to screen readers. */
export function toast(message, kind = "success") {
  const el = h(
    "div",
    { class: kind === "error" ? "toast toast-error" : "toast" },
    icon(kind === "error" ? "error" : "fresh"),
    message,
  );
  document.getElementById("toasts").append(el);
  setTimeout(() => el.remove(), kind === "error" ? 6000 : 4000);
}

/**
 * Run an async action with the button disabled and relabelled ("Saving…") until it
 * finishes, so it can't be pressed twice.
 */
export async function withBusy(button, busyLabel, action) {
  const label = button.textContent;
  button.disabled = true;
  button.textContent = busyLabel;
  try {
    return await action();
  } finally {
    button.disabled = false;
    button.textContent = label;
  }
}

const dialog = () => document.getElementById("dialog");

/** Ask before a destructive action. Resolves true if the user confirms. */
export function confirmDialog({ title, body, confirmLabel }) {
  const el = dialog();
  el.className = "dialog";
  return new Promise((resolve) => {
    const finish = (answer) => {
      el.close();
      resolve(answer);
    };
    el.replaceChildren(
      h("h2", { id: "dialog-title" }, title),
      h("p", { class: "muted" }, body),
      h(
        "div",
        { class: "dialog-actions" },
        h("button", { class: "btn", type: "button", onclick: () => finish(false) }, "Cancel"),
        h(
          "button",
          { class: "btn btn-danger", type: "button", onclick: () => finish(true) },
          confirmLabel,
        ),
      ),
    );
    el.setAttribute("aria-labelledby", "dialog-title");
    el.oncancel = () => resolve(false);
    el.showModal();
  });
}

/** Open a bottom sheet (a centred dialog on desktop). Returns a function that closes it. */
export function openSheet(title, content) {
  const el = dialog();
  el.className = "dialog sheet";
  const close = () => el.close();
  el.replaceChildren(
    h(
      "div",
      { class: "section-head" },
      h("h2", { id: "dialog-title" }, title),
      h("button", { class: "btn btn-quiet", type: "button", onclick: close }, "Close"),
    ),
    content,
  );
  el.setAttribute("aria-labelledby", "dialog-title");
  el.oncancel = null;
  el.showModal();
  return close;
}

/** A labelled input with an error line underneath. Returns the pieces. */
export function textField({ id, label, ...attrs }) {
  const input = h("input", { id, class: "input", "aria-describedby": `${id}-error`, ...attrs });
  const error = h("span", { id: `${id}-error`, class: "field-error", "aria-live": "polite" });
  const setError = (message) => {
    error.textContent = message ?? "";
    input.setAttribute("aria-invalid", message ? "true" : "false");
  };
  const field = h("div", { class: "field" }, h("label", { for: id }, label), input, error);
  return { field, input, setError };
}

/** Offline: show the banner and disable anything that needs GitHub.
 * Call again after adding buttons marked data-online-only. */
export function applyOnlineState() {
  const offline = !navigator.onLine;
  document.getElementById("offline").hidden = !offline;
  for (const el of document.querySelectorAll("[data-online-only]")) {
    el.disabled = offline;
  }
}
