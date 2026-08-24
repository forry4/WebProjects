//! Offline-play surface: the render view writer (`player_view` mirror), the search
//! projection writer (`compact.project` mirror), engine-dict/encmove parsing, legal
//! moves as engine dicts, and apply-with-log-events. See spender-core/gamedict.rs and
//! coc-core/gamedict.rs for the pattern; Duel is the simple case for identity (cards
//! are stable id strings resolved by the frontend's /catalog — no tile ledger needed)
//! and the subtle case for redaction (the opponent's reserve list is HETEROGENEOUS:
//! face-up reserves stay raw id strings, blind ones become {"level", "facedown"}).

use crate::cards::{
    ABILITY, AB_AGAIN, AB_PRIVILEGE, AB_STEAL, AB_TAKE_SAME, CROWNS, LEVEL_OF, LEVEL_OFF, N_CARDS,
    N_ROYALS, PTS, ROYAL_PTS,
};
use crate::engine::{
    card_id_str, royal_id_str, BuySrc, Move, ReserveSrc, Shuffler, State, Via, N_CELLS, OVER,
    PK_CHOOSE_ROYAL, PK_DISCARD, PK_NONE, PK_STEAL, PK_TAKE_SAME, WC_COLOR, WC_CROWNS, WC_POINTS,
};
use serde_json::{json, Map, Value};

pub const TOKENS: [&str; 7] = ["white", "blue", "green", "red", "black", "pearl", "gold"];
pub const COLORS: [&str; 5] = ["white", "blue", "green", "red", "black"];
const KIND_NAMES: [&str; 5] = ["", "take_same", "steal", "choose_royal", "discard"];

fn token_str(t: i8) -> Value {
    if t < 0 { Value::Null } else { json!(TOKENS[t as usize]) }
}

fn color_idx(name: &str) -> Option<usize> {
    TOKENS.iter().position(|&t| t == name)
}

/// "d2_07" → global card index; None on anything malformed.
pub fn card_idx(id: &str) -> Option<usize> {
    let rest = id.strip_prefix('d')?;
    let (lvl_s, nn_s) = rest.split_once('_')?;
    let lvl: usize = lvl_s.parse().ok()?;
    let nn: usize = nn_s.parse().ok()?;
    if !(1..=3).contains(&lvl) {
        return None;
    }
    let ci = LEVEL_OFF[lvl - 1] + nn;
    if ci >= N_CARDS || LEVEL_OF[ci] as usize != lvl {
        return None;
    }
    Some(ci)
}

pub fn royal_idx(id: &str) -> Option<usize> {
    let n: usize = id.strip_prefix('r')?.parse().ok()?;
    if n < N_ROYALS { Some(n) } else { None }
}

// ─── The render view (player_view mirror) ──────────────────────────────────

/// Mirror of `engine.player_view(game, viewer)`: the true dict minus
/// bag/decks/rng/seed/turn_undo/reserved_from_deck, plus bag_count/deck_counts,
/// with the NON-viewer seat's blind reserves as {"level", "facedown": true} —
/// unless the game is over, when everything is revealed. `log` is always [] (the
/// offline driver owns it, like the other games).
pub fn to_player_view(s: &State, pids: [&str; 2], names: [&str; 2], viewer: i32) -> Value {
    let pid_of = |seat: i32| -> Value {
        if seat < 0 { Value::Null } else { json!(pids[seat as usize]) }
    };
    let mut g = Map::new();
    g.insert("game".into(), json!("spender_duel"));
    g.insert("phase".into(), json!(if s.phase == OVER { "over" } else { "playing" }));
    g.insert("winner".into(), pid_of(s.winner));
    g.insert(
        "win_condition".into(),
        match s.win_condition {
            WC_POINTS => json!("points"),
            WC_CROWNS => json!("crowns"),
            WC_COLOR => json!("color"),
            _ => Value::Null,
        },
    );
    g.insert(
        "win_color".into(),
        if s.win_color < 0 { Value::Null } else { json!(COLORS[s.win_color as usize]) },
    );
    g.insert("order".into(), json!([pids[0], pids[1]]));
    g.insert("turn".into(), json!(pids[s.turn]));
    g.insert("turn_number".into(), json!(s.turn_number));
    g.insert(
        "turn_flags".into(),
        json!({"replenished": s.replenished, "revealed": s.revealed}),
    );
    g.insert("again".into(), json!(s.again));
    g.insert(
        "board".into(),
        Value::Array(s.board.iter().map(|&t| token_str(t)).collect()),
    );
    g.insert("bag_count".into(), json!(s.bag.len()));
    g.insert("privileges_board".into(), json!(s.privileges_board));
    let mut deck_counts = Map::new();
    let mut pyramid = Map::new();
    for lvl in 0..3 {
        deck_counts.insert((lvl + 1).to_string(), json!(s.decks[lvl].len()));
        pyramid.insert(
            (lvl + 1).to_string(),
            Value::Array(
                s.pyramid[lvl]
                    .iter()
                    .map(|&c| if c < 0 { Value::Null } else { json!(card_id_str(c as usize)) })
                    .collect(),
            ),
        );
    }
    g.insert("deck_counts".into(), Value::Object(deck_counts));
    g.insert("pyramid".into(), Value::Object(pyramid));
    g.insert(
        "royals_available".into(),
        Value::Array(s.royals_available.iter().map(|&r| json!(royal_id_str(r))).collect()),
    );

    let mut players = Map::new();
    for seat in 0..2usize {
        let p = &s.players[seat];
        let mut tokens = Map::new();
        for (i, t) in TOKENS.iter().enumerate() {
            tokens.insert((*t).into(), json!(p.tokens[i]));
        }
        // viewer < 0 = spectator: BOTH hands' blind reserves are redacted (engine.py:
        // "pid=None = spectator").
        let hide_blind = (viewer < 0 || viewer as usize != seat) && s.phase != OVER;
        let reserved: Vec<Value> = p
            .reserved
            .iter()
            .map(|&cid| {
                if hide_blind && p.reserved_from_deck.contains(&cid) {
                    json!({"level": LEVEL_OF[cid], "facedown": true})
                } else {
                    json!(card_id_str(cid))
                }
            })
            .collect();
        let purchased: Vec<Value> = p
            .purchased
            .iter()
            .map(|&(cid, asc)| {
                json!({"id": card_id_str(cid),
                       "as_color": if asc < 0 { Value::Null } else { json!(COLORS[asc as usize]) }})
            })
            .collect();
        players.insert(
            pids[seat].to_string(),
            json!({
                "name": names[seat],
                "tokens": Value::Object(tokens),
                "privileges": p.privileges,
                "reserved": reserved,
                "purchased": purchased,
                "royals": p.royals.iter().map(|&r| royal_id_str(r)).collect::<Vec<_>>(),
                "royals_claimed": p.royals_claimed,
            }),
        );
    }
    g.insert("players".into(), Value::Object(players));

    g.insert("pending_pid".into(), pid_of(s.pending_pid));
    if s.pending_kind == PK_NONE {
        g.insert("pending_kind".into(), Value::Null);
        g.insert("pending".into(), Value::Null);
    } else {
        let kind = KIND_NAMES[s.pending_kind as usize];
        let via: Value = match s.pending.via {
            Via::Card(c) => json!(card_id_str(c)),
            Via::Royal(r) => json!(royal_id_str(r)),
            Via::None => Value::Null,
        };
        let mut ctx = Map::new();
        match s.pending_kind {
            PK_TAKE_SAME => {
                ctx.insert("color".into(), json!(TOKENS[s.pending.color as usize]));
                ctx.insert("cells".into(), json!(s.pending.cells));
                if !via.is_null() {
                    ctx.insert("via".into(), via);
                }
            }
            PK_STEAL => {
                ctx.insert(
                    "colors".into(),
                    json!(s.pending.colors.iter().map(|&c| TOKENS[c]).collect::<Vec<_>>()),
                );
                if !via.is_null() {
                    ctx.insert("via".into(), via);
                }
            }
            PK_CHOOSE_ROYAL => {
                ctx.insert(
                    "royals".into(),
                    json!(s.pending.royals.iter().map(|&r| royal_id_str(r)).collect::<Vec<_>>()),
                );
            }
            PK_DISCARD => {
                ctx.insert("excess".into(), json!(s.pending.excess));
            }
            _ => {}
        }
        g.insert("pending_kind".into(), json!(kind));
        g.insert("pending".into(), json!({"ctx": Value::Object(ctx)}));
    }
    g.insert("log".into(), json!([]));
    Value::Object(g)
}

// ─── The search projection (compact.project mirror) ────────────────────────

/// Pure function of what `seat` may legally know: bag SORTED, decks as sorted
/// `unseen` pools (deck ∪ the opponent's blind reserves) + true lengths, the
/// opponent's blind reserves as per-level counts. Byte-compatible with
/// `compact::from_proj` (the wasm search's only reader).
pub fn to_proj(s: &State, seat: usize) -> Value {
    let opp = 1 - seat;
    let mut bag: Vec<u8> = s.bag.clone();
    bag.sort_unstable();
    let mut unseen: Vec<Vec<usize>> = vec![Vec::new(); 3];
    let mut deck_lens = [0usize; 3];
    for lvl in 0..3 {
        deck_lens[lvl] = s.decks[lvl].len();
        unseen[lvl] = s.decks[lvl].clone();
    }
    for &cid in &s.players[opp].reserved_from_deck {
        unseen[LEVEL_OF[cid] as usize - 1].push(cid);
    }
    for u in unseen.iter_mut() {
        u.sort_unstable();
    }
    let players: Vec<Value> = (0..2)
        .map(|si| {
            let p = &s.players[si];
            let mine = si == seat;
            let reserved: Vec<usize> = if mine {
                p.reserved.clone()
            } else {
                p.reserved
                    .iter()
                    .copied()
                    .filter(|c| !p.reserved_from_deck.contains(c))
                    .collect()
            };
            let mut blind = [0usize; 3];
            if !mine {
                for &cid in &p.reserved_from_deck {
                    blind[LEVEL_OF[cid] as usize - 1] += 1;
                }
            }
            json!({
                "tokens": p.tokens.to_vec(),
                "privileges": p.privileges,
                "reserved": reserved,
                "reserved_from_deck": if mine { p.reserved_from_deck.clone() } else { vec![] },
                "reserved_blind": blind.to_vec(),
                "purchased": p.purchased.iter().map(|&(c, a)| json!([c, a])).collect::<Vec<_>>(),
                "royals": p.royals.clone(),
                "royals_claimed": p.royals_claimed,
            })
        })
        .collect();
    json!({
        "seat": seat,
        "phase": if s.phase == OVER { 1 } else { 0 },
        "winner": s.winner,
        "win_condition": s.win_condition,
        "win_color": s.win_color,
        "turn": s.turn,
        "turn_number": s.turn_number,
        "replenished": s.replenished as i32,
        "again": s.again as i32,
        "board": s.board.iter().map(|&t| t as i32).collect::<Vec<_>>(),
        "bag": bag,
        "privileges_board": s.privileges_board,
        "pyramid": s.pyramid.iter().map(|row| row.clone()).collect::<Vec<_>>(),
        "deck_lens": deck_lens.to_vec(),
        "unseen": unseen,
        "royals": s.royals_available.clone(),
        "players": players,
        "pending_pid": s.pending_pid,
        "pending_kind": s.pending_kind,
        // Field-by-field mirror of Python's `ctx.get(k, default)`: each field exists
        // only under its kind, so gate on the kind rather than trusting whatever the
        // Rust Pending's unused fields hold (Pending::default's color is 0, not -1).
        "pending": {
            "color": if s.pending_kind == PK_TAKE_SAME { s.pending.color } else { -1 },
            "cells": if s.pending_kind == PK_TAKE_SAME { s.pending.cells.clone() } else { vec![] },
            "colors": if s.pending_kind == PK_STEAL { s.pending.colors.clone() } else { vec![] },
            "royals": if s.pending_kind == PK_CHOOSE_ROYAL { s.pending.royals.clone() } else { vec![] },
            "excess": if s.pending_kind == PK_DISCARD { s.pending.excess } else { 0 },
        },
    })
}

// ─── Move parsing (engine dict + encmove, both non-panicking) ──────────────

fn cells_of(v: &Value, key: &str) -> Option<Vec<usize>> {
    let arr = v.get(key)?.as_array()?;
    let mut out = Vec::with_capacity(arr.len());
    for x in arr {
        let n = x.as_u64()? as usize;
        if n >= N_CELLS {
            return None;
        }
        out.push(n);
    }
    Some(out)
}

/// The frontend's `{"type": ...}` move dicts (engine.py shapes).
pub fn parse_engine_move(v: &Value) -> Option<Move> {
    let cell = |k: &str| v.get(k).and_then(|x| x.as_u64()).map(|n| n as usize);
    match v.get("type")?.as_str()? {
        "take" => Some(Move::Take { cells: cells_of(v, "cells")? }),
        "use_privilege" => Some(Move::UsePrivilege { cell: cell("cell")? }),
        "replenish" => Some(Move::Replenish),
        "pass" => Some(Move::Pass),
        "reserve" => {
            let gold_cell = cell("gold_cell")?;
            let src = v.get("source")?;
            let level = src.get("level")?.as_u64()? as usize;
            if !(1..=3).contains(&level) {
                return None;
            }
            let src = match src.get("kind")?.as_str()? {
                "pyramid" => ReserveSrc::Pyramid {
                    level: level - 1,
                    slot: src.get("slot")?.as_u64()? as usize,
                },
                "deck" => ReserveSrc::Deck { level: level - 1 },
                _ => return None,
            };
            Some(Move::Reserve { gold_cell, src })
        }
        "buy" => {
            let card = card_idx(v.get("card_id")?.as_str()?)?;
            let from = match v.get("from")?.as_str()? {
                "pyramid" => BuySrc::Pyramid,
                "reserve" => BuySrc::Reserve,
                _ => return None,
            };
            let as_color = match v.get("as_color").and_then(|x| x.as_str()) {
                Some(c) => COLORS.iter().position(|&x| x == c)? as i8,
                None => -1,
            };
            Some(Move::Buy { card, from, as_color })
        }
        "take_same" => Some(Move::TakeSame { cell: cell("cell")? }),
        "steal" => Some(Move::Steal { color: color_idx(v.get("color")?.as_str()?)? }),
        "choose_royal" => Some(Move::ChooseRoyal { royal: royal_idx(v.get("royal_id")?.as_str()?)? }),
        "discard" => Some(Move::Discard { color: color_idx(v.get("color")?.as_str()?)? }),
        "skip_pending" => Some(Move::SkipPending),
        _ => None,
    }
}

/// The search loop's encmove dicts (`{"t": ...}` — what duel_pick_move emits).
/// Non-panicking mirror of encmove::decode_move.
pub fn parse_encmove(v: &Value) -> Option<Move> {
    let u = |k: &str| v.get(k).and_then(|x| x.as_u64()).map(|n| n as usize);
    let i = |k: &str| v.get(k).and_then(|x| x.as_i64());
    match v.get("t")?.as_str()? {
        "take" => Some(Move::Take { cells: cells_of(v, "cells")? }),
        "use_privilege" => Some(Move::UsePrivilege { cell: u("cell")? }),
        "replenish" => Some(Move::Replenish),
        "pass" => Some(Move::Pass),
        "reserve" => {
            let level = u("level")?;
            if !(1..=3).contains(&level) {
                return None;
            }
            let src = if i("kind")? == 0 {
                ReserveSrc::Pyramid { level: level - 1, slot: u("slot")? }
            } else {
                ReserveSrc::Deck { level: level - 1 }
            };
            Some(Move::Reserve { gold_cell: u("cell")?, src })
        }
        "buy" => Some(Move::Buy {
            card: u("card")?.min(N_CARDS - 1),
            from: if i("from")? == 0 { BuySrc::Pyramid } else { BuySrc::Reserve },
            as_color: i("as_color")? as i8,
        }),
        "take_same" => Some(Move::TakeSame { cell: u("cell")? }),
        "steal" => Some(Move::Steal { color: u("color")? }),
        "choose_royal" => Some(Move::ChooseRoyal { royal: u("royal")? }),
        "discard" => Some(Move::Discard { color: u("color")? }),
        "skip_pending" => Some(Move::SkipPending),
        _ => None,
    }
}

/// A Move as the engine-dict shape — key sets match engine.legal_moves exactly
/// (as_color omitted for non-wild buys, slot omitted for deck reserves).
pub fn move_to_engine_dict(mv: &Move) -> Value {
    match mv {
        Move::Take { cells } => json!({"type": "take", "cells": cells}),
        Move::UsePrivilege { cell } => json!({"type": "use_privilege", "cell": cell}),
        Move::Replenish => json!({"type": "replenish"}),
        Move::Pass => json!({"type": "pass"}),
        Move::Reserve { gold_cell, src } => match src {
            ReserveSrc::Pyramid { level, slot } => json!({"type": "reserve", "gold_cell": gold_cell,
                "source": {"kind": "pyramid", "level": level + 1, "slot": slot}}),
            ReserveSrc::Deck { level } => json!({"type": "reserve", "gold_cell": gold_cell,
                "source": {"kind": "deck", "level": level + 1}}),
        },
        Move::Buy { card, from, as_color } => {
            let mut m = Map::new();
            m.insert("type".into(), json!("buy"));
            m.insert("card_id".into(), json!(card_id_str(*card)));
            m.insert(
                "from".into(),
                json!(if matches!(from, BuySrc::Pyramid) { "pyramid" } else { "reserve" }),
            );
            if *as_color >= 0 {
                m.insert("as_color".into(), json!(COLORS[*as_color as usize]));
            }
            Value::Object(m)
        }
        Move::TakeSame { cell } => json!({"type": "take_same", "cell": cell}),
        Move::Steal { color } => json!({"type": "steal", "color": TOKENS[*color]}),
        Move::ChooseRoyal { royal } => json!({"type": "choose_royal", "royal_id": royal_id_str(*royal)}),
        Move::Discard { color } => json!({"type": "discard", "color": TOKENS[*color]}),
        Move::SkipPending => json!({"type": "skip_pending"}),
    }
}

// ─── Apply with log-event synthesis ────────────────────────────────────────

/// Log records the applied move generated, engine.py-log style: `t` = the PRE-move
/// turn_number, `None`-ish fields omitted, `frm` (not `from`) on buys. Auto events
/// (again / privilege_gain / royal / extra_turn / game_over) are derived by diffing.
fn mk_rec(t: i32, pid: &str, ty: &str, extra: Value) -> Value {
    let mut m = Map::new();
    m.insert("t".into(), json!(t));
    m.insert("pid".into(), json!(pid));
    m.insert("type".into(), json!(ty));
    if let Value::Object(e) = extra {
        for (k, v) in e {
            if !v.is_null() {
                m.insert(k, v);
            }
        }
    }
    Value::Object(m)
}

/// The ability side-record `_resolve_ability` logs right after a buy/royal. AGAIN logs
/// unconditionally (and can't be read off the diff — a winning move's victory check
/// RESETS `again` before we see it); the rest are diffed, gated by the card's actual
/// ability so unrelated flows can't alias: privilege → own privilege count (False-grant
/// = no record), take_same → the one emptied board cell (buy/royal touch no other
/// cell), steal → the one opponent token down (payment only moves the ACTOR's tokens).
/// A multi-choice ability sets a pending instead and logs nothing — the diff shows
/// none of these — and a no-target ability is silently ignored.
fn ability_records(
    out: &mut Vec<Value>,
    old: &State,
    new: &State,
    seat: usize,
    ability: u8,
    via: &str,
    mk: &dyn Fn(&str, Value) -> Value,
) {
    if ability == AB_AGAIN {
        out.push(mk("again", json!({"via": via})));
    }
    if ability == AB_PRIVILEGE && new.players[seat].privileges > old.players[seat].privileges {
        out.push(mk("privilege_gain", json!({"via": via})));
    }
    if ability == AB_TAKE_SAME {
        for cell in 0..N_CELLS {
            if old.board[cell] >= 0 && new.board[cell] < 0 {
                out.push(mk("take_same", json!({"color": TOKENS[old.board[cell] as usize],
                    "cell": cell, "via": via})));
            }
        }
    }
    if ability == AB_STEAL {
        let (opp_new, opp_old) = (&new.players[1 - seat].tokens, &old.players[1 - seat].tokens);
        for (c, tok) in TOKENS.iter().enumerate() {
            if opp_new[c] < opp_old[c] {
                out.push(mk("steal", json!({"color": tok, "via": via})));
            }
        }
    }
}

pub fn synth_events(old: &State, new: &State, seat: usize, mv: &Move, pids: [&str; 2]) -> Vec<Value> {
    let pid = pids[seat];
    let opp = 1 - seat;
    let t = old.turn_number;
    let mk = |ty: &str, extra: Value| -> Value { mk_rec(t, pid, ty, extra) };
    let mut out: Vec<Value> = Vec::new();
    let opp_priv_gain = new.players[opp].privileges > old.players[opp].privileges;

    match mv {
        Move::Take { cells } => {
            let colors: Vec<&str> =
                cells.iter().map(|&c| TOKENS[old.board[c] as usize]).collect();
            out.push(mk("take", json!({"cells": cells, "colors": colors,
                "opp_privilege": if opp_priv_gain { json!(true) } else { Value::Null }})));
        }
        Move::UsePrivilege { cell } => {
            out.push(mk("use_privilege",
                json!({"cell": cell, "color": TOKENS[old.board[*cell] as usize]})));
        }
        Move::Replenish => {
            let placed = old.board.iter().filter(|&&t| t < 0).count()
                - new.board.iter().filter(|&&t| t < 0).count();
            out.push(mk("replenish", json!({"count": placed,
                "opp_privilege": if opp_priv_gain { json!(true) } else { Value::Null }})));
        }
        Move::Reserve { gold_cell, src } => match src {
            ReserveSrc::Pyramid { level, slot } => {
                let cid = old.pyramid[*level][*slot];
                out.push(mk("reserve", json!({"level": level + 1, "slot": slot,
                    "card_id": if cid >= 0 { json!(card_id_str(cid as usize)) } else { Value::Null },
                    "gold_cell": gold_cell})));
            }
            ReserveSrc::Deck { level } => {
                out.push(mk("reserve",
                    json!({"level": level + 1, "from_deck": true, "gold_cell": gold_cell})));
            }
        },
        Move::Buy { card, from, as_color } => {
            let mut e = Map::new();
            e.insert("card_id".into(), json!(card_id_str(*card)));
            e.insert(
                "frm".into(),
                json!(if matches!(from, BuySrc::Pyramid) { "pyramid" } else { "reserve" }),
            );
            if *as_color >= 0 {
                e.insert("as_color".into(), json!(COLORS[*as_color as usize]));
            }
            if PTS[*card] > 0 {
                e.insert("points".into(), json!(PTS[*card]));
            }
            if CROWNS[*card] > 0 {
                e.insert("crowns".into(), json!(CROWNS[*card]));
            }
            out.push(mk("buy", Value::Object(e)));
            ability_records(&mut out, old, new, seat, ABILITY[*card], &card_id_str(*card), &mk);
        }
        Move::TakeSame { cell } => {
            let via: Value = match old.pending.via {
                Via::Card(c) => json!(card_id_str(c)),
                Via::Royal(r) => json!(royal_id_str(r)),
                Via::None => Value::Null,
            };
            out.push(mk("take_same", json!({"color": TOKENS[old.pending.color as usize],
                "cell": cell, "via": via})));
        }
        Move::Steal { color } => {
            let via: Value = match old.pending.via {
                Via::Card(c) => json!(card_id_str(c)),
                Via::Royal(r) => json!(royal_id_str(r)),
                Via::None => Value::Null,
            };
            out.push(mk("steal", json!({"color": TOKENS[*color], "via": via})));
        }
        Move::ChooseRoyal { royal } => {
            out.push(mk("royal", json!({"royal_id": royal_id_str(*royal),
                "points": ROYAL_PTS[*royal]})));
            ability_records(
                &mut out, old, new, seat,
                crate::cards::ROYAL_ABILITY[*royal], &royal_id_str(*royal), &mk,
            );
        }
        Move::Discard { color } => {
            out.push(mk("discard", json!({"color": TOKENS[*color]})));
        }
        Move::SkipPending => {
            out.push(mk("skip_pending",
                json!({"kind": KIND_NAMES[old.pending_kind as usize]})));
        }
        Move::Pass => out.push(mk("pass", json!({}))),
    }
    // Extra turn: the seat kept the turn across a turn_number increment — `_finish_turn`
    // saw AGAIN armed (possibly armed by THIS move's ability, so don't test old.again).
    // Logged AFTER the increment in the Python, so its `t` is the NEW turn_number.
    if new.turn_number > old.turn_number && new.turn == old.turn && new.phase != OVER {
        out.push(mk_rec(new.turn_number, pid, "extra_turn", json!({})));
    }
    if new.phase == OVER && old.phase != OVER {
        let mut e = Map::new();
        e.insert(
            "condition".into(),
            match new.win_condition {
                WC_POINTS => json!("points"),
                WC_CROWNS => json!("crowns"),
                WC_COLOR => json!("color"),
                _ => Value::Null,
            },
        );
        if new.win_color >= 0 {
            e.insert("color".into(), json!(COLORS[new.win_color as usize]));
        }
        out.push(mk("game_over", Value::Object(e)));
    }
    out
}

/// Apply an engine-dict OR encmove for `seat` (detected by "type" vs "t"); validates
/// by membership in `legal_moves` (the server's exact policy) and returns the new
/// save JSON plus the synthesized log events. Uses a real rng seeded per call for
/// the (at most one) replenish reshuffle.
pub fn apply_save(
    save_json: &str,
    move_json: &str,
    seat: usize,
    pid0: &str,
    pid1: &str,
    shuffle_seed: u64,
) -> Result<(String, Vec<Value>), String> {
    let mut s = crate::dump::state_from_json(save_json).ok_or("bad save")?;
    let v: Value = serde_json::from_str(move_json).map_err(|_| "bad move json")?;
    let mv = if v.get("type").is_some() {
        parse_engine_move(&v)
    } else {
        parse_encmove(&v)
    }
    .ok_or("unparseable move")?;
    if !s.legal_moves(seat).contains(&mv) {
        return Err("illegal move".into());
    }
    let before = s.clone();
    let mut rng = crate::rng::Rng::new(shuffle_seed);
    struct RngSh<'a>(&'a mut crate::rng::Rng);
    impl<'a> Shuffler for RngSh<'a> {
        fn shuffle(&mut self, bag: &mut Vec<u8>) {
            self.0.shuffle(bag);
        }
    }
    s.apply_move(seat, &mv, &mut RngSh(&mut rng)).map_err(|e| e.to_string())?;
    let events = synth_events(&before, &s, seat, &mv, [pid0, pid1]);
    Ok((crate::dump::state_to_json(&s), events))
}

/// Legal moves for the acting seat as engine dicts: `{"actor": seat|-1, "moves": [...]}`.
pub fn legal_json(save_json: &str) -> Result<Value, String> {
    let s = crate::dump::state_from_json(save_json).ok_or("bad save")?;
    if s.phase == OVER {
        return Ok(json!({"actor": -1, "moves": []}));
    }
    let actor = if s.pending_pid >= 0 { s.pending_pid as usize } else { s.turn };
    let moves: Vec<Value> = s.legal_moves(actor).iter().map(move_to_engine_dict).collect();
    Ok(json!({"actor": actor, "moves": moves}))
}
