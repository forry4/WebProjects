/**
 * The card the pooled sums choose: highest total, ties to the earliest legal
 * move.
 *
 * It lives here rather than in the worker's JavaScript so that the tie-break is
 * stated in one place — `PimcBot::pick` keeps the first of equal-valued moves
 * for exactly the same reason a strict `>` does, and a pooled search that broke
 * ties differently would not be the same bot.
 * @param {string} pooled_json
 * @returns {number}
 */
export function odd_best_card(pooled_json) {
    const ptr0 = passStringToWasm0(pooled_json, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
    const len0 = WASM_VECTOR_LEN;
    const ret = wasm.odd_best_card(ptr0, len0);
    return ret;
}

/**
 * Price every auction option the server offered, over `k` sampled deals.
 *
 * `{"sums":[f64...],"worlds":k}`, indexed by the SERVER'S option list — which
 * is the pooling key across workers and the answer the client sends back, so
 * nothing here re-derives it. Signed for the seat being asked, so higher is
 * better for them whether they are the one declaring (a bid, a declaration) or
 * the one deciding whether to double it (Kontra).
 *
 * An empty option list is not an error: it is a seat whose only legal action
 * is to pass, and the caller reads that off the same emptiness.
 *
 * THE EXPERT TIER RIDES IN ON THE SAME CALL. When the request carries an
 * `auction.search` block, each option is valued by MINIMAX over the auction
 * tree (`auc_search`) instead of by "what does this contract pay me". The
 * protocol does not move at all — same indices, same summing across the pool,
 * same move handed back — so only what the numbers MEAN changes, and a wasm
 * older than the server (or a malformed block) simply prices the Hard way.
 * @param {string} request_json
 * @param {number} k
 * @param {number} seed
 * @returns {string}
 */
export function odd_pick_bid(request_json, k, seed) {
    let deferred2_0;
    let deferred2_1;
    try {
        const ptr0 = passStringToWasm0(request_json, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ret = wasm.odd_pick_bid(ptr0, len0, k, seed);
        deferred2_0 = ret[0];
        deferred2_1 = ret[1];
        return getStringFromWasm0(ret[0], ret[1]);
    } finally {
        wasm.__wbindgen_free(deferred2_0, deferred2_1, 1);
    }
}

/**
 * Solve `k` sampled worlds and return the per-move value sums.
 *
 * `view_json` is the armed request: `{"view": ..., "payoff": ...}`. A bare
 * view is accepted too and searched on trick POINTS, which is what this did
 * before the payoff terms existed.
 *
 * `{"moves":[card...],"sum":[f64...],"worlds":k}` — `moves` is `State::legal`
 * in its own order and `sum[i]` is the total, over the sampled worlds, of the
 * exact double-dummy value of playing `moves[i]`, signed so that HIGHER is
 * better for the seat to move. Both arrays are additive across workers.
 *
 * A position with one legal card returns it with a zero sum and no search: the
 * answer cannot depend on it, and a full solve to learn that is the single
 * most wasteful thing this could do (mandatory follow-suit makes it common).
 * @param {string} view_json
 * @param {number} k
 * @param {number} seed
 * @returns {string}
 */
export function odd_pick_card(view_json, k, seed) {
    let deferred2_0;
    let deferred2_1;
    try {
        const ptr0 = passStringToWasm0(view_json, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ret = wasm.odd_pick_card(ptr0, len0, k, seed);
        deferred2_0 = ret[0];
        deferred2_1 = ret[1];
        return getStringFromWasm0(ret[0], ret[1]);
    } finally {
        wasm.__wbindgen_free(deferred2_0, deferred2_1, 1);
    }
}

/**
 * The constant-sum pool, so the client can label a value without hardcoding a
 * rule the `odd-positive` feature is allowed to change.
 *
 * The CLASSIC pool -- minor mode's is -1, and a client that needs a per-mode
 * pool reads it from the server's `/catalog` (`pools`), which is authoritative
 * the way this constant cannot be.
 * @returns {number}
 */
export function odd_pool() {
    const ret = wasm.odd_pool();
    return ret;
}

/**
 * THE ROUND REVIEW: what the card play was worth to a perfect declarer.
 *
 * `{"deal": {...}, "payoff": {...}}` -> `{"value": i32}`, the exact
 * double-dummy payoff of the round from the START of trick 1, signed for the
 * DECLARER — the same convention `solve_root_contract` uses, and the same one
 * `payoff` itself is written in.
 *
 * WHY THIS IS NOT `odd_pick_card` WITH A FULLY-SPECIFIED VIEW. That is the
 * obvious implementation and it cannot work: a view carries a POOL of cards
 * the seat cannot place and the searcher samples worlds from it, so even a
 * payload naming every card gets reshuffled — and the wire's partition check
 * rejects the payload first anyway (see `deal_from_json`). A review has no
 * uncertainty left in it by construction: the round is over and every card has
 * been revealed, so this solves the ONE true deal exactly rather than
 * averaging over sampled ones. It is the cheapest search this crate does for
 * the same reason — one solve, no determinization, no pooling.
 *
 * So there is nothing to aggregate and no seed: two callers handed the same
 * deal get the same number, which is what makes it safe to show a player as a
 * fact about their round rather than as a bot's opinion.
 * @param {string} request_json
 * @returns {string}
 */
export function odd_review(request_json) {
    let deferred2_0;
    let deferred2_1;
    try {
        const ptr0 = passStringToWasm0(request_json, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ret = wasm.odd_review(ptr0, len0);
        deferred2_0 = ret[0];
        deferred2_1 = ret[1];
        return getStringFromWasm0(ret[0], ret[1]);
    } finally {
        wasm.__wbindgen_free(deferred2_0, deferred2_1, 1);
    }
}

/**
 * The wire vintage this artifact speaks. 2 = understands `even_val` /
 * `even` (minor mode's runtime trick value, 2026-08-09); 3 = understands
 * `card_pts` / `cards` (skat mode's card scoring, same day); 4 = understands
 * `must_head` / `head` (skat's must-head-the-trick rule, 2026-08-10).
 *
 * RUNG 4 IS A LEGALITY RUNG, and that is a harder failure than 2 and 3 were.
 * An artifact that misses a SCORING field returns legal-but-misvalued moves;
 * one that misses this returns moves the room simply refuses, which
 * `_validated_bot_move` drops on the floor -- so the tier answers nothing and
 * the room plays the server bot at full speed while still saying Hard.
 *
 * THE WORKER PROBES THIS EXPORT before searching a minor or card-scored
 * payload: an older wasm would silently read the view WITHOUT the field and
 * return legal-but-wrong-game moves with nothing red anywhere -- the exact
 * failure shape the `shown` rewrite already paid for. The probe (absence of
 * the export, or a value below what the payload needs) turns "stale artifact
 * in that room" into the ordinary per-decision fallback to the server bot.
 * @returns {number}
 */
export function odd_wire() {
    const ret = wasm.odd_wire();
    return ret;
}
function __wbg_get_imports() {
    const import0 = {
        __proto__: null,
        __wbindgen_init_externref_table: function() {
            const table = wasm.__wbindgen_externrefs;
            const offset = table.grow(4);
            table.set(0, undefined);
            table.set(offset + 0, undefined);
            table.set(offset + 1, null);
            table.set(offset + 2, true);
            table.set(offset + 3, false);
        },
    };
    return {
        __proto__: null,
        "./dissonance_bg.js": import0,
    };
}

function getStringFromWasm0(ptr, len) {
    return decodeText(ptr >>> 0, len);
}

let cachedUint8ArrayMemory0 = null;
function getUint8ArrayMemory0() {
    if (cachedUint8ArrayMemory0 === null || cachedUint8ArrayMemory0.byteLength === 0) {
        cachedUint8ArrayMemory0 = new Uint8Array(wasm.memory.buffer);
    }
    return cachedUint8ArrayMemory0;
}

function passStringToWasm0(arg, malloc, realloc) {
    if (realloc === undefined) {
        const buf = cachedTextEncoder.encode(arg);
        const ptr = malloc(buf.length, 1) >>> 0;
        getUint8ArrayMemory0().subarray(ptr, ptr + buf.length).set(buf);
        WASM_VECTOR_LEN = buf.length;
        return ptr;
    }

    let len = arg.length;
    let ptr = malloc(len, 1) >>> 0;

    const mem = getUint8ArrayMemory0();

    let offset = 0;

    for (; offset < len; offset++) {
        const code = arg.charCodeAt(offset);
        if (code > 0x7F) break;
        mem[ptr + offset] = code;
    }
    if (offset !== len) {
        if (offset !== 0) {
            arg = arg.slice(offset);
        }
        ptr = realloc(ptr, len, len = offset + arg.length * 3, 1) >>> 0;
        const view = getUint8ArrayMemory0().subarray(ptr + offset, ptr + len);
        const ret = cachedTextEncoder.encodeInto(arg, view);

        offset += ret.written;
        ptr = realloc(ptr, len, offset, 1) >>> 0;
    }

    WASM_VECTOR_LEN = offset;
    return ptr;
}

let cachedTextDecoder = new TextDecoder('utf-8', { ignoreBOM: true, fatal: true });
cachedTextDecoder.decode();
const MAX_SAFARI_DECODE_BYTES = 2146435072;
let numBytesDecoded = 0;
function decodeText(ptr, len) {
    numBytesDecoded += len;
    if (numBytesDecoded >= MAX_SAFARI_DECODE_BYTES) {
        cachedTextDecoder = new TextDecoder('utf-8', { ignoreBOM: true, fatal: true });
        cachedTextDecoder.decode();
        numBytesDecoded = len;
    }
    return cachedTextDecoder.decode(getUint8ArrayMemory0().subarray(ptr, ptr + len));
}

const cachedTextEncoder = new TextEncoder();

if (!('encodeInto' in cachedTextEncoder)) {
    cachedTextEncoder.encodeInto = function (arg, view) {
        const buf = cachedTextEncoder.encode(arg);
        view.set(buf);
        return {
            read: arg.length,
            written: buf.length
        };
    };
}

let WASM_VECTOR_LEN = 0;

let wasmModule, wasmInstance, wasm;
function __wbg_finalize_init(instance, module) {
    wasmInstance = instance;
    wasm = instance.exports;
    wasmModule = module;
    cachedUint8ArrayMemory0 = null;
    wasm.__wbindgen_start();
    return wasm;
}

async function __wbg_load(module, imports) {
    if (typeof Response === 'function' && module instanceof Response) {
        if (!module.ok) {
            throw new Error(`failed to fetch Wasm: ${module.status} ${module.statusText} fetching '${module.url}'`);
        }

        if (typeof WebAssembly.instantiateStreaming === 'function') {
            try {
                return await WebAssembly.instantiateStreaming(module, imports);
            } catch (e) {
                const validResponse = expectedResponseType(module.type);

                if (validResponse && module.headers.get('Content-Type') !== 'application/wasm') {
                    console.warn("`WebAssembly.instantiateStreaming` failed because your server does not serve Wasm with `application/wasm` MIME type. Falling back to `WebAssembly.instantiate` which is slower. Original error:\n", e);

                } else { throw e; }
            }
        }

        const bytes = await module.arrayBuffer();
        return await WebAssembly.instantiate(bytes, imports);
    } else {
        const instance = await WebAssembly.instantiate(module, imports);

        if (instance instanceof WebAssembly.Instance) {
            return { instance, module };
        } else {
            return instance;
        }
    }

    function expectedResponseType(type) {
        switch (type) {
            case 'basic': case 'cors': case 'default': return true;
        }
        return false;
    }
}

function initSync(module) {
    if (wasm !== undefined) return wasm;


    if (module !== undefined) {
        if (Object.getPrototypeOf(module) === Object.prototype) {
            ({module} = module)
        } else {
            console.warn('using deprecated parameters for `initSync()`; pass a single object instead')
        }
    }

    const imports = __wbg_get_imports();
    if (!(module instanceof WebAssembly.Module)) {
        module = new WebAssembly.Module(module);
    }
    const instance = new WebAssembly.Instance(module, imports);
    return __wbg_finalize_init(instance, module);
}

async function __wbg_init(module_or_path) {
    if (wasm !== undefined) return wasm;


    if (module_or_path !== undefined) {
        if (Object.getPrototypeOf(module_or_path) === Object.prototype) {
            ({module_or_path} = module_or_path)
        } else {
            console.warn('using deprecated parameters for the initialization function; pass a single object instead')
        }
    }

    if (module_or_path === undefined) {
        module_or_path = new URL('dissonance_bg.wasm', import.meta.url);
    }
    const imports = __wbg_get_imports();

    if (typeof module_or_path === 'string' || (typeof Request === 'function' && module_or_path instanceof Request) || (typeof URL === 'function' && module_or_path instanceof URL)) {
        module_or_path = fetch(module_or_path);
    }

    const { instance, module } = await __wbg_load(await module_or_path, imports);

    return __wbg_finalize_init(instance, module);
}

export { initSync, __wbg_init as default };
