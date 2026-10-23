// App start-up and navigation.
//
// Screens are addressed by the part of the URL after "#", e.g. "#/watchlist/abc".
// Hash URLs keep the browser's (and Android's) back button working with no server
// setup, and work the same inside an installed app.

import { ensureKey } from "./api.js";
import { applyOnlineState, h } from "./ui.js";
import * as itemPage from "./pages/item.js";
import * as reportPage from "./pages/report.js";
import * as scanPage from "./pages/scan.js";
import * as settingsPage from "./pages/settings.js";
import * as triagePage from "./pages/triage.js";
import * as watchlistPage from "./pages/watchlist.js";

// [pattern, page, tab to highlight, parent route for the back button]
const ROUTES = [
  [/^\/$/, scanPage, "scan", null],
  [/^\/report\/([\w-]+)$/, reportPage, "scan", "/"],
  [/^\/watchlist$/, watchlistPage, "watchlist", null],
  [/^\/watchlist\/([\w-]+)$/, itemPage, "watchlist", "/watchlist"],
  [/^\/triage$/, triagePage, "triage", null],
  [/^\/settings$/, settingsPage, "settings", null],
];

const main = document.getElementById("main");
const title = document.getElementById("title");
const backButton = document.getElementById("back");

// Routes visited in this session, so Back knows whether there is an in-app page to
// return to. Opening a deep link starts with just that page, so Back goes to its
// parent route instead of leaving the app.
const visited = [];
let parentRoute = null;

function currentPath() {
  return location.hash.slice(1) || "/";
}

export function navigate(path) {
  location.hash = path;
}

export function goBack() {
  if (visited.length > 1) history.back();
  else location.replace(`#${parentRoute ?? "/"}`);
}

function setTitle(text, mono = false) {
  title.textContent = text;
  title.classList.toggle("mono", mono);
  document.title = text === "PromptDebt Scanner" ? text : `${text} · PromptDebt`;
}

function notFound(view) {
  setTitle("Page not found");
  view.append(
    h("div", { class: "empty" }, h("p", { class: "muted" }, "There's nothing at this address."),
      h("a", { class: "btn", href: "#/" }, "Go to Scan")),
  );
}

function render() {
  const path = currentPath();
  if (visited.length > 1 && visited[visited.length - 2] === path) visited.pop();
  else if (visited[visited.length - 1] !== path) visited.push(path);

  const match = ROUTES.map(([pattern, page, tab, parent]) => ({ m: path.match(pattern), page, tab, parent }))
    .find((r) => r.m);

  // Each render gets new container..
  const view = h("div", { class: "stack" });
  main.replaceChildren(view);
  window.scrollTo(0, 0);

  parentRoute = match?.parent ?? null;
  backButton.hidden = parentRoute === null;
  for (const link of document.querySelectorAll(".tabbar a")) {
    if (link.dataset.tab === match?.tab) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }

  const ctx = { setTitle, navigate, goBack, reload: render };
  if (match) match.page.render(view, match.m.slice(1), ctx);
  else notFound(view);

  applyOnlineState();
  title.focus({ preventScroll: true });
}

backButton.addEventListener("click", goBack);
window.addEventListener("hashchange", render);
window.addEventListener("online", applyOnlineState);
window.addEventListener("offline", applyOnlineState);

render();
ensureKey().catch(() => {
  // No key yet. Screens that need one will ask again.
});

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("sw.js").catch(() => {
    // The app still works without offline support.
  });
}
