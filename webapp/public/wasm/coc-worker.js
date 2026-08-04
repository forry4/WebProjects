// Castles of Crimson Hard/Expert-tier search worker (ROOT-PARALLEL). Loaded as a MODULE worker;
// the wasm-pack (--target web) glue + .wasm sit beside this file. One of N identical workers —
// the main thread fans a seeded search of the CURRENT MICRO DECISION to each, SUMS their root
// visit vectors, argmaxes, appends the action to the shared prefix, and repeats until the
// prefix forms a complete engine move (stepInfo boundary), then asks one worker to convert the
// chain to the compact dict-move JSON the server's ai_move handler accepts.
//
// The PV model is NOT embedded in the wasm: this worker fetches a model bin (compact f32 blob,
// ~2.6MB, browser-cached) once at init — a model upgrade is a file replace, no rebuild. WHICH
// bin comes from the worker URL's ?model= query (the tier's model): coc_pv_model.bin (Expert,
// the default) or coc_pv_model_hard.bin (Hard, the previous champion net).
//
// Protocol (main -> worker):
//   { id, kind:"searchCoC", state, prefix, mode, budget, maxSims, seed } -> { id, visits:[102 ints] }
//   { id, kind:"stepInfo",  state, prefix }                              -> { id, info:{over,boundary,actor,forced,legal} }
//   { id, kind:"chainMove", state, prefix }                              -> { id, move }   (compact dict-move JSON string)
//   ── offline driver (engine calls on the SAVE envelope; JSON strings in/out) ──
//   { id, kind:"newGame",  board0, board1, seed }             -> { id, save }
//   { id, kind:"legal",    save }                             -> { id, legal }  ({actor,moves} JSON)
//   { id, kind:"apply",    save, move, seat, pid0, pid1 }     -> { id, save, events }
//   { id, kind:"gameDict", save, pid0, pid1, name0, name1 }   -> { id, dict }   ({game,final_scores} JSON)
//   { id, kind:"proj",     save }                             -> { id, proj }   (redacted ai_search.state)
// Lifecycle: { ready:true } once wasm + model load, or { ready:false, error } if either fails
//   (the main thread drops this worker; if none are ready it never announces client_ai_ready
//   and the server computes the bot turn — the pre-existing hard path).
//   ?engine=1 in the worker URL SKIPS the model fetch entirely: the offline driver's
//   engine worker needs none of it (search stays in the pool workers, which DO load a
//   model), and skipping keeps engine calls working offline even if no model is cached.

// Namespace import so a cached OLD glue (without newer exports) still loads —
// newer entries are feature-detected at call time instead of breaking the import.
import init, * as coc from "./coc_core.js";
const { coc_init_model, coc_step_info, coc_search_timed, coc_chain_move } = coc;

let readyResolve;
const readyP = new Promise((res) => (readyResolve = res));

(async () => {
  try {
    await init();
    const params = new URL(import.meta.url).searchParams;
    if (params.get("engine") !== "1") {
      const wanted = params.get("model") || "coc_pv_model.bin";
      // whitelist so a crafted query can never fetch an arbitrary URL
      const model = wanted === "coc_pv_model_hard.bin" ? wanted : "coc_pv_model.bin";
      const resp = await fetch(new URL(`./${model}`, import.meta.url));
      if (!resp.ok) throw new Error("model fetch " + resp.status);
      const bytes = new Uint8Array(await resp.arrayBuffer());
      if (!coc_init_model(bytes)) throw new Error("model parse failed");
    }
    readyResolve(true);
    self.postMessage({ ready: true });
  } catch (err) {
    readyResolve(false);
    self.postMessage({ ready: false, error: String(err) });
  }
})();

// Engine-call results are `{"error":...}` JSON on bad input; surface those as
// protocol-level errors so the driver has ONE failure path.
const engineResult = (key, json) => {
  if (typeof json === "string" && json.startsWith('{"error"')) {
    return { error: JSON.parse(json).error };
  }
  return { [key]: json };
};
const need = (fn) => {
  if (typeof fn !== "function") throw new Error("stale wasm: no offline engine");
  return fn;
};

self.onmessage = async (e) => {
  const msg = e.data || {};
  if (!msg.kind) return;
  const ok = await readyP;
  if (!ok) { self.postMessage({ id: msg.id, error: "wasm not loaded" }); return; }
  try {
    if (msg.kind === "searchCoC") {
      // ntrees>1 runs K root-parallel trees in lockstep with BATCHED net evals
      // (coc_search_timed_multi) — feature-detected so a cached old wasm still works.
      const ntrees = (msg.ntrees >>> 0) || 0;
      const visits = (ntrees > 1 && typeof coc.coc_search_timed_multi === "function")
        ? coc.coc_search_timed_multi(
            String(msg.state), String(msg.prefix), String(msg.mode || "hybrid"),
            Number(msg.budget), (msg.maxSims >>> 0) || 0, BigInt(msg.seed >>> 0), ntrees)
        : coc_search_timed(
            String(msg.state), String(msg.prefix), String(msg.mode || "hybrid"),
            Number(msg.budget), (msg.maxSims >>> 0) || 0, BigInt(msg.seed >>> 0));
      if (!visits || !visits.length) { self.postMessage({ id: msg.id, error: "bad state/prefix" }); return; }
      self.postMessage({ id: msg.id, visits: Array.from(visits) });
    } else if (msg.kind === "stepInfo") {
      const info = JSON.parse(coc_step_info(String(msg.state), String(msg.prefix)));
      self.postMessage({ id: msg.id, info });
    } else if (msg.kind === "chainMove") {
      const move = coc_chain_move(String(msg.state), String(msg.prefix));
      self.postMessage({ id: msg.id, move });
    } else if (msg.kind === "newGame") {
      const save = need(coc.coc_new_game_json)(msg.board0 | 0, msg.board1 | 0, BigInt(msg.seed >>> 0));
      self.postMessage({ id: msg.id, ...engineResult("save", save) });
    } else if (msg.kind === "legal") {
      self.postMessage({ id: msg.id, ...engineResult("legal", need(coc.coc_legal_json)(String(msg.save))) });
    } else if (msg.kind === "apply") {
      const out = need(coc.coc_apply_json)(
        String(msg.save), String(msg.move), msg.seat >>> 0, String(msg.pid0), String(msg.pid1));
      if (out.startsWith('{"error"')) {
        self.postMessage({ id: msg.id, error: JSON.parse(out).error });
      } else {
        const parsed = JSON.parse(out);
        self.postMessage({ id: msg.id, save: JSON.stringify(parsed.save), events: parsed.events });
      }
    } else if (msg.kind === "gameDict") {
      self.postMessage({ id: msg.id, ...engineResult("dict",
        need(coc.coc_game_dict_json)(String(msg.save), String(msg.pid0), String(msg.pid1),
          String(msg.name0), String(msg.name1))) });
    } else if (msg.kind === "proj") {
      self.postMessage({ id: msg.id, ...engineResult("proj", need(coc.coc_offline_proj)(String(msg.save))) });
    }
  } catch (err) {
    self.postMessage({ id: msg.id, error: String(err) });
  }
};
