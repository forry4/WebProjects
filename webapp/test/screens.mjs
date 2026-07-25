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

	// ── Shell interactions ────────────────────────────────────────────────────
	// Rendering a screen by URL proves the component mounts. These prove the SHELL
	// still works: the state it owns (screen, identity, routing) is exactly what a
	// Spender.jsx shell/game split would break, and none of it is exercised by
	// loading a deep link directly.
	const shell = [];
	{
		const ctx = await browser.newContext();
		await ctx.addInitScript(() => localStorage.setItem("spender_user",
			JSON.stringify({ id: "screens-harness", name: "Harness", guest: true })));
		const page = await ctx.newPage();
		const errors = [];
		page.on("pageerror", (e) => errors.push(String(e)));

		const check = (name, cond, detail = "") => {
			if (cond) console.log(`  OK   ${name}`);
			else { shell.push(name); console.log(`  FAIL ${name}  ${detail}`); }
		};
		const has = async (sel, ms = 25_000) => {
			await page.waitForSelector(sel, { timeout: ms }).catch(() => {});
			return (await page.locator(sel).count().catch(() => 0)) > 0;
		};
		// A click that can't land is itself a finding, not a reason to abort: when the
		// shell breaks, several checks fail together and the whole picture is the
		// useful output. Swallow the timeout so the remaining checks still report.
		const click = async (sel, nth = 0) => {
			try { await page.locator(sel).nth(nth).click({ timeout: 15_000 }); return true; }
			catch { return false; }
		};
		const at = () => { try { return new URL(page.url()).pathname; } catch { return "?"; } };

		await page.goto(`http://localhost:${PORT}/`, { waitUntil: "networkidle" });
		check("home renders the game menu", await has(".home-game-card"));

		// Click through to a game. nav() must write the URL BEFORE switching screen,
		// because a sub-game reads parsePath() at mount.
		check("can click the Duel card", await click(".home-game-card", 3));
		check("clicking a game card mounts that game", await has(".duel"));
		check("...and the URL became its route", at() === "/duel", `got ${at()}`);

		// Back must return home. The router contract is that popstate is the ONLY
		// notifier and a no-op path write never double-pushes — a broken split shows
		// up here as Back doing nothing, or needing two presses.
		await page.goBack({ waitUntil: "networkidle" }).catch(() => {});
		check("Back returns to the home menu", await has(".home-game-card"));
		check("...and the URL went back to /", at() === "/", `got ${at()}`);

		// Spender's own lobby is the shell's most entangled screen: it shares the
		// shell's auth state and game-list fetching.
		check("can click the Spender card", await click(".home-game-card", 0));
		check("Spender lobby renders", await has(".browser"));

		check("no page errors during shell navigation", errors.length === 0,
			errors[0]?.slice(0, 160) || "");
		await ctx.close();
	}

	// ── Auth screen ───────────────────────────────────────────────────────────
	// Every context above SEEDS a guest identity to skip straight to a game, so
	// nothing else here ever renders the auth screen. It is the site's front door
	// and the first screen extracted into webapp/shell/, so it gets its own pass
	// with NO stored user.
	{
		const ctx = await browser.newContext();           // deliberately unseeded
		const page = await ctx.newPage();
		const errors = [];
		page.on("pageerror", (e) => errors.push(String(e)));
		const check = (name, cond, detail = "") => {
			if (cond) console.log(`  OK   ${name}`);
			else { shell.push(name); console.log(`  FAIL ${name}  ${detail}`); }
		};
		const has = async (sel, ms = 25_000) => {
			await page.waitForSelector(sel, { timeout: ms }).catch(() => {});
			return (await page.locator(sel).count().catch(() => 0)) > 0;
		};

		await page.goto(`http://localhost:${PORT}/`, { waitUntil: "networkidle" });
		check("a fresh visitor gets the auth screen", await has(".auth-screen"));
		check("...with all three tabs", await page.locator(".auth-tab").count() === 3);

		// Guest sign-in is the one path that needs no account, so it is the flow the
		// harness can drive end to end: it must produce an identity and land on home.
		await page.locator(".auth-tab").nth(2).click().catch(() => {});
		const guestBtn = page.locator("button", { hasText: "Play as Guest" });
		await guestBtn.click({ timeout: 15_000 }).catch(() => {});
		check("guest sign-in reaches the home menu", await has(".home-game-card"));
		const stored = await page.evaluate(() => localStorage.getItem("spender_user"));
		check("...and a guest is NOT persisted to localStorage", stored === null,
			`got ${stored}`);
		check("no page errors during auth", errors.length === 0, errors[0]?.slice(0, 160) || "");
		await ctx.close();
	}

	if (failures.length || shell.length) {
		console.error(`\nSCREENS FAIL — ${failures.length} screen(s), ${shell.length} shell interaction(s).`);
		process.exitCode = 1;
	} else {
		console.log(`\nSCREENS PASS — ${SCREENS.length} game screens + shell navigation, against a live backend.`);
	}
} catch (err) {
	console.error("SCREENS ERROR:", err.message);
	process.exitCode = 1;
} finally {
	try { await browser?.close(); } catch {}
	shutdown();
}
