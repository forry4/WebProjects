/* Service worker for the Forrest Games PWA.
 *
 * Its ONLY jobs are (1) to satisfy the install criterion so the site is
 * "Add to Home Screen"-able, and (2) to let a previously-visited install open
 * offline instead of showing the browser's dinosaur. It is deliberately NOT a
 * precaching / offline-play layer: the games are server-authoritative over a
 * WebSocket, so there is nothing to play offline anyway.
 *
 * CACHING POLICY — chosen to NOT become a second stale-content layer on top of
 * the ~10 min Pages CDN TTL and the version.json update-nudge (shared/update-nudge.js):
 *   - /assets/*  → cache-first. Vite emits these content-HASHED and immutable;
 *                  the URL changes whenever the bytes do, so a cache hit is
 *                  always the right bytes. This is where the PWA speed win is.
 *   - everything else (index.html, the SPA navigations, /wasm/* which keep the
 *                  SAME filename across builds — see CLAUDE.md, and would go
 *                  stale under cache-first) → network-first, cache only as an
 *                  OFFLINE fallback. Online, a deploy is always picked up.
 *   - version.json → never touched; the update-nudge MUST reach the network.
 *
 * Bump CACHE when this file's policy changes so `activate` drops the old store.
 */
const CACHE = "forrest-games-v1";

// Best-effort warm cache so a first offline load has a shell to fall back to.
// A failure here must not abort activation (a game dir may 404 during a deploy).
const PRECACHE = ["/", "/index.html", "/manifest.webmanifest", "/icon-192.png", "/icon-512.png"];

self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE).then((cache) => Promise.allSettled(PRECACHE.map((u) => cache.add(u))))
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)));
    await self.clients.claim();
  })());
});

async function cacheFirst(request) {
  const cache = await caches.open(CACHE);
  const hit = await cache.match(request);
  if (hit) return hit;
  const res = await fetch(request);
  if (res && res.ok && res.type === "basic") cache.put(request, res.clone());
  return res;
}

async function networkFirst(request) {
  const cache = await caches.open(CACHE);
  try {
    const res = await fetch(request);
    if (res && res.ok && res.type === "basic") cache.put(request, res.clone());
    return res;
  } catch (err) {
    const hit = await cache.match(request);
    if (hit) return hit;
    // A navigation that missed the cache (e.g. a deep link never opened offline
    // before) still gets the app shell — the SPA router reads the path itself.
    if (request.mode === "navigate") {
      const shell = await cache.match("/");
      if (shell) return shell;
    }
    throw err;
  }
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  // Only same-origin GETs. Cross-origin (the Render backend WS/health, fonts are
  // same-origin already) is left entirely to the browser.
  if (url.origin !== self.location.origin) return;
  // The update-nudge's freshness probe must always hit the network.
  if (url.pathname.endsWith("/version.json")) return;

  if (url.pathname.includes("/assets/")) {
    event.respondWith(cacheFirst(request));
  } else {
    event.respondWith(networkFirst(request));
  }
});
