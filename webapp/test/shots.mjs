/* Rag Tag: drive a real vs-bot game and screenshot every state worth LOOKING at.
 *
 * NOT A GATE. `npm run screens` decides whether the frontend ships; this exists
 * because that gate asserts structure and cannot tell you the health bar reads
 * as a slider, the art window is too dark for one fighter, or the same sentence
 * is on screen twice. It captures each phase of a whole round at three widths so
 * a person (or a reviewing agent) can judge the pixels.
 *
 * It deliberately does NOT boot anything: point it at a `vite dev` on 5173 and a
 * backend on 8000 that are already up, and an iteration costs seconds rather
 * than a full rebuild. Animations are allowed to settle rather than being
 * frozen, because a broken END state is exactly what a still frame should catch.
 *
 *   cd webapp && node test/shots.mjs <outDir> [--only=phone|tablet|desktop]
 */
import { chromium } from "playwright";
import { mkdirSync, rmSync } from "node:fs";
import path from "node:path";

const OUT = process.argv[2] || "shots";
const only = (process.argv.find((a) => a.startsWith("--only=")) || "").split("=")[1];
const PORT = 5173;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const VIEWS = [
  { key: "phone", width: 390, height: 844, dsf: 2 },
  { key: "tablet", width: 834, height: 1112, dsf: 2 },
  { key: "desktop", width: 1440, height: 900, dsf: 1 },
].filter((v) => !only || v.key === only);

rmSync(OUT, { recursive: true, force: true });
mkdirSync(OUT, { recursive: true });

async function launch() {
  const exe = process.env.PLAYWRIGHT_CHROMIUM_PATH;
  if (exe) return await chromium.launch({ executablePath: exe });
  try { return await chromium.launch(); }
  catch { return await chromium.launch({ channel: "msedge" }); }
}

const browser = await launch();
const problems = [];

for (const v of VIEWS) {
  const ctx = await browser.newContext({
    viewport: { width: v.width, height: v.height },
    deviceScaleFactor: v.dsf,
    // Animations settle before a shot; freezing them would hide a broken
    // end-state, which is exactly the class of bug a still frame should catch.
  });
  await ctx.addInitScript(() => localStorage.setItem("spender_user",
    JSON.stringify({ id: `shot-${Math.random().toString(36).slice(2, 8)}`, name: "Critic", guest: true })));
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error") errors.push(`console: ${m.text()}`); });

  const shot = async (name, opts = {}) => {
    await sleep(opts.settle ?? 900);
    await page.screenshot({ path: path.join(OUT, `${v.key}-${name}.png`), fullPage: opts.full !== false });
    process.stdout.write(`  ${v.key}/${name}\n`);
  };
  const has = async (sel) => (await page.locator(sel).count()) > 0;
  const clickIf = async (sel) => {
    if (await has(sel)) { await page.locator(sel).first().click().catch(() => {}); return true; }
    return false;
  };

  console.log(`\n== ${v.key} (${v.width}x${v.height}) ==`);
  await page.goto(`http://localhost:${PORT}/ragtag`, { waitUntil: "networkidle" });
  await page.waitForSelector(".lby-create-row", { timeout: 30_000 }).catch(() => {});
  await shot("01-lobby");

  await clickIf(".lby-cta");
  await page.waitForSelector(".cm-create", { timeout: 15_000 }).catch(() => {});
  await shot("02-create-modal", { full: false });
  await clickIf(".cm-create");

  // Draft, twice.
  for (let round = 0; round < 2; round++) {
    await page.waitForSelector(".rt-prompt .rt-pick", { timeout: 30_000 }).catch(() => {});
    if (!(await has(".rt-prompt .rt-pick"))) break;
    if (round === 0) await shot("03-draft");
    else await shot("04-draft-second");
    await page.locator(".rt-prompt .rt-pick").first().click().catch(() => {});
    await sleep(900);
  }

  // A Fey Folk Character prompt can come before "who leads"; same shape.
  for (let i = 0; i < 3; i++) {
    const hd = await page.locator(".rt-prompt h3").first().innerText().catch(() => "");
    if (/Character/i.test(hd)) {
      await shot("05-character");
      await page.locator(".rt-prompt .rt-pick").first().click().catch(() => {});
      await sleep(800);
    } else break;
  }

  await page.waitForSelector(".rt-prompt .rt-pick", { timeout: 25_000 }).catch(() => {});
  const leadHd = await page.locator(".rt-prompt h3").first().innerText().catch(() => "");
  if (/leads/i.test(leadHd)) {
    await shot("06-who-leads");
    await page.locator(".rt-prompt .rt-pick").first().click().catch(() => {});
  } else problems.push(`${v.key}: expected the who-leads prompt, saw "${leadHd}"`);

  // The fight. Manual stepping is the point, so shoot the first turn, step,
  // and shoot again.
  await page.waitForSelector(".rt-stage", { timeout: 30_000 }).catch(() => {});
  await shot("07-fight-turn1");

  const goEnabled = await page.locator(".rt-ctl-go:not([disabled])").count();
  if (!goEnabled) problems.push(`${v.key}: "Next turn" was not clickable on turn 1`);
  await clickIf(".rt-ctl-go:not([disabled])");
  await shot("08-fight-turn2");

  // The detail modal, on a fighter and on a played card. Right-click is the
  // desktop half of the gesture; the touch half is a real timer (see
  // shared/gestures.js) and is covered by the screens gate, not here.
  await page.locator(".rt-fighter").first().click({ button: "right" }).catch(() => {});
  await shot("07b-info-fighter", { full: false });
  await page.keyboard.press("Escape").catch(() => {});
  await sleep(300);
  await page.locator(".rt-card").first().click({ button: "right" }).catch(() => {});
  await shot("07c-info-card", { full: false });
  await page.keyboard.press("Escape").catch(() => {});
  await sleep(300);

  // Straight to the end of the round.
  await clickIf(".rt-ctl:not([disabled]):has-text('To the end')");
  await sleep(700);
  await shot("09-fight-end");

  // BUILD!
  await page.waitForSelector(".rt-prompt h3", { timeout: 30_000 }).catch(() => {});
  const buildHd = await page.locator(".rt-prompt h3").first().innerText().catch(() => "");
  if (/Build/i.test(buildHd)) {
    await shot("10-build");
    await page.locator(".rt-prompt .rt-pick").first().click().catch(() => {});
    await shot("11-build-slots");
    await page.locator(".rt-slots .rt-drop").first().click().catch(() => {});
    await clickIf(".rt-go:not([disabled])");
  } else problems.push(`${v.key}: expected the BUILD prompt, saw "${buildHd}"`);

  // Round two, so the log has a finished round above the live one.
  await page.waitForSelector(".rt-stage", { timeout: 30_000 }).catch(() => {});
  await sleep(1200);
  await shot("12-round2");
  // Step a couple of turns so the log fills out.
  for (let i = 0; i < 3; i++) { await clickIf(".rt-ctl-go:not([disabled])"); await sleep(450); }
  await shot("13-round2-log");

  if (errors.length) problems.push(`${v.key}: page errors -> ${errors.slice(0, 3).join(" | ")}`);
  await ctx.close();
}

await browser.close();
console.log("\n" + (problems.length ? "PROBLEMS:\n  " + problems.join("\n  ") : "no functional problems"));
