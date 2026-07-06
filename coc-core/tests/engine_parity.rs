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

use coc_core::boards_gen::{MAX_REGIONS, N_SPACES};
use coc_core::engine::{
    self, Die, Micro, Pending, PlayerState, State, A_ADJUST0, A_BUY_BLACK0, A_DISCARD0,
    A_END_TURN, A_GOODS0, A_M6, A_PLACE_SLOT0, A_SELL, A_SHIP_DEPOT0, A_SKIP, A_SPACE0,
    A_SPEND_DIE0, A_TAKE_HEX0, A_WH0, A_WORKERS, A_XVALUE0,
};
use coc_core::proj::{fnv64, proj_string};
use serde_json::Value;

fn iu(v: &Value) -> i64 {
    v.as_i64().expect("int")
}

fn arr<'a>(v: &'a Value, k: &str) -> &'a Vec<Value> {
    v[k].as_array().unwrap_or_else(|| panic!("array {k}"))
}

fn from_proj(p: &Value) -> State {
    let boards = [iu(&p["boards"][0]) as u8, iu(&p["boards"][1]) as u8];
    let mut s = State::shell(boards);
    s.phase = iu(&p["phase"]) as u8;
    s.round = iu(&p["round"]) as u8;
    s.mode = iu(&p["mode"]) as u8;
    s.winner = iu(&p["winner"]) as i8;
    s.track_pos = [iu(&p["track_pos"][0]) as u8, iu(&p["track_pos"][1]) as u8];
    s.track_top = iu(&p["track_top"]) as i8;
    s.round_order = [iu(&p["round_order"][0]) as u8, iu(&p["round_order"][1]) as u8];
    s.start_player = iu(&p["start_player"]) as u8;
    s.turn = iu(&p["turn"]) as i8;
    s.white_die = iu(&p["white_die"]) as u8;
    for seat in 0..2 {
        for die in 0..2 {
            let d = &p["dice"][seat][die];
            s.dice[seat][die] = Die {
                value: iu(&d[0]) as u8,
                orig: iu(&d[1]) as u8,
                used: iu(&d[2]) != 0,
                adjusted: iu(&d[3]) != 0,
            };
        }
    }
    s.black_used = iu(&p["black_used"]) != 0;
    s.m6_used = iu(&p["m6_used"]) != 0;
    for d in 0..6 {
        s.depot_hex[d] = [iu(&p["depot_hex"][d][0]) as u16, iu(&p["depot_hex"][d][1]) as u16];
        for c in 0..6 {
            s.depot_goods[d][c] = iu(&p["depot_goods"][d][c]) as u8;
        }
    }
    for slot in 0..4 {
        s.black_depot[slot] = iu(&p["black_depot"][slot]) as u16;
    }
    let sup = arr(p, "supply");
    s.supply_len = sup.len() as u8;
    for (i, v) in sup.iter().enumerate() {
        s.supply[i] = iu(v) as u16;
    }
    let bsup = arr(p, "black_supply");
    s.black_supply_len = bsup.len() as u8;
    for (i, v) in bsup.iter().enumerate() {
        s.black_supply[i] = iu(v) as u16;
    }
    let gsup = arr(p, "goods_supply");
    s.goods_supply_len = gsup.len() as u8;
    for (i, v) in gsup.iter().enumerate() {
        s.goods_supply[i] = iu(v) as u8;
    }
    let gq = arr(p, "goods_queue");
    s.goods_queue_len = gq.len() as u8;
    for (i, v) in gq.iter().enumerate() {
        s.goods_queue[i] = iu(v) as u8;
    }
    for c in 0..6 {
        s.bonus_left[c] = iu(&p["bonus_left"][c]) as u8;
    }
    for seat in 0..2 {
        let pp = &p["players"][seat];
        let mut ps = PlayerState::empty();
        for sid in 0..N_SPACES {
            ps.duchy[sid] = iu(&pp["duchy"][sid]) as u16;
            if ps.duchy[sid] != 0 {
                ps.filled |= 1 << sid;
            }
        }
        ps.castle_sid = iu(&pp["castle_sid"]) as u8;
        for slot in 0..3 {
            ps.storage[slot] = iu(&pp["storage"][slot]) as u16;
        }
        for c in 0..6 {
            ps.goods[c] = iu(&pp["goods"][c]) as u8;
            ps.sold[c] = iu(&pp["sold"][c]) as u8;
        }
        ps.workers = iu(&pp["workers"]) as i16;
        ps.silver = iu(&pp["silver"]) as i16;
        ps.vp = iu(&pp["vp"]) as i16;
        ps.bonus_claimed = iu(&pp["bonus_claimed"]) as u8;
        ps.mines = iu(&pp["mines"]) as u8;
        for b in 0..8 {
            ps.buildings[b] = iu(&pp["buildings"][b]) as u8;
        }
        ps.livestock_mask = iu(&pp["livestock_mask"]) as u8;
        ps.mon_mask = iu(&pp["mon_mask"]) as u32;
        for r in 0..MAX_REGIONS {
            ps.town_bldg[r] = iu(&pp["town_bldg"][r]) as u8;
        }
        s.players[seat] = ps;
    }
    s.pending_pid = iu(&p["pending_pid"]) as i8;
    let f = arr(p, "pending_fields");
    s.pending = match iu(&p["pending_tag"]) {
        0 => Pending::None,
        1 => Pending::ExtraAction,
        2 => Pending::ShipChoose,
        3 => Pending::ShipAdj { cands: iu(&f[0]) as u8 },
        4 => Pending::GoodsPick {
            depot: iu(&f[0]) as u8,
            colors: iu(&f[1]) as u8,
            m5_from: iu(&f[2]) as i8,
        },
        5 => Pending::BuildingTake { types: iu(&f[0]) as u8 },
        6 => Pending::Warehouse,
        7 => Pending::Townhall,
        t => panic!("bad pending tag {t}"),
    };
    s
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
