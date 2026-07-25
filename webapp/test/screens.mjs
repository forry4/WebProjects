/* Game-screen render gate — the coverage `smoke.mjs` cannot provide.
 *
 * WHY THIS EXISTS. The smoke test loads three routes and asserts #root is non-empty,
 * which reads like "the app renders". It isn't: the shell pings the backend BEFORE it
 * routes anywhere, and the smoke run has no backend — so all three routes sit on the
 * loading screen. They report an identical #root length that is ~99% injected CSS.
 * Smoke genuinely catches a blank page, a bundle that throws, and layout shift. It has
 * never once rendered a game.
 *
 * So every game screen has been shipping unverified, which is also why the Spender.jsx
 * shell/game split keeps getting deferred: there is nothing to catch a regression in it.
 *
 * WHAT THIS DOES: boots the REAL backend (uvicorn on the composition root), serves the
 * built frontend on 5173 — which is load-bearing, `core/config.py` only allowlists that
 * port for CORS, and on any other port the browser fetch is blocked and the app hangs
 * on the loader — seeds a guest identity, then drives each game route and asserts it
 * rendered ITS OWN screen: distinct, substantial content and no uncaught page errors.
 *
 * Run: `npm run screens` (from webapp/). Needs Python + the backend requirements.
 */
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { chromium } from "playwright";

const webappDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(webappDir, "..");
const PORT = 5173;            // CORS-allowlisted; see above
const API_PORT = 8000;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Each game owns one route and must render a marker only IT can produce. The marker is
// a CSS class from that game's own stylesheet, so a screen that silently fell back to
// the shell (or to the loader) fails instead of passing on "something rendered".
const SCREENS = [
	{ path: "/duel", chunk: "SpenderDuel", marker: ".duel" },
	{ path: "/coc", chunk: "CastlesOfCrimson", marker: ".coc" },
	{ path: "/werewolf", chunk: "WhereWolf", marker: ".ww" },
	{ path: "/books", chunk: "Books", marker: ".bk-app" },
];

async function waitForHttp(url, timeoutMs, label) {
	const deadline = Date.now() + timeoutMs;
	while (Date.now() < deadline) {
		try {
			const res = await fetch(url);
			if (res.ok) return true;
		} catch { /* not up yet */ }
		await sleep(500);
	}
	throw new Error(`${label} did not come up at ${url} within ${timeoutMs}ms`);
}

async function launchBrowser() {
	try { return await chromium.launch(); }
	catch { return await chromium.launch({ channel: "msedge" }); }
}

let api, preview, browser;
const shutdown = () => {
	for (const p of [api, preview]) { try { p?.kill(); } catch {} }
};
process.on("exit", shutdown);
process.on("SIGINT", () => { shutdown(); process.exit(130); });

try {
	console.log("starting backend (uvicorn app:app) ...");
	api = spawn("python", ["-m", "uvicorn", "app:app", "--port", String(API_PORT)],
		{ cwd: repoRoot, stdio: "ignore", shell: true });
	await waitForHttp(`http://localhost:${API_PORT}/health`, 90_000, "backend");
	console.log("  backend up");

	// BUILD FIRST. Without this the harness happily tests whatever is already in
	// dist/ — and a build that FAILS leaves the previous, working bundle in place,
	// so a broken change would sail through green. (Caught exactly that way.)
	console.log("building ...");
	await new Promise((res, rej) => {
		const b = spawn("npx", ["vite", "build"], { cwd: webappDir, stdio: "ignore", shell: true });
		b.on("exit", (code) => (code === 0 ? res() : rej(new Error(`vite build exited ${code}`))));
	});

	console.log("serving the built frontend ...");
	preview = spawn("npx", ["vite", "preview", "--port", String(PORT), "--strictPort"],
		{ cwd: webappDir, stdio: "ignore", shell: true });
	await waitForHttp(`http://localhost:${PORT}/`, 60_000, "vite preview");
	console.log("  preview up");

	browser = await launchBrowser();
	const failures = [];

	for (const { path: route, chunk, marker } of SCREENS) {
		const ctx = await browser.newContext();
		// A guest identity skips the auth screen without touching the DB.
		await ctx.addInitScript(() => localStorage.setItem("spender_user",
			JSON.stringify({ id: "screens-harness", name: "Harness", guest: true })));
		const page = await ctx.newPage();
		const errors = [];
		const assets = [];
		page.on("pageerror", (e) => errors.push(String(e)));
		page.on("console", (m) => { if (m.type() === "error") errors.push(`console: ${m.text()}`); });
		page.on("request", (r) => {
			const u = r.url();
			if (u.includes("/assets/")) assets.push(u.split("/").pop());
		});

		await page.goto(`http://localhost:${PORT}${route}`, { waitUntil: "networkidle" });
		// The screen arrives after the backend ping resolves and the lazy chunk lands.
		let markerCount = 0;
		for (let i = 0; i < 20 && markerCount === 0; i++) {
			markerCount = await page.locator(marker).count().catch(() => 0);
			if (markerCount === 0) await sleep(400);
		}
		const rootLen = await page.evaluate(() => document.getElementById("root").innerHTML.length);
		const gotChunk = assets.some((a) => a.startsWith(`${chunk}-`));

		const problems = [];
		if (markerCount === 0) problems.push(`no element matching "${marker}" (screen never mounted)`);
		if (!gotChunk) problems.push(`lazy chunk ${chunk}-*.js was never fetched`);
		if (rootLen < 5000) problems.push(`#root only ${rootLen} chars (looks like the loader)`);
		if (errors.length) problems.push(`${errors.length} page error(s): ${errors[0].slice(0, 200)}`);

		if (problems.length) {
			failures.push(`${route}: ${problems.join("; ")}`);
			console.log(`  FAIL ${route}`);
			problems.forEach((p) => console.log(`         ${p}`));
		} else {
			console.log(`  OK   ${route.padEnd(10)} chunk=${chunk} #root=${rootLen}`);
		}
		await ctx.close();
	}

	if (failures.length) {
		console.error(`\nSCREENS FAIL — ${failures.length}/${SCREENS.length} game screens did not render.`);
		process.exitCode = 1;
	} else {
		console.log(`\nSCREENS PASS — all ${SCREENS.length} game screens rendered against a live backend.`);
	}
} catch (err) {
	console.error("SCREENS ERROR:", err.message);
	process.exitCode = 1;
} finally {
	try { await browser?.close(); } catch {}
	shutdown();
}
