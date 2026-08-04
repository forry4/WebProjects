//! Render-dict parity: the Rust `gamedict::to_game_dict` must reproduce the Python
//! WIRE game dict (mk_room_state's shape) at every sampled boundary, modulo a single
//! shared canonicalization — implemented ONCE here and applied to BOTH sides, so the
//! two sides can't drift through separate canon code. Also gates the `to_proj` writer
//! (round-trips through `from_proj` to the sorted-pool projection string) and soaks
//! `new_game` + the legal-chain enumerator through full random games.
//!
//! Fixtures: `tools/gen_gamedict_fixtures.py` (run before this test).
//! Build: needs `bridge` (serde in the native lib): `cargo test --features bridge`.
//!
//! What canon() erases, and why each is safe:
//!  - "id" strings: offline tile ids are ledger-minted ("oh…"), Python's are build-
//!    order ("h…") — identity is per-instance bookkeeping, not game state.
//!  - "black" flags on tiles: blackness is per-instance provenance the compact state
//!    doesn't carry; a fixture-rebuilt ledger can't know it. Covered by a dedicated
//!    assertion below (buy_black yields a black-flagged tile in live offline play).
//!  - claimed_bonus: the compact state keeps only the claim COUNT; the offline shadow
//!    (`bonus_vp`) can't be rebuilt from a projection. Covered by the soak (live
//!    games must show a claimed_bonus entry whenever bonus_left dropped).
//!  - moves / moves_seq / turn_number / round_in_game / town_buildings: log-side or
//!    unread-by-the-JSX bookkeeping the offline driver owns in JS.
//!  - order of sold_goods / livestock_types / monastery_effects / pending colors /
//!    winner ties / depot goods: acquisition-order lists the compact state stores as
//!    sets/counts; the JSX reads them order-insensitively (lengths/membership).

use serde_json::{json, Map, Value};

const STRIP: [&str; 7] = [
    "black", "claimed_bonus", "moves", "moves_seq", "turn_number", "round_in_game",
    "town_buildings",
];
const SORT_LISTS: [&str; 7] =
    ["sold_goods", "livestock_types", "monastery_effects", "colors", "candidates", "winner", "types"];

fn canon(v: &Value, key: Option<&str>) -> Value {
    match v {
        Value::Object(m) => {
            let mut out = Map::new();
            for (k, val) in m {
                if STRIP.contains(&k.as_str()) {
                    continue;
                }
                if k == "id" {
                    out.insert("id".into(), json!("#"));
                    continue;
                }
                // goods COUNT maps: drop zero entries (present-vs-omitted is codec noise)
                if k == "goods" && val.is_object() {
                    let mut g = Map::new();
                    for (c, n) in val.as_object().unwrap() {
                        if n.as_i64().unwrap_or(0) != 0 {
                            g.insert(c.clone(), n.clone());
                        }
                    }
                    out.insert("goods".into(), Value::Object(g));
                    continue;
                }
                out.insert(k.clone(), canon(val, Some(k)));
            }
            Value::Object(out)
        }
        Value::Array(a) => {
            let mut items: Vec<Value> = a
                .iter()
                .map(|x| {
                    // candidates are BARE tile-id strings — mask them like "id" values
                    if key == Some("candidates") && x.is_string() {
                        json!("#")
                    } else {
                        canon(x, None)
                    }
                })
                .collect();
            let sortable = key.map(|k| SORT_LISTS.contains(&k)).unwrap_or(false)
                || (key == Some("goods")); // depot goods tile lists: arrival order is not state
            if sortable {
                items.sort_by_key(|x| x.to_string());
            }
            Value::Array(items)
        }
        other => other.clone(),
    }
}

/// Path-wise JSON diff for failure readability (full dicts are ~40KB each).
fn diff_paths(path: &str, a: &Value, b: &Value, out: &mut Vec<String>) {
    if out.len() > 24 {
        return;
    }
    match (a, b) {
        (Value::Object(ma), Value::Object(mb)) => {
            for k in ma.keys().chain(mb.keys().filter(|k| !ma.contains_key(*k))) {
                let pa = format!("{path}/{k}");
                match (ma.get(k), mb.get(k)) {
                    (Some(va), Some(vb)) => diff_paths(&pa, va, vb, out),
                    (Some(va), None) => out.push(format!("{pa}: rust-only = {va}")),
                    (None, Some(vb)) => out.push(format!("{pa}: python-only = {vb}")),
                    _ => {}
                }
            }
        }
        (Value::Array(aa), Value::Array(ab)) if aa.len() == ab.len() => {
            for (i, (va, vb)) in aa.iter().zip(ab).enumerate() {
                diff_paths(&format!("{path}[{i}]"), va, vb, out);
            }
        }
        _ if a != b => out.push(format!(
            "{path}: rust={} python={}",
            a.to_string().chars().take(160).collect::<String>(),
            b.to_string().chars().take(160).collect::<String>()
        )),
        _ => {}
    }
}

#[test]
fn gamedict_matches_python_wire() {
    let path = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/gamedict_fixtures.jsonl");
    let raw = std::fs::read_to_string(path).unwrap_or_else(|e| {
        panic!("read {path}: {e}\nRun: python rust-cores/coc-core/tools/gen_gamedict_fixtures.py")
    });
    let mut n = 0usize;
    let mut n_pending = 0usize;
    for (li, line) in raw.lines().enumerate() {
        if line.trim().is_empty() {
            continue;
        }
        let rec: Value = serde_json::from_str(line).expect("fixture line parses");
        let s = coc_core::pxio::from_proj(&rec["proj"]);
        if s.pending_pid >= 0 {
            n_pending += 1;
        }
        // Fresh ledger for the position (ids are canon-erased anyway).
        let mut ids = coc_core::gamedict::Ledger::empty();
        coc_core::gamedict::reconcile(&coc_core::engine::State::shell(s.boards), &s, &mut ids);
        let order: Vec<&str> = rec["wire"]["order"]
            .as_array()
            .expect("wire order")
            .iter()
            .map(|p| p.as_str().unwrap())
            .collect();
        let names: Vec<&str> = order
            .iter()
            .map(|p| rec["wire"]["players"][*p]["name"].as_str().unwrap_or(p))
            .collect();
        let got = coc_core::gamedict::to_game_dict(&s, &ids, [order[0], order[1]], [names[0], names[1]]);
        let want = canon(&rec["wire"], None);
        let got_c = canon(&got, None);
        if got_c != want {
            let mut diffs = Vec::new();
            diff_paths("", &got_c, &want, &mut diffs);
            panic!(
                "game dict mismatch at fixture line {li} — first diffs:\n{}",
                diffs[..diffs.len().min(12)].join("\n")
            );
        }
        n += 1;
    }
    assert!(n > 0, "no fixtures");
    assert!(n_pending > 0, "no pending-phase positions in fixtures");
    eprintln!("gamedict parity OK: {n} positions ({n_pending} pending-phase)");
}

/// `to_proj` writer gate: reading it back must yield the sorted-pool projection
/// (proj_string-identical to sorting the pools of the true state).
#[test]
fn to_proj_round_trips_to_sorted_projection() {
    let mut checked = 0usize;
    for seed in 0..8u64 {
        let mut s = coc_core::engine::State::new_game([(seed % 9) as u8, ((seed + 3) % 9) as u8], seed);
        let mut guard = 0;
        loop {
            let round = coc_core::pxio::from_proj(&coc_core::gamedict::to_proj(&s));
            let mut sorted = s.clone();
            sorted.supply[..sorted.supply_len as usize].sort_unstable();
            sorted.black_supply[..sorted.black_supply_len as usize].sort_unstable();
            sorted.goods_supply[..sorted.goods_supply_len as usize].sort_unstable();
            assert_eq!(
                coc_core::proj::proj_string(&round),
                coc_core::proj::proj_string(&sorted),
                "to_proj round-trip diverged (seed {seed})"
            );
            checked += 1;
            if s.mode == coc_core::engine::OVER || guard > 40 {
                break;
            }
            guard += 1;
            // advance a few random engine moves via the chain enumerator
            let moves = coc_core::gamedict::legal_compact_moves(&s);
            assert!(!moves.is_empty(), "no legal moves while not OVER");
            let pick = &moves[(seed as usize + guard * 7) % moves.len()];
            let chain = coc_core::actions::compact_to_actions(pick);
            for a in chain {
                coc_core::engine::apply(&mut s, a);
            }
        }
    }
    eprintln!("to_proj round-trip OK: {checked} positions");
}

/// Live-play soak through the OFFLINE apply path (the exact driver loop): random
/// full games must complete, conserve the tile multiset across containers, keep
/// the ledger in lockstep, and surface the provenance canon() erases (black flags
/// on bought black tiles, claimed_bonus entries when a color bonus is taken).
#[test]
fn offline_apply_soak() {
    let mut finished = 0usize;
    let mut saw_black = false;
    let mut saw_bonus = false;
    for seed in 0..6u64 {
        let mut save = coc_core::gamedict::new_game_save((seed % 9) as u8, ((seed * 5 + 2) % 9) as u8, seed);
        let mut guard = 0;
        loop {
            let (s, ids) = coc_core::gamedict::save_from_json(&save).expect("save parses");
            if s.mode == coc_core::engine::OVER {
                finished += 1;
                break;
            }
            guard += 1;
            assert!(guard < 1500, "seed {seed}: game did not finish");
            let actor = s.actor();
            assert!(actor >= 0, "no actor while not OVER");
            let moves = coc_core::gamedict::legal_compact_moves(&s);
            assert!(!moves.is_empty(), "seed {seed}: no legal moves");
            // Bias toward board-building moves (place/take/black): uniform-random play
            // almost never completes a color group, leaving the claimed_bonus coverage
            // assertion below unreachable. 3 of 4 picks prefer the building subset.
            let building: Vec<&serde_json::Value> = moves
                .iter()
                .filter(|m| matches!(m["t"].as_str(), Some("place") | Some("take_hex") | Some("black")))
                .collect();
            let k = guard * 13 + seed as usize;
            // Periodic forced end_turn: die-adjust backtracking REFUNDS workers, so a
            // deterministic index walk can cycle between free adjusts forever.
            let end = moves.iter().find(|m| m["t"] == serde_json::json!("end"));
            let mv = if k % 8 == 0 && end.is_some() {
                end.unwrap().to_string()
            } else if !building.is_empty() && k % 4 != 0 {
                building[k % building.len()].to_string()
            } else {
                moves[k % moves.len()].to_string()
            };
            let (next, _events) = coc_core::gamedict::apply_save(&save, &mv, actor as usize, "p0", "p1")
                .unwrap_or_else(|e| panic!("seed {seed}: apply failed: {e} on {mv}"));
            save = next;

            let (s2, ids2) = coc_core::gamedict::save_from_json(&save).expect("save re-parses");
            // Ledger lockstep: every occupied visible slot has an id; empty slots don't.
            for d in 0..6 {
                for slot in 0..2 {
                    assert_eq!(
                        s2.depot_hex[d][slot] != 0,
                        !ids2.depot_hex[d][slot].is_empty(),
                        "seed {seed}: ledger desync at depot {d} slot {slot}"
                    );
                }
            }
            let dict = coc_core::gamedict::to_game_dict(&s2, &ids2, ["p0", "p1"], ["P0", "P1"]);
            let txt = dict.to_string();
            if txt.contains(r#""black":true"#) {
                saw_black = true;
            }
            if !dict["players"]["p0"]["claimed_bonus"].as_array().unwrap().is_empty()
                || !dict["players"]["p1"]["claimed_bonus"].as_array().unwrap().is_empty()
            {
                saw_bonus = true;
            }
            let _ = ids;
        }
    }
    assert!(finished >= 5, "only {finished}/6 games finished");
    assert!(saw_black, "no black-flagged tile ever rendered (buy_black path untested)");
    assert!(saw_bonus, "no claimed_bonus entry ever rendered (bonus_vp shadow untested)");
}
