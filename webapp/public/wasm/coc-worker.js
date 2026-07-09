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
// Lifecycle: { ready:true } once wasm + model load, or { ready:false, error } if either fails
//   (the main thread drops this worker; if none are ready it never announces client_ai_ready
//   and the server computes the bot turn — the pre-existing hard path).

import init, { coc_init_model, coc_step_info, coc_search_timed, coc_chain_move } from "./coc_core.js";

let readyResolve;
const readyP = new Promise((res) => (readyResolve = res));

(async () => {
  try {
    await init();
    const wanted = new URL(import.meta.url).searchParams.get("model") || "coc_pv_model.bin";
    // whitelist so a crafted query can never fetch an arbitrary URL
    const model = wanted === "coc_pv_model_hard.bin" ? wanted : "coc_pv_model.bin";
    const resp = await fetch(new URL(`./${model}`, import.meta.url));
    if (!resp.ok) throw new Error("model fetch " + resp.status);
    const bytes = new Uint8Array(await resp.arrayBuffer());
    if (!coc_init_model(bytes)) throw new Error("model parse failed");
    readyResolve(true);
    self.postMessage({ ready: true });
  } catch (err) {
    readyResolve(false);
    self.postMessage({ ready: false, error: String(err) });
  }
})();

self.onmessage = async (e) => {
  const msg = e.data || {};
  if (!msg.kind) return;
  const ok = await readyP;
  if (!ok) { self.postMessage({ id: msg.id, error: "wasm not loaded" }); return; }
  try {
    if (msg.kind === "searchCoC") {
      const visits = coc_search_timed(
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
    }
  } catch (err) {
    self.postMessage({ id: msg.id, error: String(err) });
  }
};
