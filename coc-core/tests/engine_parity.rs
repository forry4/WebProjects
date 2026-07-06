//! Differential parity: replay Python-engine fixture games through the Rust engine
//! and require identical canonical projections (FNV-64 of proj_string) after EVERY
//! engine move, plus legal-move-set equality (as a micro-action trie) at recorded
//! positions, plus final scores/winner.
//!
//! Generate fixtures first:
//!   python coc-core/tools/gen_engine_fixtures.py --games 2000 --loaded 300
//! Point COC_FIXTURES at another dir to use a different set.

use std::collections::BTreeSet;
use std::fs;
use std::io::{BufRead, BufReader};

use coc_core::engine::{
    self, Micro, State, A_ADJUST0, A_BUY_BLACK0, A_DISCARD0, A_END_TURN, A_GOODS0, A_M6,
    A_PLACE_SLOT0, A_SELL, A_SHIP_DEPOT0, A_SKIP, A_SPACE0, A_SPEND_DIE0, A_TAKE_HEX0, A_WH0,
    A_WORKERS, A_XVALUE0,
};
use coc_core::proj::{fnv64, proj_string};
use coc_core::pxio::from_proj;
use serde_json::Value;

fn iu(v: &Value) -> i64 {
    v.as_i64().expect("int")
}

fn arr<'a>(v: &'a Value, k: &str) -> &'a Vec<Value> {
    v[k].as_array().unwrap_or_else(|| panic!("array {k}"))
}


fn compact_to_actions(c: &Value) -> Vec<usize> {
    let t = c["t"].as_str().expect("t");
    let g = |k: &str| iu(&c[k]) as usize;
    match t {
        "end" => vec![A_END_TURN],
        "skip" => vec![A_SKIP],
        "take_hex" => vec![A_SPEND_DIE0 + g("die"), A_TAKE_HEX0 + g("depot") * 2 + g("slot")],
        "place" => vec![A_SPEND_DIE0 + g("die"), A_PLACE_SLOT0 + g("slot"), A_SPACE0 + g("space")],
        "sell" => vec![A_SPEND_DIE0 + g("die"), A_SELL],
        "workers" => vec![A_SPEND_DIE0 + g("die"), A_WORKERS],
        "adjust" => vec![A_ADJUST0 + g("die") * 6 + (g("to") - 1)],
        "black" => vec![A_BUY_BLACK0 + g("slot")],
        "discard" => vec![A_DISCARD0 + g("slot")],
        "m6" => vec![A_M6, A_TAKE_HEX0 + g("depot") * 2 + g("slot")],
        "btake" => vec![A_TAKE_HEX0 + g("depot") * 2 + g("slot")],
        "castle" => vec![A_SPACE0 + g("space")],
        "ship" | "ship_adj" => vec![A_SHIP_DEPOT0 + g("depot")],
        "pick" => vec![A_GOODS0 + g("color")],
        "wh" => vec![A_WH0 + g("color")],
        "townhall" => vec![A_PLACE_SLOT0 + g("slot"), A_SPACE0 + g("space")],
        "extra" => {
            let mut out = vec![A_XVALUE0 + g("value") - 1];
            let sub = &c["sub"];
            let gs = |k: &str| iu(&sub[k]) as usize;
            match sub["t"].as_str().expect("sub t") {
                "workers" => out.push(A_WORKERS),
                "sell" => out.push(A_SELL),
                "take_hex" => out.push(A_TAKE_HEX0 + gs("depot") * 2 + gs("slot")),
                "place" => {
                    out.push(A_PLACE_SLOT0 + gs("slot"));
                    out.push(A_SPACE0 + gs("space"));
                }
                st => panic!("bad extra sub {st}"),
            }
            out
        }
        _ => panic!("bad compact type {t}"),
    }
}

/// Node-wise equality of the engine's legal-move set (as micro chains) vs the Rust
/// legal_actions_full — proves the decomposition in BOTH directions at this position.
fn check_legal_trie(s: &State, chains: &[Vec<usize>], ctx: &str) {
    let legal: BTreeSet<usize> = engine::legal_actions_full(s).into_iter().collect();
    let firsts: BTreeSet<usize> = chains.iter().map(|c| c[0]).collect();
    assert_eq!(
        firsts, legal,
        "legal-set mismatch at {ctx}\n engine-first: {firsts:?}\n rust: {legal:?}"
    );
    for &a in &firsts {
        let subs: Vec<Vec<usize>> = chains
            .iter()
            .filter(|c| c[0] == a && c.len() > 1)
            .map(|c| c[1..].to_vec())
            .collect();
        let terminal = chains.iter().any(|c| c[0] == a && c.len() == 1);
        assert!(
            !(terminal && !subs.is_empty()),
            "action {a} is both terminal and prefix at {ctx}"
        );
        if !subs.is_empty() {
            let mut s2 = s.clone();
            engine::apply(&mut s2, a);
            check_legal_trie(&s2, &subs, ctx);
        }
    }
}

#[test]
fn heuristic_value_parity() {
    let dir = std::env::var("COC_FIXTURES")
        .unwrap_or_else(|_| format!("{}/tests/fixtures", env!("CARGO_MANIFEST_DIR")));
    let path = format!("{dir}/values.jsonl");
    let file = fs::File::open(&path).unwrap_or_else(|_| {
        panic!("no value fixtures at {path} — run: python coc-core/tools/gen_value_fixtures.py")
    });
    let mut n = 0u64;
    for line in BufReader::new(file).lines() {
        let line = line.expect("read line");
        if line.trim().is_empty() {
            continue;
        }
        let rec: Value = serde_json::from_str(&line).expect("parse value fixture");
        let s = from_proj(&rec["proj"]);
        for (seat, key) in [(0usize, "v0"), (1, "v1")] {
            let want: f64 = rec[key].as_str().expect("v str").parse().expect("v f64");
            let got = coc_core::heuristic::value(&s, seat);
            assert!(
                (got - want).abs() <= 1e-9,
                "value mismatch seat {seat} at fixture {n}: rust {got} vs python {want}"
            );
        }
        n += 1;
    }
    println!("value parity OK: {n} positions x 2 seats");
    assert!(n >= 500);
}

#[test]
fn python_fixture_replay() {
    let dir = std::env::var("COC_FIXTURES")
        .unwrap_or_else(|_| format!("{}/tests/fixtures", env!("CARGO_MANIFEST_DIR")));
    let path = format!("{dir}/games.jsonl");
    let file = fs::File::open(&path).unwrap_or_else(|_| {
        panic!("no fixtures at {path} — run: python coc-core/tools/gen_engine_fixtures.py")
    });
    let reader = BufReader::new(file);

    let (mut games, mut moves_total) = (0u64, 0u64);
    for (li, line) in reader.lines().enumerate() {
        let line = line.expect("read line");
        if line.trim().is_empty() {
            continue;
        }
        let g: Value = serde_json::from_str(&line).expect("parse game json");
        let seed = iu(&g["seed"]);
        let mut s = from_proj(&g["init"]);
        let ih: u64 = g["ih"].as_str().expect("ih").parse().expect("ih u64");
        assert_eq!(
            fnv64(&proj_string(&s)),
            ih,
            "init hash mismatch (game line {li}, seed {seed})\n{}",
            proj_string(&s)
        );

        for (mi, mrec) in arr(&g, "moves").iter().enumerate() {
            let ctx = format!("game {li} (seed {seed}) move {mi}");
            if let Some(l) = mrec.get("L").and_then(|v| v.as_array()) {
                let chains: Vec<Vec<usize>> = l.iter().map(compact_to_actions).collect();
                check_legal_trie(&s, &chains, &ctx);
            }
            if let Some(d) = mrec.get("d").and_then(|v| v.as_array()) {
                s.dice_script = d.iter().map(|v| iu(v) as u8).collect();
            }
            for &a in &compact_to_actions(&mrec["m"]) {
                let legal = engine::legal_actions_full(&s);
                assert!(
                    legal.contains(&a),
                    "action {a} not legal at {ctx}; legal={legal:?}"
                );
                engine::apply(&mut s, a);
            }
            assert_eq!(s.micro, Micro::None, "micro not at boundary after {ctx}");
            assert!(s.dice_script.is_empty(), "unconsumed dice after {ctx}");
            let h: u64 = mrec["h"].as_str().expect("h").parse().expect("h u64");
            let got = fnv64(&proj_string(&s));
            assert_eq!(got, h, "hash mismatch after {ctx}\nrust: {}", proj_string(&s));
            if let Some(p) = mrec.get("p") {
                let s2 = from_proj(p);
                assert_eq!(
                    proj_string(&s),
                    proj_string(&s2),
                    "full projection mismatch after {ctx}"
                );
            }
            moves_total += 1;
        }

        assert!(s.is_over(), "game not over (line {li}, seed {seed})");
        let scores = s.final_scores();
        assert_eq!(scores[0] as i64, iu(&g["scores"][0]), "score[0] (seed {seed})");
        assert_eq!(scores[1] as i64, iu(&g["scores"][1]), "score[1] (seed {seed})");
        assert_eq!(s.winner as i64, iu(&g["winner"]), "winner (seed {seed})");
        games += 1;
    }
    println!("parity OK: {games} games, {moves_total} engine moves, state-exact");
    assert!(games > 0);
}
