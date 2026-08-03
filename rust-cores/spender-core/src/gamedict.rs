//! State → incumbent main.py game-dict JSON — the render shape `Spender.jsx` reads from
//! `roomData.game`. Port of `games/spender/ai/serving/engine.py::to_game_dict`, plus the
//! server's per-viewer blind-reserve redaction (`main.py::_redact_blind_reserves`): a card
//! reserved from a deck top is secret, so the NON-owning viewer sees only
//! `{"hidden":true,"level":L,"id":"<pid>:hidden:<i>"}` until the game is over.
//!
//! Exists for the OFFLINE driver: with no server in the loop, the browser needs the render
//! dict built client-side from the authoritative compact state. Parity with the Python
//! writer is gated by `tests/gamedict_parity.rs` (fixtures from
//! `tools/gen_gamedict_fixtures.py`) — the JSX renders whatever this emits, so a drifted
//! field here is a wrong board on screen.
//!
//! The `moves` key is always `[]`: the move log lives OUTSIDE the compact state (the offline
//! driver maintains it in JS, exactly as main.py maintains it outside engine State).

use crate::cards::{BONUS, COST, LEVEL_OF, NOBLE_PTS, NOBLE_REQ, PTS};
use crate::engine::{State, DISCARD, NOBLE, OVER, WIN_DRAW};
use serde_json::{json, Map, Value};

const COLOR_NAMES: [&str; 5] = ["white", "blue", "green", "red", "black"];

fn gems_obj(v: &[i32; 6]) -> Value {
    let mut m = Map::new();
    for (i, c) in COLOR_NAMES.iter().enumerate() {
        m.insert((*c).into(), json!(v[i]));
    }
    m.insert("gold".into(), json!(v[5]));
    Value::Object(m)
}

/// `{"id":"L1-0","level":1,"points":0,"bonus":"black","cost":{...nonzero colors...}}` —
/// the `cards.py make_card` shape (cost omits zero colors, like the source dicts).
fn card_obj(ci: i32) -> Value {
    let ci = ci as usize;
    let lvl = LEVEL_OF[ci];
    let idx = ci
        - match lvl {
            1 => 0,
            2 => LEVEL_OF.iter().position(|&l| l == 2).unwrap(),
            _ => LEVEL_OF.iter().position(|&l| l == 3).unwrap(),
        };
    let mut cost = Map::new();
    for (i, c) in COLOR_NAMES.iter().enumerate() {
        if COST[ci][i] > 0 {
            cost.insert((*c).into(), json!(COST[ci][i]));
        }
    }
    json!({
        "id": format!("L{lvl}-{idx}"),
        "level": lvl,
        "points": PTS[ci],
        "bonus": COLOR_NAMES[BONUS[ci]],
        "cost": Value::Object(cost),
    })
}

/// `{"id":"n1","points":3,"req":{...nonzero colors...}}` — the `cards.py ALL_NOBLES` shape.
fn noble_obj(ni: i32) -> Value {
    let ni = ni as usize;
    let mut req = Map::new();
    for (i, c) in COLOR_NAMES.iter().enumerate() {
        if NOBLE_REQ[ni][i] > 0 {
            req.insert((*c).into(), json!(NOBLE_REQ[ni][i]));
        }
    }
    json!({
        "id": format!("n{}", ni + 1),
        "points": NOBLE_PTS[ni],
        "req": Value::Object(req),
    })
}

/// Build the incumbent game dict for `s`. `pids` are the two seat ids in seat order
/// (= `game["order"]`). `viewer` is the seat whose view this is (0/1) — the OTHER seat's
/// blind reserves are hidden while the game is running — or -1 for the full unredacted view
/// (parity tests; game over reveals everything regardless, matching the server).
pub fn to_game_dict(s: &State, pids: (&str, &str), viewer: i32) -> Value {
    let pid_of = [pids.0, pids.1];
    let mut game = Map::new();
    game.insert("bank".into(), gems_obj(&s.bank));
    let mut decks = Map::new();
    let mut board = Map::new();
    for lvl in 0..3usize {
        decks.insert(
            format!("L{}", lvl + 1),
            Value::Array(s.decks[lvl].iter().map(|&ci| card_obj(ci)).collect()),
        );
        board.insert(
            format!("L{}", lvl + 1),
            Value::Array(
                (0..4)
                    .map(|i| {
                        let ci = s.board[lvl * 4 + i];
                        if ci >= 0 { card_obj(ci) } else { Value::Null }
                    })
                    .collect(),
            ),
        );
    }
    game.insert("decks".into(), Value::Object(decks));
    game.insert("board".into(), Value::Object(board));
    game.insert(
        "nobles".into(),
        Value::Array(s.nobles.iter().filter(|&&ni| ni >= 0).map(|&ni| noble_obj(ni)).collect()),
    );
    game.insert("order".into(), json!([pid_of[0], pid_of[1]]));
    game.insert("turn".into(), json!(pid_of[s.turn]));
    game.insert(
        "phase".into(),
        json!(if s.phase == OVER { "over" } else { "playing" }),
    );
    game.insert(
        "winner".into(),
        if s.phase == OVER {
            if s.winner == WIN_DRAW {
                json!([pid_of[0], pid_of[1]])
            } else {
                json!(pid_of[s.winner as usize])
            }
        } else {
            Value::Null
        },
    );
    game.insert("moves".into(), json!([]));
    game.insert("win_points".into(), json!(s.win_points));
    if s.final_trigger >= 0 {
        game.insert("final_round_trigger".into(), json!(pid_of[s.final_trigger as usize]));
    }
    if s.phase == DISCARD {
        game.insert("pending_discard_pid".into(), json!(pid_of[s.turn]));
    }
    if s.phase == NOBLE {
        game.insert("pending_noble_pid".into(), json!(pid_of[s.turn]));
        game.insert(
            "pending_noble_choice".into(),
            Value::Array(
                s.pending_nobles
                    .iter()
                    .map(|&slot| json!(format!("n{}", s.nobles[slot] + 1)))
                    .collect(),
            ),
        );
    }

    let mut players = Map::new();
    for seat in 0..2usize {
        // Redact this seat's blind reserves iff a real viewer is given, it's the OTHER
        // seat, and the game is still running — byte-matching _redact_blind_reserves.
        let hide = viewer >= 0 && viewer as usize != seat && s.phase != OVER;
        let reserved: Vec<Value> = s.reserved[seat]
            .iter()
            .enumerate()
            .map(|(ri, &ci)| {
                let blind = s.reserved_blind[seat][ri];
                if blind && hide {
                    json!({
                        "hidden": true,
                        "level": LEVEL_OF[ci as usize],
                        "id": format!("{}:hidden:{}", pid_of[seat], ri),
                    })
                } else if blind {
                    let mut c = card_obj(ci);
                    c.as_object_mut().unwrap().insert("from_deck".into(), json!(true));
                    c
                } else {
                    card_obj(ci)
                }
            })
            .collect();
        players.insert(
            pid_of[seat].to_string(),
            json!({
                "tokens": gems_obj(&s.tokens[seat]),
                "purchased": Value::Array(s.purchased[seat].iter().map(|&ci| card_obj(ci)).collect()),
                "reserved": Value::Array(reserved),
                "nobles": Value::Array(s.nobles_won[seat].iter().map(|&ni| noble_obj(ni)).collect()),
            }),
        );
    }
    game.insert("players".into(), Value::Object(players));
    Value::Object(game)
}

/// JSON-string convenience for the wasm boundary.
pub fn to_game_dict_json(s: &State, pid0: &str, pid1: &str, viewer: i32) -> String {
    serde_json::to_string(&to_game_dict(s, (pid0, pid1), viewer)).expect("game dict serializes")
}
