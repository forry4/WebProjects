/* Service worker for the Forrest Games PWA.
 *
 * SOURCE lives at webapp/sw.js (NOT public/): the build emits it with __BUILD_ID__
 * replaced (see the emit-service-worker plugin in vite.config.js), so every deploy gets
 * its own cache name and `activate` drops the previous deploy's store. Local builds get
 * "dev". Registration (shared/pwa.js) is prod-host-gated, so dev servers never see it.
 *
 * Jobs, in order of importance:
 *  (1) satisfy the install criterion so the site is "Add to Home Screen"-able;
 *  (2) let a previously-visited install open offline instead of the browser error page;
 *  (3) hold the OFFLINE-PLAY assets (the wasm engine/AI + fonts) when the user asks —
 *      the PRECACHE_OFFLINE message below, sent from the Local-vs-AI hub. Spender's
 *      offline vs-AI mode runs entirely on those assets (games/spender/offline.js).
 *
 * CACHING POLICY — chosen to NOT become a second stale-content layer on top of the
 * ~10 min Pages CDN TTL and the version.json update-nudge (shared/update-nudge.js):
 *   - /assets/*  → cache-first. Vite emits these content-HASHED and immutable;
 *                  the URL changes whenever the bytes do, so a cache hit is
 *                  always the right bytes. This is where the PWA speed win is.
 *   - everything else (index.html, the SPA navigations, /wasm/* which keep the
 *                  SAME filename across builds — see CLAUDE.md, and would go
 *                  stale under cache-first) → network-first, cache only as an
 *                  OFFLINE fallback. Online, a deploy is always picked up.
 *   - version.json → never touched; the update-nudge MUST reach the network.
 *
 * PRECACHE_OFFLINE uses cache:"reload" requests on those same stable-name /wasm/ files:
 * that bypasses the HTTP cache (and with it the stale-wasm-behind-the-CDN-TTL trap) for
 * the copy that will serve offline, while the runtime policy for them stays network-first.
 */
const CACHE = "forrest-games-__BUILD_ID__";

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

// Deliberate offline-asset download, driven by the page (the Local-vs-AI hub) with a
// MessageChannel port for progress: {done,total} per file, then {ok:true} / {error}.
// Sequential on purpose — the wasm is ~5 MB and progress should mean something.
self.addEventListener("message", (event) => {
  const d = event.data || {};
  if (d.type !== "PRECACHE_OFFLINE" || !Array.isArray(d.urls)) return;
  const port = event.ports && event.ports[0];
  event.waitUntil((async () => {
    try {
      const cache = await caches.open(CACHE);
      let done = 0;
      for (const u of d.urls) {
        const res = await fetch(new Request(u, { cache: "reload" }));
        if (!res || !res.ok) throw new Error(`${u}: HTTP ${res && res.status}`);
        await cache.put(u, res);
        done += 1;
        try { port && port.postMessage({ done, total: d.urls.length }); } catch {}
      }
      try { port && port.postMessage({ ok: true }); } catch {}
    } catch (err) {
      try { port && port.postMessage({ error: String(err) }); } catch {}
    }
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
