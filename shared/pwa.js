/* Register the PWA service worker (webapp/public/sw.js) so the site is
 * installable to a phone home screen and opens offline.
 *
 * Gated to the real production hosts — the SAME hosts as index.html's backend
 * warm-up ping. Reasons:
 *   - A service worker is an extra caching layer; keeping it off localhost means
 *     the smoke/screens render gates (which serve a prod build on 127.0.0.1) and
 *     `npm run dev` never get one silently installed intercepting their requests.
 *   - Installability only matters on the deployed origin anyway.
 *
 * The worker itself (sw.js) is intentionally light and network-first for HTML —
 * see the header there for why it will not serve a stale bundle. Registration is
 * fire-and-forget and runs AFTER load, so it can't touch first paint or the CLS
 * budget, exactly like startUpdateNudge().
 */
export function startPwa() {
  try {
    if (!("serviceWorker" in navigator)) return;
    const host = location.hostname;
    const isProd = host === "forry4.github.io" || host.slice(-11) === ".workers.dev";
    if (!isProd) return;
    // BASE_URL is "/" on the prod user site; keep it relative so a sub-path
    // deploy would still resolve (and the worker's scope follows its location).
    const base = (import.meta.env && import.meta.env.BASE_URL) || "/";
    const register = () =>
      navigator.serviceWorker.register(`${base}sw.js`).catch(() => {});
    if (document.readyState === "complete") register();
    else window.addEventListener("load", register, { once: true });
  } catch {
    /* never let PWA setup break the app */
  }
}
