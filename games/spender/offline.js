/* Offline vs-AI game driver — the client-side stand-in for main.py's room server.
 *
 * In an offline game the BROWSER is authoritative: the saved game is the compact-state
 * JSON (the same "Dump" shape the search workers already consume), and every step is a
 * stateless JSON→JSON call into the Rust engine compiled into spender_core_bg.wasm
 * (new_game / legal_moves / apply / game_dict — see rust-cores/spender-core/src/wasm.rs).
 * The UI keeps rendering the incumbent game-dict shape; the wasm's game_dict_json emits
 * it with the SAME per-viewer blind-reserve redaction the server applies (parity-gated
 * by gamedict_parity.rs), so the game screen needs no offline-specific rendering.
 *
 * What main.py does that this must mirror (and where):
 *  - move legality: the UI's dict-move is matched against the engine's legal_moves list
 *    (movesEqual), exactly how the server validates an ai_move — never applied raw.
 *  - the move log: engine State carries no log; the record keeps a newest-first `moves`
 *    list (capped 500) like the server's game dict.
 *  - discard undo: the pre-action state is snapshotted before a human take/reserve and
 *    restored on `undo_discard`; kept in the record so undo survives a reload (the
 *    server keeps its snapshot in saved state for the same reason). Cleared once the
 *    turn completes. Always-snapshot is fine here — "snapshot" is keeping a string.
 *  - AI noble auto-pick: _run_ai_turn resolves the AI's noble choice server-side, so the
 *    search never sees a NOBLE-phase root online; mirror that by auto-applying the first
 *    pending noble for the AI (all nobles are 3 points — the choice is value-neutral).
 *  - AI discard routing: an over-cap AI take leaves the DISCARD-phase state pending with
 *    the AI to move; the caller re-dispatches the search on it (the defer_discard flow).
 *
 * The engine runs in its OWN module worker (same spender-worker.js the search pool
 * loads), created lazily and kept for the session: the hub needs engine calls before any
 * search pool exists, and the pool's lifecycle (torn down with roomData) is wrong for a
 * driver that outlives screens. One extra instance total; it idles during search.
 */

import { dbPut, dbGet, dbList, dbDelete, requestPersistentStorage } from "../../shared/offline-db.js";

export const OFFLINE_AI_PID = "offline_ai";
export const OFFLINE_ID_RE = /^LOCAL[A-Z0-9]{4,8}$/;
const LOG_CAP = 500;

// Compact-state phase constants (engine.rs): 0=PLAY 1=DISCARD 2=NOBLE 3=OVER.
const PH_DISCARD = 1, PH_NOBLE = 2, PH_OVER = 3;

const newLocalId = () =>
	"LOCAL" + Array.from({ length: 6 }, () => "ABCDEFGHJKMNPQRSTUVWXYZ23456789"[Math.floor(Math.random() * 31)]).join("");

// Same structural comparison the puzzle path uses to match a UI move to a canonical one.
export const movesEqual = (a, b) => {
	if (!a || !b || a.type !== b.type) return false;
	if (a.type === "take_gems")
		return [...(a.colors || [])].sort().join(",") === [...(b.colors || [])].sort().join(",");
	if (a.type === "buy") return a.card_id === b.card_id;
	if (a.type === "reserve")
		return (a.card_id || null) === (b.card_id || null) && (a.deck_level || null) === (b.deck_level || null);
	if (a.type === "discard") return a.color === b.color;
	if (a.type === "pick_noble") return a.noble_id === b.noble_id;
	return JSON.stringify(a) === JSON.stringify(b);
};

// ─── The lazy engine worker ────────────────────────────────────────────────
let _engine = null;

function makeEngineWorker() {
	const url = `${import.meta.env.BASE_URL}wasm/spender-worker.js`;
	const w = new Worker(url, { type: "module" });
	const pending = new Map();
	let nextId = 1, readyRes;
	const ready = new Promise((r) => (readyRes = r));
	w.onmessage = (e) => {
		const d = e.data || {};
		if (d.ready !== undefined) { readyRes(!!d.ready); return; }
		const p = pending.get(d.id);
		if (p) { pending.delete(d.id); p(d); }
	};
	w.onerror = () => readyRes(false);
	return {
		async request(payload) {
			if (!(await ready)) throw new Error("the game engine failed to load — go online once to download it");
			const id = nextId++;
			const res = await new Promise((r) => { pending.set(id, r); w.postMessage({ ...payload, id }); });
			if (res.error) throw new Error(res.error);
			return res;
		},
	};
}

function engine(payload) {
	if (!_engine) _engine = makeEngineWorker();
	return _engine.request(payload);
}

// ─── Record helpers ────────────────────────────────────────────────────────

const aiSeatOf = (rec) => 1 - rec.mySeat;
export const offlinePids = (rec, myId) =>
	rec.mySeat === 0 ? [myId, OFFLINE_AI_PID] : [OFFLINE_AI_PID, myId];

async function save(rec) {
	rec.updated = Date.now();
	await dbPut(rec);
	return rec;
}

// ─── Public driver API ─────────────────────────────────────────────────────

export async function createOfflineGame({ aiVariant, winPoints }) {
	const seed = (Math.random() * 0x100000000) >>> 0;
	const { state } = await engine({ kind: "newGame", seed, winPoints });
	const rec = {
		id: newLocalId(),
		dump: state,
		mySeat: Math.random() < 0.5 ? 0 : 1,   // mirror the server's shuffled seat order
		aiVariant,
		winPoints,
		seed,
		moves: [],
		status: "playing",
		undo: null,
		created: Date.now(),
		updated: Date.now(),
	};
	await save(rec);
	requestPersistentStorage();
	return rec;
}

export const loadOfflineGame = (id) => dbGet(id);
export const deleteOfflineGame = (id) => dbDelete(id);

export async function listOfflineGames() {
	const all = await dbList();
	return all.sort((a, b) => (b.updated || 0) - (a.updated || 0));
}

/* Build the synthesized roomData the game screen renders — the offline analog of
 * mk_room_state. `game` is the wasm's viewer-redacted game dict plus the JS-side keys
 * the compact state doesn't carry (ai_player, the move log). `ai_search` rides along
 * whenever the AI is to move and the game isn't over — including a pending AI discard,
 * exactly like the online defer_discard flow (the dict phase stays "playing" there). */
export async function offlineRoomData(rec, myId, myName) {
	const pids = offlinePids(rec, myId);
	const { game: gameJson } = await engine({
		kind: "gameDict", state: rec.dump, pid0: pids[0], pid1: pids[1], viewer: rec.mySeat,
	});
	const game = { ...JSON.parse(gameJson), ai_player: OFFLINE_AI_PID, moves: rec.moves };
	const rd = {
		room_id: rec.id,
		players: { [myId]: myName || "You", [OFFLINE_AI_PID]: `AI (${rec.aiVariant})` },
		status: rec.status,
		ai_variant: rec.aiVariant,
		offline: true,
		game,
	};
	if (game.phase === "playing" && game.turn === OFFLINE_AI_PID) {
		rd.ai_search = {
			state: JSON.parse(rec.dump),
			seat: aiSeatOf(rec),
			sims: 4000,
			ply: rec.moves.length,
		};
	}
	return rd;
}

/* Validate + apply one dict-move for the side to move. `myId` labels the human's log
 * entries; `isAi` marks moves arriving from the search (no undo snapshot; stale/illegal
 * ones are dropped silently by the caller — the server treats a bad ai_move the same
 * way). Returns {ok, rec} or {ok:false, err}. */
export async function applyOfflineMove(rec, move, myId, { isAi = false } = {}) {
	if (rec.status === "over") return { ok: false, err: "game is over" };

	// undo_discard is not an engine action — it restores the pre-action snapshot,
	// mirroring main.py's pre_discard_snapshot flow.
	if (move?.type === "undo_discard") {
		if (!rec.undo) return { ok: false, err: "nothing to undo" };
		rec.dump = rec.undo.dump;
		rec.moves = rec.undo.moves;
		rec.undo = null;
		return { ok: true, rec: await save(rec) };
	}

	// The engine applies for its side-to-move; make sure the CALLER's idea of the mover
	// matches (a stale AI submission after the human already moved must be dropped, not
	// applied as the human's move).
	const turnSeat = JSON.parse(rec.dump).turn;
	if ((turnSeat === aiSeatOf(rec)) !== isAi) return { ok: false, err: "not your turn" };

	const { moves: legalJson } = await engine({ kind: "legalMoves", state: rec.dump });
	const hit = JSON.parse(legalJson).find((m) => movesEqual(m.move, move));
	if (!hit) return { ok: false, err: "illegal move" };

	// Snapshot before a human PRIMARY action that can overfill; undo_discard restores it.
	if (!isAi && (move.type === "take_gems" || move.type === "reserve")) {
		rec.undo = { dump: rec.dump, moves: [...rec.moves] };
	}

	const { state: after } = await engine({ kind: "apply", state: rec.dump, action: hit.action });
	rec.dump = after;
	rec.moves = [{ ...hit.move, pid: isAi ? OFFLINE_AI_PID : myId }, ...rec.moves].slice(0, LOG_CAP);

	let s = JSON.parse(after);

	// AI noble auto-pick (the _run_ai_turn behavior — the search never sees NOBLE roots).
	while (s.phase === PH_NOBLE && s.turn === aiSeatOf(rec)) {
		const { moves: lm } = await engine({ kind: "legalMoves", state: rec.dump });
		const pick = JSON.parse(lm).find((m) => m.move.type === "pick_noble");
		if (!pick) break;
		const { state: st2 } = await engine({ kind: "apply", state: rec.dump, action: pick.action });
		rec.dump = st2;
		rec.moves = [{ ...pick.move, pid: OFFLINE_AI_PID }, ...rec.moves].slice(0, LOG_CAP);
		s = JSON.parse(st2);
	}

	// The undo window closes when the human's turn actually completes (no pending discard
	// left on their seat). AI moves never touch the snapshot.
	if (!isAi && !(s.phase === PH_DISCARD && s.turn === rec.mySeat)) rec.undo = null;

	if (s.phase === PH_OVER) rec.status = "over";
	return { ok: true, rec: await save(rec) };
}
