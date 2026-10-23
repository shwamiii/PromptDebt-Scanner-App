// Service worker: lets the installed app open offline by caching the app shell
// (HTML, CSS, JS, icons). API requests are never cached, so no watchlist, triage or
// key data is stored by it.
//
// Strategy: network first, so updates show up straight away; the cached copy is
// only used when the network fails.

const CACHE = "promptdebt-shell-v1";
const SHELL = [
  "./",
  "index.html",
  "styles.css",
  "manifest.json",
  "icons/icon.svg",
  "js/app.js",
  "js/api.js",
  "js/config.js",
  "js/format.js",
  "js/ui.js",
  "js/pages/item.js",
  "js/pages/report.js",
  "js/pages/scan.js",
  "js/pages/settings.js",
  "js/pages/triage.js",
  "js/pages/watchlist.js",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)))),
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  const isShell =
    event.request.method === "GET" && url.origin === self.location.origin && !url.pathname.startsWith("/api/");
  if (!isShell) return; // API and cross-origin requests go straight to the network.

  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(event.request, copy));
        }
        return response;
      })
      .catch(() => caches.match(event.request, { ignoreSearch: true })),
  );
});
