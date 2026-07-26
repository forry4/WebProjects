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
import { spawn, spawnSync } from "node:child_process";
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

// Kill the process TREE, not just the child. Both servers are spawned with
// `shell: true`, so `child.kill()` reaps the shell and leaves the real uvicorn /
// vite grandchild running — which then squats on the port and makes the NEXT run
// test a stale backend (exactly the failure the started_at guard above now
// catches). Reaping properly is the actual fix; the guard is the safety net.
const killTree = (child) => {
	if (!child?.pid) return;
	try {
		if (process.platform === "win32") {
			// spawnSync, not spawn: shutdown() runs from process "exit", where an async
			// child never gets to run and the server survives the harness.
			spawnSync("taskkill", ["/pid", String(child.pid), "/T", "/F"], { stdio: "ignore" });
		} else {
			process.kill(-child.pid, "SIGKILL");
		}
	} catch { /* already gone */ }
	try { child.kill(); } catch {}
};
const shutdown = () => { for (const p of [api, preview]) killTree(p); };
process.on("exit", shutdown);
process.on("SIGINT", () => { shutdown(); process.exit(130); });

try {
	// Record BEFORE spawning: /health reports `started_at` (core/build_info), so we can
	// prove the backend answering us is the one WE started.
	//
	// THIS IS NOT PARANOIA. A stale uvicorn left on 8000 from an earlier session makes
	// our spawn fail to bind while the health check succeeds instantly — against the OLD
	// code. Every backend assertion then silently tests a build that no longer exists.
	// Caught exactly that way: a deliberately broken engine.apply_move still "passed".
	// The port can't just be randomised — VITE_WS_URL bakes localhost:8000 into the
	// bundle — so detect it and fail loudly instead.
	const spawnedAt = Math.floor(Date.now() / 1000);
	console.log("starting backend (uvicorn app:app) ...");
	api = spawn("python", ["-m", "uvicorn", "app:app", "--port", String(API_PORT)],
		{ cwd: repoRoot, stdio: "ignore", shell: true });
	await waitForHttp(`http://localhost:${API_PORT}/health`, 90_000, "backend");
	const health = await (await fetch(`http://localhost:${API_PORT}/health`)).json();
	if (!(health.started_at >= spawnedAt - 2)) {
		throw new Error(
			`port ${API_PORT} is already serving a DIFFERENT backend (started_at=${health.started_at}, ` +
			`we started at ${spawnedAt}). Kill it and re-run — otherwise this harness tests stale code.`);
	}
	console.log("  backend up (verified ours)");

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
	// and the first screen extracted out of Spender.jsx, so it gets its own pass
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

	// ── Play a turn ───────────────────────────────────────────────────────────
	// The only end-to-end exercise of the stack that actually matters: create a
	// vs-AI game, take gems, and watch the board change. Everything above proves
	// screens MOUNT. This proves the WebSocket handshake, the room server, the
	// engine's apply_move, the per-recipient broadcast and the AI scheduler all
	// still work together — none of which any other test touches from the client.
	//
	// It is also the coverage the shell/game split needs: `screen` currently
	// conflates the site-level mode with Spender's own browser/waiting/game, and
	// separating them is exactly the kind of change that renders fine and plays
	// wrong.
	{
		const ctx = await browser.newContext();
		await ctx.addInitScript(() => localStorage.setItem("spender_user",
			JSON.stringify({ id: "play-harness", name: "Player", guest: true })));
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

		await page.goto(`http://localhost:${PORT}/spender`, { waitUntil: "networkidle" });
		check("Spender lobby reachable by URL", await has(".lby-create-row"));

		// New Game -> the modal defaults to a vs-AI opponent, so accept and create.
		await page.locator(".lby-cta").click({ timeout: 15_000 }).catch(() => {});
		check("the create-game modal opens", await has(".cm-panel"));
		await page.locator(".cm-create").click({ timeout: 15_000 }).catch(() => {});

		// A vs-AI game starts immediately — no waiting room.
		check("a vs-AI game starts and the board renders", await has(".gem-stack", 30_000));
		const boardCards = await page.locator(".card").count().catch(() => 0);
		check("the board dealt its cards", boardCards >= 12, `saw ${boardCards}`);

		// The first player is randomised, so the bot may move first — WAIT for our
		// turn rather than assuming it. `disabled` marks a stack that can't be taken
		// (empty bank, or not our turn).
		let takeable = 0;
		for (let i = 0; i < 40 && takeable < 3; i++) {
			takeable = await page.locator(".gem-stack:not(.disabled)").count().catch(() => 0);
			if (takeable < 3) await sleep(500);
		}
		check("our turn arrives (waiting out the bot if it moved first)",
			takeable >= 3, `${takeable} takeable stacks`);

		// Snapshot our own panel: the server broadcast updating it is the proof the
		// move was really applied, and comparing text avoids depending on the exact
		// markup of the token row.
		const myPanel = () => page.locator(".player-panel.me").first().innerText().catch(() => "");
		const panelBefore = await myPanel();

		// Click three distinct COLOURS by data-color. Not `nth(i)` over the
		// non-disabled set: that set is re-evaluated after every click (selecting
		// gems disables others), and it includes the GOLD stack — whose click handler
		// arms a reserve and CLEARS the gem selection, which silently cost a gem.
		const colours = (await page.evaluate(() =>
			[...document.querySelectorAll(".gem-stack:not(.disabled)")]
				.map((e) => e.dataset.color)
				.filter((c) => c && c !== "gold"))).slice(0, 3);
		check("three colours are available to take", colours.length === 3, colours.join(","));
		for (const c of colours) {
			await page.locator(`.gem-stack[data-color="${c}"]`).click({ timeout: 10_000 }).catch(() => {});
		}
		// `button:visible` matters: the actions area is rendered THREE times (mobile and
		// desktop variants) and only one copy is visible. innerText happily reads a
		// hidden copy, so a plain .first() click times out — and because the click was
		// wrapped in .catch(() => {}), the move silently never happened while the label
		// check still passed. Clicking is now a CHECK, not a swallowed side effect.
		const takeBtn = page.locator("button:visible", { hasText: /^Take/ });
		const takeLabel = await takeBtn.first().innerText().catch(() => "");
		check("the Take button reflects the 3 selected gems",
			takeLabel.replace(/\s+/g, "") === "Take3", `label was ${JSON.stringify(takeLabel)}`);
		const submitted = await takeBtn.first().click({ timeout: 15_000 })
			.then(() => true).catch(() => false);
		check("the Take button is clickable", submitted);

		let panelAfter = panelBefore;
		for (let i = 0; i < 30 && panelAfter === panelBefore; i++) {
			await sleep(400);
			panelAfter = await myPanel();
		}
		check("the server applied the move and re-broadcast our panel",
			panelAfter !== panelBefore && panelAfter.length > 0,
			`panel unchanged: ${JSON.stringify(panelBefore.slice(0, 60))}`);
		// Back OUT of a live room. This drives applyPopRoute's inSpenderRoom branch —
		// the subtlest thing the site/Spender screen split touches, since it has to tell
		// "in a Spender ROOM" (waiting/game) from "in the Spender LOBBY" (browser) now
		// that those live in two different pieces of state.
		await page.goBack({ waitUntil: "networkidle" }).catch(() => {});
		const backToLobby = await has(".lby-create-row", 20_000);
		check("Back leaves a live game and returns to the Spender lobby", backToLobby,
			`url ${new URL(page.url()).pathname}`);

		// Puzzles are their own SITE-level mode but render on Spender's GAME screen —
		// the one place the two levels deliberately disagree (site mode "puzzles",
		// spenderScreen "game", puzzling=true, and no socket). /puzzles picks one
		// immediately rather than showing a list, so assert the board itself.
		await page.goto(`http://localhost:${PORT}/puzzles`, { waitUntil: "networkidle" });
		const puzzleBoard = await has(".game", 25_000);
		const puzzleText = await page.locator("#root").innerText().catch(() => "");
		check("a puzzle renders on Spender's game screen", puzzleBoard && /PUZZLE/i.test(puzzleText),
			`board=${puzzleBoard} url=${new URL(page.url()).pathname}`);

		check("no page errors while playing", errors.length === 0, errors[0]?.slice(0, 160) || "");
		await ctx.close();
	}

	// ── Two clients: the waiting room ─────────────────────────────────────────
	// Spender's `waiting` screen is only reachable in a human-vs-human game, so a
	// single-client walk can never see it — it was the last Spender screen with no
	// coverage at all. Two browser contexts: one creates a friend game, the other
	// joins by the shared room code, and both must end up seated in the same room.
	// This also exercises the join handshake and the broadcast fan-out to a SECOND
	// socket, which the vs-AI walk never touches.
	{
		const mk = async (id) => {
			const c = await browser.newContext();
			await c.addInitScript((pid) => localStorage.setItem("spender_user",
				JSON.stringify({ id: pid, name: pid, guest: true })), id);
			return c;
		};
		const hostCtx = await mk("host-harness");
		const joinCtx = await mk("join-harness");
		const host = await hostCtx.newPage();
		const joiner = await joinCtx.newPage();
		const errors = [];
		host.on("pageerror", (e) => errors.push("host: " + e));
		joiner.on("pageerror", (e) => errors.push("joiner: " + e));
		const check = (name, cond, detail = "") => {
			if (cond) console.log(`  OK   ${name}`);
			else { shell.push(name); console.log(`  FAIL ${name}  ${detail}`); }
		};

		await host.goto(`http://localhost:${PORT}/spender`, { waitUntil: "networkidle" });
		await host.waitForSelector(".lby-create-row", { timeout: 25_000 }).catch(() => {});
		await host.locator(".lby-cta").click({ timeout: 15_000 }).catch(() => {});
		await host.waitForSelector(".cm-panel", { timeout: 15_000 }).catch(() => {});
		// Switch the opponent segment from the default (AI) to "friend".
		await host.locator(".cm-seg button").first().click({ timeout: 10_000 }).catch(() => {});
		await host.locator(".cm-create").click({ timeout: 15_000 }).catch(() => {});

		const gotWaiting = await host.waitForSelector(".room-code-box", { timeout: 30_000 })
			.then(() => true).catch(() => false);
		check("a friend game reaches the waiting room", gotWaiting);
		const code = (await host.locator(".room-code-box").innerText().catch(() => "")).trim();
		check("the waiting room shows a join code", /^[A-Z]{4,8}$/.test(code), `got ${JSON.stringify(code)}`);

		if (code) {
			await joiner.goto(`http://localhost:${PORT}/spender`, { waitUntil: "networkidle" });
			await joiner.waitForSelector(".lby-code", { timeout: 25_000 }).catch(() => {});
			await joiner.locator(".lby-code").fill(code).catch(() => {});
			await joiner.locator(".lby-join-btn").click({ timeout: 15_000 }).catch(() => {});
			const joined = await joiner.waitForSelector(".room-code-box", { timeout: 30_000 })
				.then(() => true).catch(() => false);
			check("the second client joins that room", joined);

			// The host must LEARN about the joiner — that is the broadcast working.
			let seats = 0;
			for (let i = 0; i < 25 && seats < 2; i++) {
				seats = await host.locator(".player-list li").count().catch(() => 0);
				if (seats < 2) await sleep(400);
			}
			check("the host sees the second player arrive", seats >= 2, `saw ${seats} seats`);

			// DEEP LINK into that room by URL — the invite-link path. This is driven by
			// a separate deep-entry effect that only runs on Spender's LOBBY screen, and
			// a shipped bug proved nothing was watching it: after the site/Spender screen
			// split its guard still read `screen !== "browser"`, which can never be true
			// now, so invite links silently stopped working while every other check
			// stayed green.
			const deep = await joinCtx.newPage();
			await deep.goto(`http://localhost:${PORT}/spender/${code}`, { waitUntil: "networkidle" });
			const landed = await deep.waitForSelector(".room-code-box, .game", { timeout: 30_000 })
				.then(() => true).catch(() => false);
			check("a deep link enters the room it names", landed,
				`url ${new URL(deep.url()).pathname}`);
			await deep.close();
		}
		check("no page errors in the two-client flow", errors.length === 0, errors[0]?.slice(0, 160) || "");
		await hostCtx.close();
		await joinCtx.close();
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
