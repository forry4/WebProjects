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
	{ path: "/dontminion", chunk: "Dontminion", marker: ".dm" },
	{ path: "/oddtrick", chunk: "Oddtrick", marker: ".odd" },
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

	// ── The shared lobby Rules button + how-to-play modal ─────────────────────
	// One kit, six lobbies — so it is worth driving all six rather than one. The
	// three contracts that regress silently:
	//   1. every lobby actually PASSES onRules (the button is opt-in, so a game
	//      that forgets it renders a perfectly fine lobby with no way in);
	//   2. the BODY is the scroller, not the page — `.rl-body` has min-height:0
	//      and one stray CSS edit turns the panel into a page-height modal whose
	//      "Got it" button sits below the fold (the shape every per-game copy of
	//      this modal used to have);
	//   3. on a phone the create row SCROLLS SIDEWAYS instead of wrapping, and
	//      the page itself must not scroll sideways with it.
	{
		const ctx = await browser.newContext();
		await ctx.addInitScript(() => localStorage.setItem("spender_user",
			JSON.stringify({ id: "rules-harness", name: "Rules", guest: true })));
		const page = await ctx.newPage();
		const errors = [];
		page.on("pageerror", (e) => errors.push(String(e)));
		const check = (name, cond, detail = "") => {
			if (cond) console.log(`  OK   ${name}`);
			else { shell.push(name); console.log(`  FAIL ${name}  ${detail}`); }
		};

		for (const route of ["/spender", "/coc", "/werewolf", "/duel", "/dontminion", "/oddtrick"]) {
			await page.goto(`http://localhost:${PORT}${route}`, { waitUntil: "networkidle" });
			await page.waitForSelector(".lby-rules", { timeout: 25_000 }).catch(() => {});
			const hasBtn = await page.locator(".lby-rules").count().catch(() => 0);
			check(`${route} lobby offers a Rules button`, hasBtn === 1, `count ${hasBtn}`);
			if (!hasBtn) continue;

			await page.locator(".lby-rules").click({ timeout: 10_000 }).catch(() => {});
			await page.waitForSelector(".rl-body", { timeout: 10_000 }).catch(() => {});
			const geom = await page.evaluate(() => {
				const panel = document.querySelector(".rl-panel");
				const body = document.querySelector(".rl-body");
				const done = document.querySelector(".rl-done");
				if (!panel || !body || !done) return null;
				return {
					panelH: panel.getBoundingClientRect().height,
					viewH: window.innerHeight,
					bodyScrolls: body.scrollHeight > body.clientHeight + 1,
					doneBottom: done.getBoundingClientRect().bottom,
					sections: document.querySelectorAll(".rl-sec").length,
				};
			});
			check(`${route} rules open with real content`, !!geom && geom.sections >= 4,
				JSON.stringify(geom));
			if (!geom) continue;
			check(`${route} rules scroll INSIDE the panel`,
				geom.bodyScrolls && geom.panelH <= geom.viewH,
				`panel ${Math.round(geom.panelH)} view ${geom.viewH} scrolls ${geom.bodyScrolls}`);
			check(`${route} rules keep the close button on screen`,
				geom.doneBottom <= geom.viewH, `bottom ${Math.round(geom.doneBottom)}`);

			await page.keyboard.press("Escape");
			await page.waitForSelector(".rl-panel", { state: "detached", timeout: 5_000 })
				.catch(() => {});
			const stillOpen = await page.locator(".rl-panel").count().catch(() => 1);
			check(`${route} rules close on Escape`, stillOpen === 0, `count ${stillOpen}`);
		}

		// Phones: five controls no longer fit, so the row must scroll rather than wrap.
		await page.setViewportSize({ width: 380, height: 760 });
		await page.goto(`http://localhost:${PORT}/dontminion`, { waitUntil: "networkidle" });
		await page.waitForSelector(".lby-create-row", { timeout: 25_000 }).catch(() => {});
		const row = await page.evaluate(() => {
			const el = document.querySelector(".lby-create-row");
			if (!el) return null;
			// "One row" can't be equal TOPS — the controls have different heights and
			// the row centers them. It is that every control overlaps every other
			// vertically, which a wrap breaks and a centered nowrap row never does.
			const boxes = [...el.children].map((c) => c.getBoundingClientRect());
			return {
				overflows: el.scrollWidth > el.clientWidth + 1,
				oneRow: Math.max(...boxes.map((b) => b.top)) < Math.min(...boxes.map((b) => b.bottom)),
				pageWide: document.documentElement.scrollWidth > window.innerWidth + 1,
			};
		});
		check("the phone create row scrolls sideways", !!row && row.overflows, JSON.stringify(row));
		check("...on ONE row (no wrap)", !!row && row.oneRow, JSON.stringify(row));
		check("...without making the PAGE scroll sideways", !!row && !row.pageWide,
			JSON.stringify(row));
		check("no page errors in the rules pass", errors.length === 0,
			errors[0]?.slice(0, 160) || "");
		await ctx.close();
	}

	// ── Dontminion's expansion picker ─────────────────────────────────────────
	// Three contracts that regress SILENTLY (a one-word edit to a useState, a CSS
	// rule that stops the list scrolling) and that nothing else here would catch:
	// Base Set alone is the default, the LIST scrolls rather than the modal, and
	// Select all toggles both ways. The set count grows every expansion phase, so
	// the picker is the part of that modal most likely to be touched.
	{
		const ctx = await browser.newContext();
		await ctx.addInitScript(() => localStorage.setItem("spender_user",
			JSON.stringify({ id: "picker-harness", name: "Picker", guest: true })));
		const page = await ctx.newPage();
		const errors = [];
		page.on("pageerror", (e) => errors.push(String(e)));
		const check = (name, cond, detail = "") => {
			if (cond) console.log(`  OK   ${name}`);
			else { shell.push(name); console.log(`  FAIL ${name}  ${detail}`); }
		};

		await page.goto(`http://localhost:${PORT}/dontminion`, { waitUntil: "networkidle" });
		await page.waitForSelector(".dm", { timeout: 25_000 }).catch(() => {});
		await page.getByRole("button", { name: /new game|create/i }).first()
			.click({ timeout: 15_000 }).catch(() => {});
		const opened = await page.waitForSelector(".dm-checks", { timeout: 15_000 })
			.then(() => true).catch(() => false);
		check("Dontminion's create modal opens", opened);

		if (opened) {
			const p = await page.evaluate(() => {
				const list = document.querySelector(".dm-checks");
				const panel = document.querySelector(".cm-panel");
				return {
					on: [...list.querySelectorAll(".dm-check-on")].map((b) => b.textContent.trim()),
					total: list.querySelectorAll(".dm-check").length,
					listScrolls: list.scrollHeight > list.clientHeight + 1,
					panelScrolls: panel.scrollHeight > panel.clientHeight + 1,
				};
			});
			check("...with Base Set the only expansion selected",
				p.on.length === 1 && /Base/.test(p.on[0]), JSON.stringify(p.on));
			// The list only NEEDS to scroll once it outgrows its cap; assert the
			// modal doesn't, which is the property the cap exists to preserve.
			check("...the expansion LIST scrolls, not the whole modal",
				!p.panelScrolls && (p.total < 4 || p.listScrolls),
				`list=${p.listScrolls} panel=${p.panelScrolls} of ${p.total}`);

			// The bot tier is the one create option that changes who you PLAY —
			// it must be pickable, and must default to the bot that plays a real
			// game (main.py coerces an unknown tier away silently, so a typo'd
			// id here would look fine and quietly seat the random bot).
			const bots = await page.evaluate(() => {
				const row = document.querySelector(".dm-cm-botstyle");
				if (!row) return null;
				return {
					label: row.querySelector(".cm-label")?.textContent.trim(),
					labels: [...row.querySelectorAll(".cm-seg-btn")].map((b) => b.textContent.trim()),
					sel: [...row.querySelectorAll(".cm-seg-btn.sel")].map((b) => b.textContent.trim()),
					// one line with the bot count, and its name must not wrap
					oneLine: row.getBoundingClientRect().top
						=== document.querySelector(".dm-cm-two > .dm-cm-col").getBoundingClientRect().top
						&& [...row.querySelectorAll(".cm-seg-btn")]
							.every((b) => b.getBoundingClientRect().height < 44),
				};
			});
			// Defaults to the STRONGEST tier (main.DEFAULT_DIFFICULTY = bmplus,
			// labelled "Money+"). Asserted on the label rather than the id
			// because the id never reaches the DOM; the full tier names ride
			// as button titles, since a longer label would be clipped by the
			// seg track's overflow:hidden — which is what the one-line check
			// below guards.
			check("...the bot style is pickable, defaulting to the strongest tier",
				!!bots && bots.labels.length >= 2 && bots.sel.length === 1
				&& /money\+/i.test(bots.sel[0]), JSON.stringify(bots));
			check("...sharing one line with the bot count, without wrapping",
				!!bots && bots.oneLine, JSON.stringify(bots));

			// The Require picker is built from /catalog, so an empty list means
			// the server field is missing or misnamed — exactly the drift the
			// wire-contract test can't see from the browser side.
			const req = await page.evaluate(() => {
				const list = document.querySelector(".dm-checks-req");
				if (!list) return null;
				return {
					labels: [...list.querySelectorAll(".dm-check")].map((b) => b.textContent.trim()),
					on: list.querySelectorAll(".dm-check-on").length,
					scrolls: list.scrollHeight > list.clientHeight + 1,
				};
			});
			check("...the Require picker offers all three bonuses, none preselected",
				!!req && req.labels.length === 3 && req.on === 0
				&& req.labels.some((l) => /\+2 Actions/.test(l))
				&& req.labels.some((l) => /\+1 Buy/.test(l))
				&& req.labels.some((l) => /\+2 Cards/.test(l)), JSON.stringify(req));
			// three fixed entries always fit — a scrollbar here means it wrongly
			// inherited the expansion list's cap
			check("...and the Require list needs no scrollbar", !!req && !req.scrolls,
				JSON.stringify(req));

			await page.click(".dm-checks-req .dm-check");
			const reqOn = await page.evaluate(() => ({
				on: document.querySelectorAll(".dm-checks-req .dm-check-on").length,
				hint: document.querySelector(".cm-hint")?.textContent || "",
			}));
			check("...checking one is reflected in the hint",
				reqOn.on === 1 && /always including a card that gives/.test(reqOn.hint),
				JSON.stringify(reqOn));
			await page.click(".dm-checks-req .dm-check");   // back to none for the create below

			await page.click(".dm-check-all");
			const all = await page.evaluate(() => ({
				on: document.querySelectorAll(".dm-checks .dm-check-on").length,
				total: document.querySelectorAll(".dm-checks .dm-check").length,
				disabled: document.querySelector(".cm-create").disabled,
			}));
			check("Select all turns every expansion on",
				all.total > 1 && all.on === all.total && !all.disabled, JSON.stringify(all));

			await page.click(".dm-check-all");
			const none = await page.evaluate(() => ({
				on: document.querySelectorAll(".dm-checks .dm-check-on").length,
				disabled: document.querySelector(".cm-create").disabled,
			}));
			// Empty is a REACHABLE state, so Create must refuse it — the server
			// rejects an empty expansion set and the error would be opaque.
			check("...and pressing it again clears them, disabling Create",
				none.on === 0 && none.disabled, JSON.stringify(none));
		}
		check("no page errors in the expansion picker", errors.length === 0,
			errors[0]?.slice(0, 160) || "");
		await ctx.close();
	}

	// ── Dontminion's card face ────────────────────────────────────────────────
	// The first check here that actually PLAYS Dontminion — the route test above
	// mounts the lobby and never renders a card. Two geometry contracts, both of
	// which a one-line CSS edit can break silently:
	//   1. all four text insets are EQUAL. They were 12px (the shared .card
	//      frame's padding stacked on each row's own), and the title's right
	//      inset was smaller still because FitText measured the PADDING box.
	//   2. on the smallest face (56px, the in-play rows) the cost coin sits
	//      BESIDE the type labels, not wrapped under them.
	{
		const ctx = await browser.newContext();
		await ctx.addInitScript(() => localStorage.setItem("spender_user",
			JSON.stringify({ id: "cardface-harness", name: "Face", guest: true })));
		const page = await ctx.newPage();
		const errors = [];
		page.on("pageerror", (e) => errors.push(String(e)));
		const check = (name, cond, detail = "") => {
			if (cond) console.log(`  OK   ${name}`);
			else { shell.push(name); console.log(`  FAIL ${name}  ${detail}`); }
		};

		await page.goto(`${`http://localhost:${PORT}`}/dontminion`, { waitUntil: "networkidle" });
		await page.waitForSelector(".dm", { timeout: 25_000 }).catch(() => {});
		await page.getByRole("button", { name: /new game|create/i }).first()
			.click({ timeout: 15_000 }).catch(() => {});
		await page.waitForSelector(".cm-panel", { timeout: 15_000 }).catch(() => {});
		await page.locator(".cm-create").click({ timeout: 15_000 }).catch(() => {});
		const dealt = await page.waitForSelector(".dm-supply .dm-card", { timeout: 30_000 })
			.then(() => true).catch(() => false);
		check("a Dontminion game deals a board", dealt);

		if (dealt) {
			const g = await page.evaluate(() => {
				const c = document.querySelector(".dm-supply .dm-card");
				const cb = c.getBoundingClientRect();
				const span = c.querySelector(".dm-fitspan").getBoundingClientRect();
				const nameBox = c.querySelector(".dm-card-name");
				const ncs = getComputedStyle(nameBox);
				const types = c.querySelector(".dm-types").getBoundingClientRect();
				const cost = c.querySelector(".dm-cost").getBoundingClientRect();
				const r = (n) => +n.toFixed(1);
				return {
					titleLeft: r(span.left - cb.left),
					titleRight: r(cb.right - span.right),
					typesLeft: r(types.left - cb.left),
					costRight: r(cb.right - cost.right),
					costBottom: r(cb.bottom - cost.bottom),
					// the FitText bug: the name grew into its own right inset
					nameOverflow: r(span.width - (nameBox.clientWidth
						- parseFloat(ncs.paddingLeft) - parseFloat(ncs.paddingRight))),
				};
			});
			// The title is left-aligned and usually shorter than the card, so its
			// RIGHT gap is only meaningful as "at least the inset" — the bug made
			// it smaller than the left one.
			check("card insets are the same on every side",
				Math.abs(g.typesLeft - g.costRight) < 1 && Math.abs(g.typesLeft - g.costBottom) < 1
				&& Math.abs(g.typesLeft - g.titleLeft) < 1, JSON.stringify(g));
			// FitText only misbehaves on a name it has to SHRINK, and no supply name
			// shrinks at any sane width — asserting at desktop size PASSED with the
			// bug still in (verified, which is why this block exists).
			//
			// So narrow the viewport until the always-present Province pile is forced
			// to shrink. Narrow it TOO far and the required size drops under FitText's
			// own 8px floor, where the text overflows no matter how it was measured —
			// a real limit, but not this bug, and asserting there fails on correct
			// code. The rig therefore sweeps down and stops at the first width that
			// shrinks the name while staying ABOVE the floor. Geometry is
			// deterministic, so this picks the same width every run; if no width
			// qualifies the check FAILS rather than passing unexercised.
			let rig = null;
			for (const w of [320, 300, 280, 260, 250, 245, 240, 235]) {
				await page.setViewportSize({ width: w, height: 900 });
				// FitText refits from a ResizeObserver, so the reading right after a
				// resize can be the PREVIOUS width's. Poll until two consecutive
				// samples agree instead of trusting one fixed sleep — an
				// intermittently-failing shared gate is worse than no gate.
				let prev = null;
				for (let i = 0; i < 12; i++) {
					await sleep(150);
					const now = await page.evaluate(() => {
						const c = [...document.querySelectorAll(".dm-supply .dm-card")]
							.find((x) => x.querySelector(".dm-fitspan")?.textContent === "Province");
						return c ? getComputedStyle(c.querySelector(".dm-card-name")).fontSize : null;
					});
					if (now && now === prev) break;
					prev = now;
				}
				const r = await page.evaluate(() => {
					const card = [...document.querySelectorAll(".dm-supply .dm-card")]
						.find((c) => c.querySelector(".dm-fitspan")?.textContent === "Province");
					if (!card) return null;
					const box = card.querySelector(".dm-card-name");
					const span = card.querySelector(".dm-fitspan");
					const cs = getComputedStyle(box);
					const content = box.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
					const cb = card.getBoundingClientRect(), sb = span.getBoundingClientRect();
					return {
						shrank: !!box.style.fontSize,
						fontPx: +parseFloat(cs.fontSize).toFixed(2),
						overflow: +(sb.width - content).toFixed(1),
						gapLeft: +(sb.left - cb.left).toFixed(1),
						gapRight: +(cb.right - sb.right).toFixed(1),
					};
				});
				if (r?.shrank && r.fontPx > 8.05) { rig = { w, ...r }; break; }
			}
			check("...and a title it must shrink still respects its right inset",
				!!rig && rig.overflow <= 0.5 && Math.abs(rig.gapLeft - rig.gapRight) < 1.5,
				JSON.stringify(rig));
			await page.setViewportSize({ width: 1280, height: 900 });
			await sleep(400);

			// Longest type label on the SMALLEST face: clone a real card into the
			// 56px in-play context rather than trusting a computed estimate.
			const fit = await page.evaluate(() => {
				const host = document.querySelector(".dm-opp-inplay");
				const clone = document.querySelector(".dm-supply .dm-card").cloneNode(true);
				// The in-play rows animate cards in (dm-enter scales them up), and a
				// freshly appended clone is measured MID-ANIMATION: rects come back
				// ~6% small. A uniform scale doesn't change whether the foot wrapped,
				// so the verdict held — but the reported widths were fiction. Kill the
				// animation and assert we measured settled layout, so a future
				// geometry surprise fails loudly instead of printing numbers that
				// don't reconcile.
				clone.style.animation = "none";
				const t = clone.querySelectorAll(".dm-type");
				[...t].slice(1).forEach((x) => x.remove());
				t[0].textContent = "Duration";          // the widest label we ship
				host.appendChild(clone);
				const foot = clone.querySelector(".dm-card-foot");
				const costEl = clone.querySelector(".dm-cost");
				const fcs = getComputedStyle(foot);
				const avail = foot.clientWidth - parseFloat(fcs.paddingLeft) - parseFloat(fcs.paddingRight)
					- costEl.getBoundingClientRect().width - parseFloat(fcs.columnGap || "0");
				const label = t[0].getBoundingClientRect().width;
				const types = clone.querySelector(".dm-types").getBoundingClientRect();
				const cost = costEl.getBoundingClientRect();
				const out = {
					faceW: +clone.getBoundingClientRect().width.toFixed(1),
					cssW: +parseFloat(getComputedStyle(clone).width).toFixed(1),
					avail: +avail.toFixed(1), label: +label.toFixed(1),
					slack: +(avail - label).toFixed(1),
					wrapped: cost.top >= types.bottom - 0.5,
				};
				clone.remove();
				return out;
			});
			check("the cost coin shares a row with the types on the 56px face",
				!fit.wrapped && fit.slack > 0 && Math.abs(fit.faceW - fit.cssW) < 0.5,
				JSON.stringify(fit));

			// The count pill straddles the card's bottom edge, so tightening the
			// foot's inset walked the type label straight under it — 7px of overlap
			// on every supply pile, which is how this check earned its place.
			const pills = await page.evaluate(() => {
				const bad = [];
				for (const slot of document.querySelectorAll(".dm-pile-slot")) {
					// Fan slots (your hand, an opponent's hand) hold a ROW of cards under
					// one centred pill, so "the slot's card" is meaningless there — the
					// pill is not labelling the card it happens to sit over. Only
					// single-card slots have the pill-labels-this-card relationship.
					if (slot.matches(".dm-myhand, .dm-opp-hand")) continue;
					const card = slot.querySelector(".dm-card");
					const pill = slot.querySelector(".dm-pile-count");
					if (!card || !pill) continue;
					const pb = pill.getBoundingClientRect();
					for (const [what, el] of [["types", card.querySelector(".dm-types")],
						["cost", card.querySelector(".dm-cost")]]) {
						if (!el || !el.textContent.trim()) continue;
						const b = el.getBoundingClientRect();
						if (pb.top < b.bottom && pb.bottom > b.top && pb.left < b.right && pb.right > b.left) {
							bad.push({ card: card.querySelector(".dm-fitspan")?.textContent, what,
								by: +(b.bottom - pb.top).toFixed(1) });
						}
					}
				}
				return bad.slice(0, 5);
			});
			check("the pile count never covers a card's type or cost",
				pills.length === 0, JSON.stringify(pills));

			// ── the landscape row: EMPTY here, real on an Adventures board ────────
			// This board is Base Set only, so it has no Events and the row must
			// render NOTHING — not an empty flex container with its own padding and
			// border, which would push the whole Supply down on every game that
			// isn't using landscapes. Token badges are the same story.
			const dormant = await page.evaluate(() => ({
				rows: document.querySelectorAll(".dm-lscape-row").length,
				faces: document.querySelectorAll(".dm-lscape").length,
				tokens: document.querySelectorAll(".dm-tokens").length,
				supplyTop: document.querySelector(".dm-supply")
					?.firstElementChild?.className ?? null,
			}));
			check("a board with no landscapes renders no landscape row at all",
				dormant.rows === 0 && dormant.faces === 0 && dormant.tokens === 0
				&& /dm-basics/.test(dormant.supplyTop || ""),
				JSON.stringify(dormant));

			// ── Supply faces render fitted rules text (the `body` opt-in) ─────────
			// Rules text used to be gated off small faces; supply piles now pass
			// <DmCardFace body> and FitBodyText fills within a 10-16px band, cutting
			// a too-long rule with "…" (the full card is a press/right-click away).
			// The deal is RANDOM, so rather than demand a particular wordy card (a
			// ~2% deal has none — a flaky gate), assert the INVARIANTS: text renders,
			// the band holds, nothing overflows, short cards hit the ceiling, and a
			// face is truncated IFF its full rule can't fit at the floor. The
			// biconditional exercises the truncation logic on every deal without
			// depending on which cards were dealt.
			await page.setViewportSize({ width: 1000, height: 900 });   // squeezes kingdom piles to the 88px floor
			await sleep(500);                                           // let FitBodyText's ResizeObserver refit
			const bodyTxt = await page.evaluate(() => {
				const rows = [...document.querySelectorAll(".dm-supply .dm-card")].map((c) => {
					const el = c.querySelector(".dm-card-body");
					const name = c.querySelector(".dm-fitspan")?.textContent;
					if (!el) return { name, hasBody: false };
					const px = +parseFloat(getComputedStyle(el).fontSize).toFixed(2);
					const shown = el.textContent;
					// full rule rides in the face's title as "Name (cost) — <text>"
					const full = (c.getAttribute("title") || "").split(" — ").slice(1).join(" — ");
					// measure the FULL text at the floor, then restore the fitter's output
					const prevF = el.style.fontSize, prevT = el.textContent;
					el.style.fontSize = "10px"; el.textContent = full;
					const fullOverflows = el.scrollHeight > el.clientHeight + 0.5;
					el.textContent = prevT; el.style.fontSize = prevF;
					return { name, hasBody: true, px, shown, truncated: /…$/.test(shown),
						fullOverflows, overflow: el.scrollHeight - el.clientHeight };
				});
				const b = rows.filter((r) => r.hasBody);
				const basic = /^(Copper|Silver|Gold|Estate|Duchy|Province|Curse)$/;
				return {
					total: rows.length, withText: b.filter((r) => r.shown && r.shown.length).length,
					outOfBand: b.filter((r) => r.px < 9.9 || r.px > 16.1).map((r) => [r.name, r.px]),
					overflowing: b.filter((r) => r.overflow > 1).map((r) => r.name),
					short: b.filter((r) => basic.test(r.name)),
					mismatch: b.filter((r) => r.truncated !== r.fullOverflows).map((r) => [r.name, r.truncated, r.fullOverflows]),
					floorOff: b.filter((r) => r.truncated && Math.abs(r.px - 10) > 0.6).map((r) => [r.name, r.px]),
					sample: b.slice(0, 3).map((r) => [r.name, r.px, r.truncated]),
				};
			});
			check("every supply pile renders fitted body text",
				bodyTxt.total > 0 && bodyTxt.withText === bodyTxt.total, JSON.stringify(bodyTxt.sample));
			// short cards must NOT balloon (ceiling) and nothing may overflow (floor)
			check("...within the 10-16px band, short cards capped, none overflowing",
				bodyTxt.outOfBand.length === 0 && bodyTxt.overflowing.length === 0
				&& bodyTxt.short.length > 0 && bodyTxt.short.every((r) => r.px >= 15.5),
				JSON.stringify({ band: bodyTxt.outOfBand, over: bodyTxt.overflowing,
					short: bodyTxt.short.map((r) => [r.name, r.px]) }));
			// truncation is exactly "the full rule can't fit at the floor", and every
			// cut face sits at the 10px floor
			check("...truncated with an ellipsis iff the full rule can't fit at the floor",
				bodyTxt.mismatch.length === 0 && bodyTxt.floorOff.length === 0,
				JSON.stringify({ mismatch: bodyTxt.mismatch, floorOff: bodyTxt.floorOff }));
			await page.setViewportSize({ width: 1280, height: 900 });
			await sleep(400);

			// The log reads CHRONOLOGICALLY — oldest at the top, newest at the
			// bottom — and follows the newest line. Both the brightened line and
			// the slide-in animation key off :last-child, so a flip back to
			// newest-first would highlight and animate the wrong end silently.
			const readLog = () => page.evaluate(() => {
				const box = document.querySelector(".dm-log");
				if (!box) return null;
				const lines = [...box.querySelectorAll(".dm-log-line")].map((l) => l.textContent.trim());
				return {
					lines,
					atBottom: box.scrollHeight - box.scrollTop - box.clientHeight < 80,
					// the turn-1 marker is the OLDEST turn event, so chronological
					// order puts it near the top, never at the very end
					firstTurnIdx: [...box.querySelectorAll(".dm-log-line")]
						.findIndex((l) => l.classList.contains("dm-log-turn")),
				};
			});
			const logBefore = await readLog();

			// Right-click / press-and-hold opens the card's detail modal without
			// firing the card's PRIMARY action. Tested on an affordable Copper in
			// the buy phase, because that is the case where a plain click really
			// does buy — the pile count is the witness that it didn't.
			await page.locator(".dm-turnbtns .btn", { hasText: /to buy phase/i })
				.click({ timeout: 10_000 }).catch(() => {});
			await sleep(800);

			const copperCount = () => page.evaluate(() => {
				const el = [...document.querySelectorAll(".dm-supply .dm-pile-slot")]
					.find((x) => x.querySelector(".dm-fitspan")?.textContent === "Copper");
				return el?.querySelector(".dm-pile-count")?.textContent ?? null;
			});
			const infoOpen = () => page.locator(".dm-cardinfo").count().then((n) => n > 0);
			const closeInfo = async () => {
				if (await infoOpen()) {
					await page.locator(".dm-backdrop").first().click({ position: { x: 5, y: 5 } });
					await sleep(250);
				}
			};
			const copper = page.locator(".dm-supply .dm-card").filter({ hasText: "Copper" }).first();
			const c0 = await copperCount();
			await copper.click({ button: "right" });
			await sleep(350);
			const rc = { opened: await infoOpen(), title: await page.locator(".dm-cardinfo-detail h2")
				.textContent().catch(() => null) };
			await closeInfo();
			const c1 = await copperCount();
			check("right-click opens the card detail without buying",
				rc.opened && rc.title === "Copper" && c0 === c1 && c0 !== null,
				JSON.stringify({ ...rc, c0, c1 }));

			// Synthetic touch hold — Playwright has no press-and-hold, and the iOS
			// path is a timer rather than a `contextmenu`, so dispatch the real
			// pointer sequence with pointerType "touch".
			const bb = await copper.boundingBox();
			const hold = (ms) => page.evaluate(async ([x, y, dur]) => {
				const el = document.elementFromPoint(x, y).closest(".dm-card");
				const mk = (type) => new PointerEvent(type, { bubbles: true, cancelable: true,
					composed: true, pointerId: 1, pointerType: "touch", isPrimary: true,
					clientX: x, clientY: y });
				el.dispatchEvent(mk("pointerdown"));
				await new Promise((r) => setTimeout(r, dur));
				el.dispatchEvent(mk("pointerup"));
				el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true,
					clientX: x, clientY: y }));
			}, [bb.x + bb.width / 2, bb.y + bb.height / 2, ms]);

			await hold(650);
			await sleep(350);
			const heldOpen = await infoOpen();
			await closeInfo();
			const c2 = await copperCount();
			check("press-and-hold opens the card detail without buying",
				heldOpen && c1 === c2, JSON.stringify({ heldOpen, c1, c2 }));

			// ...and the gesture must not eat an ordinary tap.
			await hold(80);
			await sleep(800);
			const c3 = await copperCount();
			const tapOpened = await infoOpen();
			await closeInfo();
			check("a short tap still buys, and opens nothing",
				c2 !== c3 && !tapOpened, JSON.stringify({ c2, c3, tapOpened }));

			// That buy ALWAYS logs (unlike the phase click, which logs nothing the
			// client renders — anchoring here instead of there is what makes this
			// deterministic rather than deal-dependent). Chronological order means
			// the log only ever grows at the END, so everything on screen before
			// the buy must still be there, in order, as a PREFIX of the new list.
			// Asserting a specific "newest line" can't work — the bot moves too.
			const logAfter = await readLog();
			const grewAtEnd = !!logBefore && !!logAfter
				&& logAfter.lines.length > logBefore.lines.length
				&& logBefore.lines.every((t, i) => logAfter.lines[i] === t);
			check("the log runs oldest-to-newest — new lines are APPENDED at the bottom",
				grewAtEnd, JSON.stringify({
					before: logBefore?.lines.slice(-3), after: logAfter?.lines.slice(-5),
				}));

			// ...and it FOLLOWS that newest line, including after a scroll the
			// READER did not cause. The list renders only the newest 200 lines, so
			// past 200 entries every turn evicts lines off the top and Chrome's
			// scroll ANCHORING pulls scrollTop back on its own to hold the visible
			// text still. Reading that as "they scrolled up to re-read" latched the
			// log in place for the rest of the game — and only on a PC, because iOS
			// Safari implements no scroll anchoring. Simulated directly (a scroll
			// with no preceding gesture) rather than by playing 200 turns, and the
			// log is forced to overflow so the check can't be vacuous on a short one.
			// force a scroller regardless of how much this deal has logged, and start
			// it pinned at the bottom so the move away from it is a REAL change the
			// browser reports (React sets no style prop on this element, so the
			// inline max-height survives every re-render)
			await page.evaluate(() => {
				const el = document.querySelector(".dm-log");
				el.style.maxHeight = "60px";
				el.scrollTop = el.scrollHeight;
			});
			await sleep(200);
			const logPre = await page.evaluate(() => {
				const el = document.querySelector(".dm-log");
				if (!el) return null;
				el.scrollTop = 0;   // ...as scroll anchoring does: no gesture, real event
				return { n: el.querySelectorAll(".dm-log-line").length,
					canScroll: el.scrollHeight > el.clientHeight + 4 };
			});
			await sleep(300);       // let that scroll event dispatch
			// ending the turn is the reliable log generator here — the buy phase is
			// already spent by the tap test above, and the bot's reply logs plenty
			await page.locator(".dm-turnbtns .btn", { hasText: /end turn/i })
				.click({ timeout: 10_000 }).catch(() => {});
			await sleep(2500);
			const follow = await page.evaluate(() => {
				const el = document.querySelector(".dm-log");
				const r = { gap: +(el.scrollHeight - el.scrollTop - el.clientHeight).toFixed(1),
					n: el.querySelectorAll(".dm-log-line").length };
				el.style.maxHeight = "";
				return r;
			});
			check("the log still follows the newest line after a scroll the reader did not cause",
				!!logPre && logPre.canScroll && follow.n > logPre.n && follow.gap < 48,
				JSON.stringify({ canScroll: logPre?.canScroll, lines: [logPre?.n, follow.n],
					gapFromBottom: follow.gap }));

			// Phone width stacks your piles / hand / buttons into one column, and the
			// count pills hang BELOW their slot — so "hand N" landed on top of the
			// buttons (measured 6px into them). Nothing in the column may overlap.
			await page.setViewportSize({ width: 390, height: 844 });
			await sleep(600);
			const mob = await page.evaluate(() => {
				const pill = document.querySelector(".dm-myhand .dm-pile-count");
				const btns = document.querySelector(".dm-turnbtns");
				if (!pill || !btns) return { missing: true };
				const p = pill.getBoundingClientRect(), b = btns.getBoundingClientRect();
				// ...and lifting it must not push it onto a card's own text
				let onCard = null;
				for (const el of document.querySelectorAll(".dm-me .dm-types, .dm-me .dm-cost")) {
					if (!el.textContent.trim()) continue;
					const r = el.getBoundingClientRect();
					if (p.top < r.bottom && p.bottom > r.top && p.left < r.right && p.right > r.left) {
						onCard = el.className; break;
					}
				}
				return { overlapWithButtons: +(p.bottom - b.top).toFixed(1), onCard };
			});
			check("on a phone the hand count clears the buttons and the cards",
				!mob.missing && mob.overlapWithButtons < 0 && !mob.onCard, JSON.stringify(mob));
			await page.setViewportSize({ width: 1280, height: 900 });
			await sleep(300);
		}
		check("no page errors while rendering the board", errors.length === 0,
			errors[0]?.slice(0, 160) || "");
		await ctx.close();
	}

	// ── the landscape row on a REAL Adventures board (ph. 7) ──────────────────
	// The empty-state pin above is the layout-shift guard; it says nothing about
	// whether the row WORKS, and a component that throws on its first real
	// landscape would satisfy it perfectly. Adventures ships 20 Events, so the
	// row is now reachable by any player and owes a real render.
	//
	// ─── Lobby History pages 10 at a time, and stops at 50 ───────────────────
	// `useProgressiveList` (shared/lobby.jsx) is wired identically into all four
	// lobbies, so covering it once covers the logic; each game's wiring is one
	// line. Driven against a STUBBED /games/history rather than a seeded DB: the
	// point is the reveal, and 55 synthetic rows make both the page size and the
	// HISTORY_MAX cap exact instead of dependent on what this box has played.
	{
		const ctx = await browser.newContext();
		// a session_token so the lobby actually fetches history (a guest is short-
		// circuited to an empty list), and a SHORT viewport so the initial 10 rows
		// push the sentinel below the fold — otherwise a tall window can see the
		// end of the list immediately and legitimately reveals the next page at
		// mount, which would make "shows 10" flaky rather than wrong.
		await ctx.addInitScript(() => localStorage.setItem("spender_user",
			JSON.stringify({ id: "hist-harness", name: "Histy", session_token: "stub" })));
		const page = await ctx.newPage();
		await page.setViewportSize({ width: 1280, height: 500 });
		const errors = [];
		page.on("pageerror", (e) => errors.push(String(e)));
		const check = (name, cond, detail = "") => {
			if (cond) console.log(`  OK   ${name}`);
			else { shell.push(name); console.log(`  FAIL ${name}  ${detail}`); }
		};

		// The shell validates the stored session on load and a definitively-dead
		// token clears the login — but a NETWORK error never does (deliberate), so
		// aborting is how the seeded user survives without guessing the payload.
		await page.route("**/auth/session*", (r) => r.abort());
		const TOTAL = 55;     // > HISTORY_MAX, so the cap is exercised too
		await page.route("**/games/history*", (r) => r.fulfill({
			status: 200, contentType: "application/json",
			body: JSON.stringify({
				ok: true,
				games: Array.from({ length: TOTAL }, (_, i) => ({
					id: `G${String(i).padStart(3, "0")}`,
					players: ["Histy", "Bot 1"], opponents: ["Bot 1"],
					your_vp: 30, scores: { Histy: 30, "Bot 1": 10 },
					standings: [{ name: "Histy", vp: 30, you: true, won: true },
						{ name: "Bot 1", vp: 10, you: false, won: false }],
					you_won: true, winners: ["Histy"], updated_at: 1750000000 - i * 60,
				})),
			}),
		}));

		await page.goto(`http://localhost:${PORT}/dontminion`, { waitUntil: "networkidle" });
		await page.waitForSelector(".dm", { timeout: 25_000 }).catch(() => {});
		const rows = () => page.locator(".lby-col-history .lby-card").count();
		await page.waitForFunction(
			() => document.querySelectorAll(".lby-col-history .lby-card").length > 0,
			null, { timeout: 20_000 }).catch(() => {});
		const first = await rows();
		check("History shows the first page only, not every finished game",
			first === 10, JSON.stringify({ first, of: TOTAL }));

		// scrolling the end of the list into view reveals the next page
		await page.locator(".lby-col-history .lby-more").scrollIntoViewIfNeeded()
			.catch(() => {});
		await sleep(500);
		const second = await rows();
		check("...and reaching the end of it reveals another page",
			second > first && second % 10 === 0,
			JSON.stringify({ first, second }));

		// keep going until it stops growing — it must stop at HISTORY_MAX, never
		// at the 55 the server sent
		let last = second;
		for (let i = 0; i < 12; i++) {
			const sentinel = page.locator(".lby-col-history .lby-more");
			if (await sentinel.count() === 0) break;
			await sentinel.scrollIntoViewIfNeeded().catch(() => {});
			await sleep(350);
			const n = await rows();
			if (n === last) break;
			last = n;
		}
		check("...and stops at HISTORY_MAX rather than at everything the server sent",
			last === 50 && TOTAL > 50, JSON.stringify({ last, sent: TOTAL }));
		check("no page errors paging through History", errors.length === 0,
			errors[0] || "");
		await ctx.close();
	}

	// An Adventures-only board deals at least one Event on 99.65% of seeds
	// (measured over 20k), so this asserts the BICONDITIONAL rather than
	// demanding one: a face implies a well-formed row, and no face implies no
	// row. Never deal-dependent, and it exercises the real render path on all
	// but ~1 run in 300 — the same shape as the body-text truncation check.
	{
		const ctx = await browser.newContext();
		await ctx.addInitScript(() => localStorage.setItem("spender_user",
			JSON.stringify({ id: "adv-harness", name: "Adv", guest: true })));
		const page = await ctx.newPage();
		const errors = [];
		page.on("pageerror", (e) => errors.push(String(e)));
		const check = (name, cond, detail = "") => {
			if (cond) console.log(`  OK   ${name}`);
			else { shell.push(name); console.log(`  FAIL ${name}  ${detail}`); }
		};

		await page.goto(`http://localhost:${PORT}/dontminion`, { waitUntil: "networkidle" });
		await page.waitForSelector(".dm", { timeout: 25_000 }).catch(() => {});
		await page.getByRole("button", { name: /new game|create/i }).first()
			.click({ timeout: 15_000 }).catch(() => {});
		await page.waitForSelector(".dm-checks", { timeout: 15_000 }).catch(() => {});
		// Adventures ON, Base Set OFF — an Adventures-only pool, so the Event
		// deal is over the set that actually has Events.
		for (const label of ["Adventures", "Base Set"]) {
			await page.locator(".dm-checks .dm-check", { hasText: label }).first()
				.click({ timeout: 10_000 }).catch(() => {});
		}
		const picked = await page.evaluate(() =>
			[...document.querySelectorAll(".dm-checks .dm-check-on")].map((b) => b.textContent.trim()));
		check("the Adventures expansion is selectable",
			picked.length === 1 && /Adventures/.test(picked[0]), JSON.stringify(picked));
		await page.locator(".cm-create").click({ timeout: 15_000 }).catch(() => {});
		const dealt = await page.waitForSelector(".dm-supply .dm-card", { timeout: 30_000 })
			.then(() => true).catch(() => false);
		check("an Adventures game deals a board", dealt);

		if (dealt) {
			const ls = await page.evaluate(() => {
				const row = document.querySelector(".dm-lscape-row");
				const faces = [...document.querySelectorAll(".dm-lscape")];
				const supply = document.querySelector(".dm-supply");
				return {
					rows: document.querySelectorAll(".dm-lscape-row").length,
					firstChildIsRow: !!row && supply.firstElementChild === row,
					insideBoard: !!row
						&& row.getBoundingClientRect().width <= supply.getBoundingClientRect().width + 1,
					faces: faces.map((f) => ({
						name: f.querySelector(".dm-ls-name")?.textContent || "",
						cost: f.querySelector(".dm-ls-cost")?.textContent || "",
						kind: f.querySelector(".dm-ls-kind")?.textContent || "",
						text: (f.querySelector(".dm-ls-text")?.textContent || "").length,
						overflows: f.scrollHeight > f.clientHeight + 1,
					})),
				};
			});
			const wellFormed = ls.faces.length > 0
				&& ls.rows === 1 && ls.firstChildIsRow && ls.insideBoard
				&& ls.faces.every((f) => f.name && /^\$\d+$/.test(f.cost) && f.kind
					&& f.text > 0 && !f.overflows);
			check("an Event renders in the landscape row, above the Supply and inside it",
				ls.faces.length === 0 ? ls.rows === 0 : wellFormed, JSON.stringify(ls));
		}
		check("no page errors on an Adventures board", errors.length === 0,
			errors[0]?.slice(0, 160) || "");
		await ctx.close();
	}

	// ── a REAL Empires board (ph. 8): landmarks and Debt prices ───────────────
	// Two render paths arrive with this set and neither existed before it:
	//   * a LANDMARK in the landscape row — a landscape that is never bought, so
	//     it prints NO price at all and shows its VP store instead. The
	//     Adventures block above asserts every face carries a `$N`, which is
	//     exactly the assumption a landmark breaks;
	//   * a DEBT price on a Supply face — an orange hexagon, and for the four
	//     {ND} Actions it REPLACES the coin cost rather than sitting beside it
	//     (Engineer is {4D}, not "$0 + 4D"), so a board full of them must not
	//     render a row of misleading zeroes.
	// Both are asserted as well-formedness biconditionals rather than demanding
	// a particular deal, the same shape the rest of this file uses.
	{
		const ctx = await browser.newContext();
		await ctx.addInitScript(() => localStorage.setItem("spender_user",
			JSON.stringify({ id: "emp-harness", name: "Emp", guest: true })));
		const page = await ctx.newPage();
		const errors = [];
		page.on("pageerror", (e) => errors.push(String(e)));
		const check = (name, cond, detail = "") => {
			if (cond) console.log(`  OK   ${name}`);
			else { shell.push(name); console.log(`  FAIL ${name}  ${detail}`); }
		};

		await page.goto(`http://localhost:${PORT}/dontminion`, { waitUntil: "networkidle" });
		await page.waitForSelector(".dm", { timeout: 25_000 }).catch(() => {});
		await page.getByRole("button", { name: /new game|create/i }).first()
			.click({ timeout: 15_000 }).catch(() => {});
		await page.waitForSelector(".dm-checks", { timeout: 15_000 }).catch(() => {});
		for (const label of ["Empires", "Base Set"]) {
			await page.locator(".dm-checks .dm-check", { hasText: label }).first()
				.click({ timeout: 10_000 }).catch(() => {});
		}
		const picked = await page.evaluate(() =>
			[...document.querySelectorAll(".dm-checks .dm-check-on")].map((b) => b.textContent.trim()));
		check("the Empires expansion is selectable",
			picked.length === 1 && /Empires/.test(picked[0]), JSON.stringify(picked));
		await page.locator(".cm-create").click({ timeout: 15_000 }).catch(() => {});
		const dealt = await page.waitForSelector(".dm-supply .dm-card", { timeout: 30_000 })
			.then(() => true).catch(() => false);
		check("an Empires game deals a board", dealt);

		if (dealt) {
			const board = await page.evaluate(() => {
				const faces = [...document.querySelectorAll(".dm-lscape")].map((f) => ({
					name: f.querySelector(".dm-ls-name")?.textContent || "",
					kind: f.querySelector(".dm-ls-kind")?.textContent || "",
					cost: f.querySelector(".dm-ls-cost")?.textContent || "",
					vp: f.querySelector(".dm-ls-vp")?.textContent || "",
					text: (f.querySelector(".dm-ls-text")?.textContent || "").length,
					overflows: f.scrollHeight > f.clientHeight + 1,
				}));
				const debts = [...document.querySelectorAll(".dm-supply .dm-card")]
					.filter((c) => c.querySelector(".dm-cost-d"))
					.map((c) => ({
						badge: c.querySelector(".dm-cost-d text")?.textContent || "",
						solo: !!c.querySelector(".dm-cost-d-solo"),
						coin: c.querySelector(".dm-cost")?.textContent || "",
					}));
				return { rows: document.querySelectorAll(".dm-lscape-row").length, faces, debts };
			});
			// every face is well formed, and a landmark prints NO price
			const facesOk = board.faces.every((f) =>
				f.name && f.kind && f.text > 0 && !f.overflows
				&& (f.kind === "landmark"
					? f.cost === ""
					: /^\$\d+( \+ \d+D)?$|^\d+D$/.test(f.cost)));
			check("a landmark renders with a VP store and no price at all",
				board.faces.length === 0
					? board.rows === 0
					: board.rows === 1 && facesOk,
				JSON.stringify(board.faces));
			// a Debt badge is a positive number, and a {ND} card shows NO coin
			check("a Debt-costed pile shows a Debt badge instead of a misleading $0",
				board.debts.every((d) => /^[1-9]\d*$/.test(d.badge)
					&& (d.solo ? d.coin === "" : d.coin !== "")),
				JSON.stringify(board.debts));
		}
		check("no page errors on an Empires board", errors.length === 0,
			errors[0]?.slice(0, 160) || "");
		await ctx.close();
	}

	// ── a REAL Renaissance board (ph. 9): PROJECTS and the Villagers mat ──────
	// Two more render paths this set adds, neither reachable before it:
	//   * a PROJECT in the landscape row. It prints a price like an Event but
	//     is bought ONCE and then permanent, marked by a per-player CUBE — so
	//     the row must render cube dots for owners and none for a fresh board.
	//     The Empires block above asserts a landmark prints no price; a project
	//     does print one, which is the other side of that biconditional.
	//   * the VILLAGERS counter in the resource bar, whose SPEND control is
	//     driven by the server's `spendable` (Villagers are Action-phase only)
	//     rather than by any client-side rule.
	// Written as well-formedness assertions rather than demanding a particular
	// deal, the same shape as the rest of this file.
	{
		const ctx = await browser.newContext();
		await ctx.addInitScript(() => localStorage.setItem("spender_user",
			JSON.stringify({ id: "ren-harness", name: "Ren", guest: true })));
		const page = await ctx.newPage();
		const errors = [];
		page.on("pageerror", (e) => errors.push(String(e)));
		const check = (name, cond, detail = "") => {
			if (cond) console.log(`  OK   ${name}`);
			else { shell.push(name); console.log(`  FAIL ${name}  ${detail}`); }
		};

		await page.goto(`http://localhost:${PORT}/dontminion`, { waitUntil: "networkidle" });
		await page.waitForSelector(".dm", { timeout: 25_000 }).catch(() => {});
		await page.getByRole("button", { name: /new game|create/i }).first()
			.click({ timeout: 15_000 }).catch(() => {});
		await page.waitForSelector(".dm-checks", { timeout: 15_000 }).catch(() => {});
		for (const label of ["Renaissance", "Base Set"]) {
			await page.locator(".dm-checks .dm-check", { hasText: label }).first()
				.click({ timeout: 10_000 }).catch(() => {});
		}
		const picked = await page.evaluate(() =>
			[...document.querySelectorAll(".dm-checks .dm-check-on")].map((b) => b.textContent.trim()));
		// the ph.-3 lesson: the picker used to map a literal list, so a shipped
		// set could be correct on the backend and unpickable in the UI
		check("the Renaissance expansion is selectable",
			picked.length === 1 && /Renaissance/.test(picked[0]), JSON.stringify(picked));
		await page.locator(".cm-create").click({ timeout: 15_000 }).catch(() => {});
		const dealt = await page.waitForSelector(".dm-supply .dm-card", { timeout: 30_000 })
			.then(() => true).catch(() => false);
		check("a Renaissance game deals a board", dealt);

		if (dealt) {
			const board = await page.evaluate(() => {
				const faces = [...document.querySelectorAll(".dm-lscape")].map((f) => ({
					name: f.querySelector(".dm-ls-name")?.textContent || "",
					kind: f.querySelector(".dm-ls-kind")?.textContent || "",
					cost: f.querySelector(".dm-ls-cost")?.textContent || "",
					cubes: f.querySelectorAll(".dm-cube").length,
					text: (f.querySelector(".dm-ls-text")?.textContent || "").length,
					overflows: f.scrollHeight > f.clientHeight + 1,
				}));
				return { rows: document.querySelectorAll(".dm-lscape-row").length, faces };
			});
			// a PROJECT renders like a purchasable landscape and, on a fresh
			// board, carries NO cube — nobody has bought one yet
			const projects = board.faces.filter((f) => f.kind === "project");
			check("a Project renders with a price, its text and no cube yet",
				board.faces.length === 0
					? board.rows === 0
					: board.rows === 1 && projects.every((f) =>
						f.name && f.text > 0 && !f.overflows
						&& /^\$\d+$/.test(f.cost) && f.cubes === 0),
				JSON.stringify(board.faces));
		}
		check("no page errors on a Renaissance board", errors.length === 0,
			errors[0]?.slice(0, 160) || "");
		await ctx.close();
	}

	// ── Offline vs-AI (Spender local play) ────────────────────────────────────
	// The first browser coverage of BOTH the offline driver and the client-WASM AI
	// path: /offline must boot with no backend ping, create a local game through the
	// wasm engine, and — with the network genuinely CUT (context.setOffline) — apply a
	// human move and get an AI reply from the worker-pool search. Then, back online
	// (the preview server is the asset origin; there's no SW on localhost to serve a
	// reload's assets), a reload must resume the save from IndexedDB.
	{
		const ctx = await browser.newContext();
		await ctx.addInitScript(() => localStorage.setItem("spender_user",
			JSON.stringify({ id: "offline-harness", name: "Offline", guest: true })));
		const page = await ctx.newPage();
		const errors = [];
		page.on("pageerror", (e) => errors.push(String(e)));
		// The search pool announces itself on the console once its workers have FETCHED and
		// compiled the wasm — the network can only be cut after that (see below).
		let poolReady = false;
		page.on("console", (m) => { if (/\[client-AI\].*ready/.test(m.text())) poolReady = true; });
		const check = (name, cond, detail = "") => {
			if (cond) console.log(`  OK   ${name}`);
			else { shell.push(name); console.log(`  FAIL ${name}  ${detail}`); }
		};

		await page.goto(`http://localhost:${PORT}/offline`, { waitUntil: "load" });
		const hubUp = await page.waitForSelector(".offline-panel", { timeout: 20_000 })
			.then(() => true).catch(() => false);
		check("the Local-vs-AI hub renders", hubUp);

		if (hubUp) {
			// S searches its full 4.5s budget per move; that's the real serving shape.
			await page.locator(".cm-pill", { hasText: "Steve" }).click({ timeout: 10_000 }).catch(() => {});
			await page.locator(".cm-create", { hasText: "Start Game" }).click({ timeout: 10_000 }).catch(() => {});
			const board = await page.waitForSelector(".gem-stack", { timeout: 20_000 })
				.then(() => true).catch(() => false);
			check("Start Game deals a local board", board);
			check("...at its /offline/<LOCALID> URL",
				/^\/offline\/LOCAL[A-Z0-9]+$/.test(new URL(page.url()).pathname),
				new URL(page.url()).pathname);

			// Cut the network only once the search pool has its wasm in memory — cutting
			// earlier races the pool's module fetches and hangs the AI's first search
			// (caught exactly that way; the AI can open the game when seats shuffle it
			// first). On a real device this window is covered by the SW precache.
			for (let i = 0; i < 40 && !poolReady; i++) await sleep(250);
			check("the search worker pool arms", poolReady);
			await ctx.setOffline(true);

			let takeable = 0;
			for (let i = 0; i < 60 && takeable < 3; i++) {   // the AI may move first — wait it out
				takeable = await page.locator(".gem-stack:not(.disabled)").count().catch(() => 0);
				if (takeable < 3) await sleep(500);
			}
			check("our turn arrives with the network OFF", takeable >= 3, `${takeable} takeable`);

			const colours = (await page.evaluate(() =>
				[...document.querySelectorAll(".gem-stack:not(.disabled)")]
					.map((e) => e.dataset.color).filter((c) => c && c !== "gold"))).slice(0, 3);
			for (const c of colours) {
				await page.locator(`.gem-stack[data-color="${c}"]`).click({ timeout: 10_000 }).catch(() => {});
			}
			const moved = await page.locator("button:visible", { hasText: /^Take/ }).first()
				.click({ timeout: 10_000 }).then(() => true).catch(() => false);
			check("a take-gems move applies through the local engine", moved);

			// The AI's reply is the whole point: the worker pool searches and the driver
			// applies — no server anywhere.
			let aiMoved = false;
			for (let i = 0; i < 50 && !aiMoved; i++) {
				aiMoved = (await page.locator(".gem-stack:not(.disabled)").count().catch(() => 0)) >= 3
					&& !(await page.locator(".ai-thinking").count().catch(() => 0));
				if (!aiMoved) await sleep(500);
			}
			check("the wasm AI replies while offline", aiMoved);

			// Assets need the network again for a reload (no SW on localhost) — the SAVE
			// must not: it comes from IndexedDB.
			await ctx.setOffline(false);
			await page.reload({ waitUntil: "load" }).catch(() => {});
			const resumed = await page.waitForSelector(".gem-stack", { timeout: 20_000 })
				.then(() => true).catch(() => false);
			check("a reload resumes the save from IndexedDB", resumed);

			await page.goBack().catch(() => {});
			const listed = await page.waitForSelector(".offline-save-row", { timeout: 10_000 })
				.then(() => true).catch(() => false);
			check("Back lands on the hub with the save listed", listed);
		}
		check("no page errors in offline play", errors.length === 0, errors[0]?.slice(0, 160) || "");
		await ctx.close();
	}

	// ── Oddtrick's skat auction ───────────────────────────────────────────────
	// Skat mode is a room FLAG chosen in the create modal, which is exactly the
	// failure class this gate exists for: Dontminion's Renaissance set rendered
	// fine and could not be CREATED, because a list in main.py was stale. A
	// mounted /oddtrick screen says nothing about whether picking "Skat" deals a
	// skat game, so this drives the segment, the deal, and the first bid — the
	// value ladder is a middle panel that does not exist in classic mode at all.
	{
		const ctx = await browser.newContext();
		await ctx.addInitScript(() => localStorage.setItem("spender_user",
			JSON.stringify({ id: "skat-harness", name: "Skat", guest: true })));
		const page = await ctx.newPage();
		const errors = [];
		page.on("pageerror", (e) => errors.push(String(e)));
		const check = (name, cond, detail = "") => {
			if (cond) console.log(`  OK   ${name}`);
			else { shell.push(name); console.log(`  FAIL ${name}  ${detail}`); }
		};

		await page.goto(`http://localhost:${PORT}/oddtrick`, { waitUntil: "networkidle" });
		await page.waitForSelector(".odd", { timeout: 25_000 }).catch(() => {});
		await page.getByRole("button", { name: /new game|create/i }).first()
			.click({ timeout: 15_000 }).catch(() => {});
		await page.waitForSelector(".cm-seg", { timeout: 15_000 }).catch(() => {});
		await page.locator(".cm-seg .cm-seg-btn", { hasText: /^Skat$/ }).first()
			.click({ timeout: 10_000 }).catch(() => {});
		const picked = await page.evaluate(() =>
			[...document.querySelectorAll(".cm-seg .cm-seg-btn.sel")].map((b) => b.textContent.trim()));
		check("the skat auction is selectable in the create modal",
			picked.includes("Skat"), JSON.stringify(picked));

		await page.getByRole("button", { name: /^Bot · Normal$/ }).first()
			.click({ timeout: 15_000 }).catch(() => {});
		// A skat room deals immediately vs the bot, straight into the number
		// ladder — a grid that classic mode never renders.
		const ladder = await page.waitForSelector(".odd-valgrid button", { timeout: 25_000 })
			.then(() => true).catch(() => false);
		check("a skat room deals into the number ladder", ladder);

		if (ladder) {
			const rungs = await page.evaluate(() =>
				[...document.querySelectorAll(".odd-valgrid button")].map((b) => +b.textContent));
			check("the ladder is ascending and server-supplied, not a 1..12 level row",
				rungs.length > 12 && rungs.every((v, i) => i === 0 || v > rungs[i - 1]),
				JSON.stringify(rungs.slice(0, 8)));

			await page.locator(".odd-valgrid button").first().click().catch(() => {});
			// Selecting a number shows what it could BUY — the mode's whole
			// argument, and the one thing /catalog is fetched for.
			const clears = await page.waitForSelector(".odd-clears .odd-clear", { timeout: 10_000 })
				.then(() => true).catch(() => false);
			check("a selected number shows every game that clears it", clears);

			await page.getByRole("button", { name: /^Bid \d+$/ }).first()
				.click({ timeout: 10_000 }).catch(() => {});
			// The bot answers, and the round moves on — to its own bid, or to
			// the talon prompt if it passed. Either way the auction is NOT stuck.
			await sleep(2500);
			const moved = await page.evaluate(() => ({
				log: document.querySelectorAll(".odd-bidlog div").length,
				phase: !!document.querySelector(".odd-auction, .odd-result"),
			}));
			check("the bot answers a number bid", moved.log >= 2 && moved.phase,
				JSON.stringify(moved));
		}
		check("no page errors in the skat auction", errors.length === 0,
			errors[0]?.slice(0, 160) || "");
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
