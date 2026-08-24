/* Tiny promise-wrapped IndexedDB store for OFFLINE games — the app's first and only
 * IndexedDB use (everything else is localStorage). IndexedDB because offline saves are
 * per-move full game states: too big to serialize into localStorage on every move, and
 * the async API keeps the write off the interaction path.
 *
 * One DB (`forrest-offline`), one object store (`games`, keyPath `id`). Records are
 * whole saved-game objects owned by each game's offline driver (Spender's:
 * games/spender/offline.js) — this module knows nothing about their shape.
 *
 * Every call swallows platform failures into safe defaults (list → [], get → null,
 * put/delete → false): private mode or a storage-evicted iOS PWA should degrade to
 * "no saved games", never crash the hub.
 */

const DB_NAME = "forrest-offline";
const STORE = "games";

let _dbP = null;

function openDb() {
	if (_dbP) return _dbP;
	_dbP = new Promise((resolve, reject) => {
		try {
			const req = indexedDB.open(DB_NAME, 1);
			req.onupgradeneeded = () => {
				if (!req.result.objectStoreNames.contains(STORE)) {
					req.result.createObjectStore(STORE, { keyPath: "id" });
				}
			};
			req.onsuccess = () => resolve(req.result);
			req.onerror = () => reject(req.error);
		} catch (e) { reject(e); }
	});
	// a failed open must not poison every later call with the same rejected promise
	_dbP.catch(() => { _dbP = null; });
	return _dbP;
}

function tx(db, mode, fn) {
	return new Promise((resolve, reject) => {
		const t = db.transaction(STORE, mode);
		const store = t.objectStore(STORE);
		const req = fn(store);
		t.oncomplete = () => resolve(req?.result);
		t.onerror = () => reject(t.error);
		t.onabort = () => reject(t.error);
	});
}

export async function dbPut(record) {
	try { await tx(await openDb(), "readwrite", (s) => s.put(record)); return true; }
	catch { return false; }
}

export async function dbGet(id) {
	try { return (await tx(await openDb(), "readonly", (s) => s.get(id))) || null; }
	catch { return null; }
}

export async function dbList() {
	try { return (await tx(await openDb(), "readonly", (s) => s.getAll())) || []; }
	catch { return []; }
}

export async function dbDelete(id) {
	try { await tx(await openDb(), "readwrite", (s) => s.delete(id)); return true; }
	catch { return false; }
}

/* Ask the browser to protect this origin's storage from eviction. Installed-PWA storage
 * is already exempt from Safari's 7-day script-storage cap, but asking is free and helps
 * the browser-tab case. Result intentionally ignored — nothing actionable on "no". */
export function requestPersistentStorage() {
	try { navigator.storage?.persist?.().catch(() => {}); } catch {}
}
