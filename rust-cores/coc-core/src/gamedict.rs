//! Offline-play surface: the save envelope (State dump + tile-id ledger), the render
//! game-dict writer, per-move log-event synthesis, engine-move-dict → compact-move
//! conversion, legal-move enumeration, and the redacted search projection writer.
//!
//! WHY A LEDGER: `State` deliberately has no tile identity (tiles.rs:3-4) — but the
//! JSX addresses moves by `tile_id` and its flyer animation tracks a tile across
//! containers by a STABLE id. The ledger mirrors every VISIBLE container (depots,
//! black depot, storage, duchies, goods queue, depot goods) with an id per slot,
//! updated after each applied move by code-matched reconciliation: an id follows its
//! tile code from container to container; a code with no donor (a supply emergence —
//! refills) mints a fresh id. Two identical codes swapping ids is harmless — the
//! tiles are indistinguishable, so the animation stays correct. Id prefixes carry
//! blackness ("oh" colored / "ob" black-back / "og" goods) since the code alone
//! can't (a black market shares the code of a colored one).
//!
//! WHY EVENTS: State keeps no move log; the JSX renders `game.moves` and the engine's
//! log is rich (scoring side-effects). `apply_save` synthesizes the primary record
//! from the compact move + diff-derived records (rolls, phase ends, area completions,
//! bonus tiles, livestock scores, track advances, mine income). Anything that can't
//! be labeled unambiguously is omitted rather than mislabeled.

use crate::boards_gen::{N_SPACES, REGION_MASK, REGION_SIZE, SPACE_QR};
use crate::dump::Dump;
use crate::engine::{Micro, Pending, State, NUM_PLAYERS, OVER, PLAYING, SETUP, WIN_DRAW};
use crate::tiles::{
    self, building_type, color_of, livestock_of, monastery_effect, type_of, TileType,
    AREA_SCORE, N_GOODS, PHASE_BONUS, T_START_CASTLE,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};

pub const SPACE_COLORS: [&str; 6] = ["burgundy", "blue", "gray", "green", "beige", "yellow"];
pub const GOODS_COLORS: [&str; 6] = ["amber", "rose", "jade", "cobalt", "plum", "rust"];
pub const ANIMALS: [&str; 4] = ["cow", "sheep", "pig", "chicken"];
pub const BUILDING_NAMES: [&str; 8] =
    ["market", "carpenter", "church", "warehouse", "boarding", "bank", "townhall", "watchtower"];
pub const PHASE_LETTERS: [&str; 5] = ["A", "B", "C", "D", "E"];
const PENDING_KIND_NAMES: [&str; 8] = [
    "", "extra_action", "ship_choose_depot", "ship_adjacent_depot", "goods_pick",
    "building_take_choice", "warehouse_sell", "townhall_place",
];

pub fn space_id_str(sid: usize) -> String {
    let (q, r) = SPACE_QR[sid];
    format!("{q},{r}")
}

pub fn space_index(id: &str) -> Option<usize> {
    (0..N_SPACES).find(|&i| space_id_str(i) == id)
}

// ─── The tile-id ledger ────────────────────────────────────────────────────

#[derive(Serialize, Deserialize, Clone, Default)]
pub struct Ledger {
    pub depot_hex: Vec<Vec<String>>,   // [6][2], "" = empty
    pub black_depot: Vec<String>,      // [4]
    pub storage: Vec<Vec<String>>,     // [2][3]
    pub duchy: Vec<Vec<String>>,       // [2][37]
    pub goods_queue: Vec<String>,      // parallel to goods_queue
    pub depot_goods: Vec<Vec<Vec<String>>>, // [6][color][ids]
    pub next_id: u64,
}

impl Ledger {
    pub fn empty() -> Ledger {
        Ledger {
            depot_hex: vec![vec![String::new(); 2]; 6],
            black_depot: vec![String::new(); 4],
            storage: vec![vec![String::new(); 3]; 2],
            duchy: vec![vec![String::new(); N_SPACES]; 2],
            goods_queue: Vec::new(),
            depot_goods: vec![vec![Vec::new(); N_GOODS]; 6],
            next_id: 1,
        }
    }
    fn mint(&mut self, black: bool) -> String {
        let id = format!("{}{}", if black { "ob" } else { "oh" }, self.next_id);
        self.next_id += 1;
        id
    }
    fn mint_goods(&mut self) -> String {
        let id = format!("og{}", self.next_id);
        self.next_id += 1;
        id
    }
}

/// Every hex-tile position across the visible containers, in a fixed walk order.
/// (kind, a, b): 0=depot_hex(d,slot) 1=black_depot(slot) 2=storage(seat,slot) 3=duchy(seat,sid)
fn hex_positions(s: &State) -> Vec<(u8, usize, usize, u16)> {
    let mut out = Vec::with_capacity(96);
    for d in 0..6 {
        for slot in 0..2 {
            out.push((0, d, slot, s.depot_hex[d][slot]));
        }
    }
    for slot in 0..4 {
        out.push((1, slot, 0, s.black_depot[slot]));
    }
    for seat in 0..2 {
        for slot in 0..3 {
            out.push((2, seat, slot, s.players[seat].storage[slot]));
        }
        for sid in 0..N_SPACES {
            out.push((3, seat, sid, s.players[seat].duchy[sid]));
        }
    }
    out
}

fn ledger_get(l: &Ledger, kind: u8, a: usize, b: usize) -> String {
    match kind {
        0 => l.depot_hex[a][b].clone(),
        1 => l.black_depot[a].clone(),
        2 => l.storage[a][b].clone(),
        _ => l.duchy[a][b].clone(),
    }
}

fn ledger_set(l: &mut Ledger, kind: u8, a: usize, b: usize, id: String) {
    match kind {
        0 => l.depot_hex[a][b] = id,
        1 => l.black_depot[a] = id,
        2 => l.storage[a][b] = id,
        _ => l.duchy[a][b] = id,
    }
}

/// Code-matched id reconciliation between two states (see module header).
pub fn reconcile(old: &State, new: &State, l: &mut Ledger) {
    use std::collections::HashMap;
    let old_pos = hex_positions(old);
    let new_pos = hex_positions(new);
    let mut pool: HashMap<u16, Vec<String>> = HashMap::new();

    // Pass 1: positions whose code changed release their id into the per-code pool.
    for (i, &(kind, a, b, old_code)) in old_pos.iter().enumerate() {
        let new_code = new_pos[i].3;
        if old_code != 0 && old_code != new_code {
            let id = ledger_get(l, kind, a, b);
            if !id.is_empty() {
                pool.entry(old_code).or_default().push(id);
            }
            ledger_set(l, kind, a, b, String::new());
        }
    }
    // Pass 2: positions holding a code without an id adopt from the pool or mint.
    for &(kind, a, b, code) in &new_pos {
        if code == 0 {
            ledger_set(l, kind, a, b, String::new());
            continue;
        }
        if ledger_get(l, kind, a, b).is_empty() {
            let id = pool
                .get_mut(&code)
                .and_then(|v| v.pop())
                .unwrap_or_else(|| {
                    // Fresh emergence: black-backed iff it surfaced in the black depot
                    // (colored refills only enter numbered depots; black monasteries
                    // are flagged by effect id at render time as a belt-and-braces).
                    let black = kind == 1;
                    l.mint(black)
                });
            ledger_set(l, kind, a, b, id);
        }
    }

    // Goods queue: match by color prefix walk (queue only ever pops from the front
    // and refills wholesale at phase boundaries).
    let new_q: Vec<u8> = new.goods_queue[..new.goods_queue_len as usize].to_vec();
    let old_q: Vec<u8> = old.goods_queue[..old.goods_queue_len as usize].to_vec();
    if new_q.len() < old_q.len() && old_q[old_q.len() - new_q.len()..] == new_q[..] {
        // front-pop(s): keep the tail ids
        let drop = old_q.len() - new_q.len();
        l.goods_queue.drain(..drop.min(l.goods_queue.len()));
    } else if new_q != old_q {
        l.goods_queue = new_q.iter().map(|_| l.mint_goods()).collect();
    }
    while l.goods_queue.len() < new_q.len() {
        let id = l.mint_goods();
        l.goods_queue.push(id);
    }
    l.goods_queue.truncate(new_q.len());

    // Depot goods: per (depot,color) count deltas; ids die on decrease, mint on increase.
    for d in 0..6 {
        for c in 0..N_GOODS {
            let n = new.depot_goods[d][c] as usize;
            while l.depot_goods[d][c].len() > n {
                l.depot_goods[d][c].pop();
            }
            while l.depot_goods[d][c].len() < n {
                let id = l.mint_goods();
                l.depot_goods[d][c].push(id);
            }
        }
    }
}

// ─── Save envelope ─────────────────────────────────────────────────────────

#[derive(Serialize, Deserialize)]
pub struct Save {
    pub state: Dump,
    pub ids: Ledger,
}

pub fn save_from_json(save_json: &str) -> Option<(State, Ledger)> {
    let save: Save = serde_json::from_str(save_json).ok()?;
    Some((save.state.into_state(), save.ids))
}

pub fn save_to_json(s: &State, ids: &Ledger) -> String {
    serde_json::to_string(&Save { state: Dump::from_state(s), ids: ids.clone() })
        .expect("save serializes")
}

pub fn new_game_save(board0: u8, board1: u8, seed: u64) -> String {
    let s = State::new_game([board0, board1], seed);
    let mut ids = Ledger::empty();
    reconcile(&State::shell([board0, board1]), &s, &mut ids);
    save_to_json(&s, &ids)
}

// ─── Tile objects ──────────────────────────────────────────────────────────

fn tile_obj(code: u16, id: &str) -> Value {
    let t = type_of(code);
    let mut m = Map::new();
    m.insert("id".into(), json!(id));
    m.insert("kind".into(), json!("hex"));
    m.insert(
        "type".into(),
        json!(match t {
            TileType::Castle => "castle",
            TileType::Ship => "ship",
            TileType::Mine => "mine",
            TileType::Livestock => "livestock",
            TileType::Building => "building",
            TileType::Monastery => "monastery",
        }),
    );
    m.insert("color".into(), json!(SPACE_COLORS[color_of(code) as usize]));
    match t {
        TileType::Building => {
            m.insert("building".into(), json!(BUILDING_NAMES[building_type(code) as usize]));
        }
        TileType::Livestock => {
            let (animal, count) = livestock_of(code);
            m.insert("animal".into(), json!(ANIMALS[animal as usize]));
            m.insert("count".into(), json!(count));
        }
        TileType::Monastery => {
            let eid = monastery_effect(code);
            m.insert("effect_id".into(), json!(eid));
            if eid >= 21 {
                m.insert("black".into(), json!(true));
            }
        }
        _ => {}
    }
    if code == T_START_CASTLE {
        m.insert("starting".into(), json!(true));
    }
    if id.starts_with("ob") {
        m.insert("black".into(), json!(true));
    }
    Value::Object(m)
}

fn goods_obj(color: usize, id: &str) -> Value {
    json!({"id": id, "kind": "goods", "color": GOODS_COLORS[color]})
}

// ─── The render game dict (wire shape: the engine dict minus _HIDE) ────────

pub fn to_game_dict(s: &State, ids: &Ledger, pids: [&str; 2], names: [&str; 2]) -> Value {
    let pid_of = |seat: i8| -> Value {
        if seat < 0 { Value::Null } else { json!(pids[seat as usize]) }
    };
    let mut g = Map::new();
    g.insert("num_players".into(), json!(NUM_PLAYERS));
    g.insert("phase_letter".into(), json!(PHASE_LETTERS[s.phase as usize]));
    g.insert("round".into(), json!(s.round));
    g.insert(
        "phase".into(),
        json!(match s.mode {
            SETUP => "setup",
            OVER => "over",
            _ => "playing",
        }),
    );
    g.insert(
        "winner".into(),
        if s.mode == OVER {
            if s.winner == WIN_DRAW {
                json!([pids[0], pids[1]])
            } else if s.winner >= 0 {
                json!(pids[s.winner as usize])
            } else {
                Value::Null
            }
        } else {
            Value::Null
        },
    );
    g.insert("order".into(), json!([pids[0], pids[1]]));
    // Track stacks bottom→top per space; with 2 players, positions + top seat fully
    // determine them (stacked ⇒ non-top below, track_top above).
    let mut track: Vec<Vec<&str>> = vec![Vec::new(); 7];
    if s.track_pos[0] == s.track_pos[1] {
        let top = if s.track_top >= 0 { s.track_top as usize } else { 0 };
        track[s.track_pos[0] as usize] = vec![pids[1 - top], pids[top]];
    } else {
        track[s.track_pos[0] as usize] = vec![pids[0]];
        track[s.track_pos[1] as usize] = vec![pids[1]];
    }
    g.insert("track".into(), json!(track));
    g.insert(
        "round_order".into(),
        json!([pids[s.round_order[0] as usize], pids[s.round_order[1] as usize]]),
    );
    g.insert("ship_advance_pending".into(), json!(0));
    g.insert("start_player".into(), json!(pids[s.start_player as usize]));
    g.insert(
        "white_die".into(),
        if s.white_die == 0 { Value::Null } else { json!(s.white_die) },
    );
    let mut dice = Map::new();
    if s.mode != SETUP && s.white_die != 0 {
        for seat in 0..2 {
            let d = &s.dice[seat];
            dice.insert(
                pids[seat].to_string(),
                json!({
                    "values": [d[0].value, d[1].value],
                    "orig": [d[0].orig, d[1].orig],
                    "used": [d[0].used, d[1].used],
                    "adjusted": [d[0].adjusted, d[1].adjusted],
                }),
            );
        }
    }
    g.insert("dice".into(), Value::Object(dice));
    g.insert("turn".into(), pid_of(s.turn));
    g.insert("black_depot_used_this_turn".into(), json!(s.black_used));
    g.insert("m6_used_this_turn".into(), json!(s.m6_used));

    let mut depots = Map::new();
    for d in 0..6 {
        let hexes: Vec<Value> = (0..2)
            .filter(|&slot| s.depot_hex[d][slot] != 0)
            .map(|slot| tile_obj(s.depot_hex[d][slot], &ids.depot_hex[d][slot]))
            .collect();
        let mut goods: Vec<Value> = Vec::new();
        for c in 0..N_GOODS {
            for id in &ids.depot_goods[d][c] {
                goods.push(goods_obj(c, id));
            }
        }
        depots.insert((d + 1).to_string(), json!({"hexes": hexes, "goods": goods}));
    }
    g.insert("depots".into(), Value::Object(depots));
    g.insert(
        "black_depot".into(),
        Value::Array(
            (0..4)
                .filter(|&slot| s.black_depot[slot] != 0)
                .map(|slot| tile_obj(s.black_depot[slot], &ids.black_depot[slot]))
                .collect(),
        ),
    );
    g.insert(
        "goods_queue".into(),
        Value::Array(
            (0..s.goods_queue_len as usize)
                .map(|i| goods_obj(s.goods_queue[i] as usize, &ids.goods_queue[i]))
                .collect(),
        ),
    );
    // Color bonuses are for completing all SPACES of a color — keyed by the board
    // colors (bonus_left indexes COLOR_MASK), not the goods colors.
    let mut bonus = Map::new();
    for c in 0..N_GOODS {
        let vals: Vec<i16> = match s.bonus_left[c] {
            2 => vec![tiles::bonus_first(NUM_PLAYERS), tiles::bonus_second(NUM_PLAYERS)],
            1 => vec![tiles::bonus_second(NUM_PLAYERS)],
            _ => vec![],
        };
        bonus.insert(SPACE_COLORS[c].to_string(), json!(vals));
    }
    g.insert("bonus_tiles".into(), Value::Object(bonus));

    let mut players = Map::new();
    for seat in 0..2 {
        let p = &s.players[seat];
        let mut duchy = Map::new();
        for sid in 0..N_SPACES {
            duchy.insert(
                space_id_str(sid),
                if p.duchy[sid] != 0 {
                    tile_obj(p.duchy[sid], &ids.duchy[seat][sid])
                } else {
                    Value::Null
                },
            );
        }
        let storage: Vec<Value> = (0..3)
            .filter(|&slot| p.storage[slot] != 0)
            .map(|slot| tile_obj(p.storage[slot], &ids.storage[seat][slot]))
            .collect();
        let mut goods = Map::new();
        for c in 0..N_GOODS {
            if p.goods[c] > 0 {
                goods.insert(GOODS_COLORS[c].to_string(), json!(p.goods[c]));
            }
        }
        let mut sold: Vec<&str> = Vec::new();
        for c in 0..N_GOODS {
            for _ in 0..p.sold[c] {
                sold.push(GOODS_COLORS[c]);
            }
        }
        let claimed: Vec<Value> = (0..N_GOODS)
            .filter(|&c| p.bonus_vp[c] > 0)
            .map(|c| json!({"color": GOODS_COLORS[c], "vp": p.bonus_vp[c]}))
            .collect();
        let mut buildings = Map::new();
        for b in 0..8 {
            buildings.insert(BUILDING_NAMES[b].to_string(), json!(p.buildings[b]));
        }
        let livestock: Vec<&str> = (0..4)
            .filter(|&a| p.livestock_mask >> a & 1 == 1)
            .map(|a| ANIMALS[a])
            .collect();
        let effects: Vec<u8> = (0..26).filter(|&e| p.mon_mask >> e & 1 == 1).map(|e| e + 1).collect();
        players.insert(
            pids[seat].to_string(),
            json!({
                "name": names[seat],
                "board_id": (s.boards[seat] + 1).to_string(),
                "castle_sid": if p.castle_sid as usize >= N_SPACES { Value::Null }
                              else { json!(space_id_str(p.castle_sid as usize)) },
                "duchy": Value::Object(duchy),
                "storage": storage,
                "goods": Value::Object(goods),
                "sold_goods": sold,
                "workers": p.workers,
                "silver": p.silver,
                "vp": p.vp,
                "claimed_bonus": claimed,
                "mines_count": p.mines,
                "buildings_placed": Value::Object(buildings),
                "livestock_types": livestock,
                "monastery_effects": effects,
                "town_buildings": {},
            }),
        );
    }
    g.insert("players".into(), Value::Object(players));

    g.insert("pending_pid".into(), pid_of(s.pending_pid));
    let kind_tag = match s.pending {
        Pending::None => 0,
        Pending::ExtraAction => 1,
        Pending::ShipChoose => 2,
        Pending::ShipAdj { .. } => 3,
        Pending::GoodsPick { .. } => 4,
        Pending::BuildingTake { .. } => 5,
        Pending::Warehouse => 6,
        Pending::Townhall => 7,
    };
    if kind_tag == 0 {
        g.insert("pending_kind".into(), Value::Null);
        g.insert("pending".into(), Value::Null);
    } else {
        let kind = PENDING_KIND_NAMES[kind_tag];
        let ctx: Value = match s.pending {
            Pending::ExtraAction => json!({"source": "castle"}),
            Pending::ShipChoose => json!({}),
            Pending::ShipAdj { cands } => {
                let list: Vec<usize> = (0..6).filter(|&d| cands >> d & 1 == 1).map(|d| d + 1).collect();
                json!({"candidates": list})
            }
            Pending::GoodsPick { depot, colors, m5_from } => {
                let list: Vec<&str> =
                    (0..N_GOODS).filter(|&c| colors >> c & 1 == 1).map(|c| GOODS_COLORS[c]).collect();
                json!({"depot": depot + 1, "colors": list,
                       "m5_from": if m5_from < 0 { Value::Null } else { json!(m5_from + 1) }})
            }
            Pending::BuildingTake { types } => {
                let mut cands: Vec<String> = Vec::new();
                for d in 0..6 {
                    for slot in 0..2 {
                        let code = s.depot_hex[d][slot];
                        if code != 0 && types >> color_of(code) & 1 == 1 {
                            cands.push(ids.depot_hex[d][slot].clone());
                        }
                    }
                }
                let type_names: Vec<&str> = ["castle", "ship", "mine", "livestock", "building", "monastery"]
                    .iter()
                    .enumerate()
                    .filter(|(i, _)| types >> i & 1 == 1)
                    .map(|(_, n)| *n)
                    .collect();
                // The triggering building is uniquely determined by its take-set:
                // market={ship,livestock}, carpenter={building}, church={castle,mine,monastery}.
                let building = if types >> (TileType::Building as u8) & 1 == 1 {
                    "carpenter"
                } else if types >> (TileType::Ship as u8) & 1 == 1 {
                    "market"
                } else {
                    "church"
                };
                json!({"building": building, "types": type_names, "candidates": cands})
            }
            Pending::Warehouse => json!({"building": "warehouse"}),
            Pending::Townhall => json!({"building": "townhall"}),
            Pending::None => unreachable!(),
        };
        g.insert("pending_kind".into(), json!(kind));
        g.insert(
            "pending".into(),
            json!({"pid": pid_of(s.pending_pid), "kind": kind, "ctx": ctx}),
        );
    }
    g.insert("moves".into(), json!([]));
    Value::Object(g)
}

// ─── The redacted search projection (ai_search.state) ──────────────────────

/// Mirror of `az_compact.project(game)` + the caller's pool sort (main.py:598-599):
/// exact everything except the three hidden pools, which ship SORTED (the search
/// re-shuffles them every determinization; order is the secret).
pub fn to_proj(s: &State) -> Value {
    let mut p = Map::new();
    p.insert("boards".into(), json!([s.boards[0], s.boards[1]]));
    p.insert("phase".into(), json!(s.phase));
    p.insert("round".into(), json!(s.round));
    p.insert("mode".into(), json!(s.mode));
    p.insert("winner".into(), json!(s.winner));
    p.insert("track_pos".into(), json!([s.track_pos[0], s.track_pos[1]]));
    p.insert("track_top".into(), json!(s.track_top));
    p.insert("round_order".into(), json!([s.round_order[0], s.round_order[1]]));
    p.insert("start_player".into(), json!(s.start_player));
    p.insert("turn".into(), json!(s.turn));
    p.insert("white_die".into(), json!(s.white_die));
    let dice: Vec<Vec<Vec<i64>>> = (0..2)
        .map(|seat| {
            (0..2)
                .map(|die| {
                    let d = s.dice[seat][die];
                    vec![d.value as i64, d.orig as i64, d.used as i64, d.adjusted as i64]
                })
                .collect()
        })
        .collect();
    p.insert("dice".into(), json!(dice));
    p.insert("black_used".into(), json!(s.black_used as u8));
    p.insert("m6_used".into(), json!(s.m6_used as u8));
    p.insert("depot_hex".into(), json!(s.depot_hex.iter().map(|d| d.to_vec()).collect::<Vec<_>>()));
    p.insert(
        "depot_goods".into(),
        json!(s.depot_goods.iter().map(|d| d.to_vec()).collect::<Vec<_>>()),
    );
    p.insert("black_depot".into(), json!(s.black_depot.to_vec()));
    let mut supply = s.supply[..s.supply_len as usize].to_vec();
    supply.sort_unstable();
    let mut black_supply = s.black_supply[..s.black_supply_len as usize].to_vec();
    black_supply.sort_unstable();
    let mut goods_supply = s.goods_supply[..s.goods_supply_len as usize].to_vec();
    goods_supply.sort_unstable();
    p.insert("supply".into(), json!(supply));
    p.insert("black_supply".into(), json!(black_supply));
    p.insert("goods_supply".into(), json!(goods_supply));
    p.insert("goods_queue".into(), json!(s.goods_queue[..s.goods_queue_len as usize].to_vec()));
    p.insert("bonus_left".into(), json!(s.bonus_left.to_vec()));
    let players: Vec<Value> = (0..2)
        .map(|seat| {
            let ps = &s.players[seat];
            json!({
                "duchy": ps.duchy.to_vec(),
                "castle_sid": ps.castle_sid,
                "storage": ps.storage.to_vec(),
                "goods": ps.goods.to_vec(),
                "sold": ps.sold.to_vec(),
                "workers": ps.workers,
                "silver": ps.silver,
                "vp": ps.vp,
                "bonus_claimed": ps.bonus_claimed,
                "mines": ps.mines,
                "buildings": ps.buildings.to_vec(),
                "livestock_mask": ps.livestock_mask,
                "mon_mask": ps.mon_mask,
                "town_bldg": ps.town_bldg.to_vec(),
                "board": s.boards[seat],
            })
        })
        .collect();
    p.insert("players".into(), json!(players));
    p.insert("pending_pid".into(), json!(s.pending_pid));
    let (tag, fields): (i64, Vec<i64>) = match s.pending {
        Pending::None => (0, vec![]),
        Pending::ExtraAction => (1, vec![]),
        Pending::ShipChoose => (2, vec![]),
        Pending::ShipAdj { cands } => (3, vec![cands as i64]),
        Pending::GoodsPick { depot, colors, m5_from } => {
            (4, vec![depot as i64, colors as i64, m5_from as i64])
        }
        Pending::BuildingTake { types } => (5, vec![types as i64]),
        Pending::Warehouse => (6, vec![]),
        Pending::Townhall => (7, vec![]),
    };
    p.insert("pending_tag".into(), json!(tag));
    p.insert("pending_fields".into(), json!(fields));
    Value::Object(p)
}

// ─── Engine-move dict → compact move ───────────────────────────────────────

fn find_depot_slot(s: &State, ids: &Ledger, tile_id: &str, depot1: Option<usize>) -> Option<(usize, usize)> {
    for d in 0..6 {
        if let Some(want) = depot1 {
            if d + 1 != want {
                continue;
            }
        }
        for slot in 0..2 {
            if s.depot_hex[d][slot] != 0 && ids.depot_hex[d][slot] == tile_id {
                return Some((d, slot));
            }
        }
    }
    None
}

fn find_storage_slot(s: &State, ids: &Ledger, seat: usize, tile_id: &str) -> Option<usize> {
    (0..3).find(|&slot| s.players[seat].storage[slot] != 0 && ids.storage[seat][slot] == tile_id)
}

fn goods_index(name: &str) -> Option<usize> {
    GOODS_COLORS.iter().position(|&c| c == name)
}

/// Convert the JSX's engine-style move dict to the compact shape (`{"t": ...}`).
/// `seat` is the mover (tile lookups in storage are per-seat).
pub fn engine_move_to_compact(
    s: &State,
    ids: &Ledger,
    seat: usize,
    mv: &Value,
) -> Result<Value, String> {
    let ty = mv.get("type").and_then(|v| v.as_str()).ok_or("move has no type")?;
    let die = || mv.get("die_index").and_then(|v| v.as_i64()).unwrap_or(0);
    let tile = || mv.get("tile_id").and_then(|v| v.as_str()).unwrap_or("");
    let space = || -> Result<usize, String> {
        let sid = mv.get("space_id").and_then(|v| v.as_str()).ok_or("no space_id")?;
        space_index(sid).ok_or_else(|| format!("unknown space {sid}"))
    };
    Ok(match ty {
        "end_turn" => json!({"t": "end"}),
        "skip_pending" => json!({"t": "skip"}),
        "monastery6_take" => json!({"t": "m6"}),
        "place_starting_castle" => json!({"t": "castle", "space": space()?}),
        "take_hex" => {
            let want = mv.get("depot").and_then(|v| v.as_u64()).map(|d| d as usize);
            let (d, slot) =
                find_depot_slot(s, ids, tile(), want).ok_or("tile not in that depot")?;
            json!({"t": "take_hex", "die": die(), "depot": d, "slot": slot})
        }
        "place_tile" => {
            let slot = find_storage_slot(s, ids, seat, tile()).ok_or("tile not in storage")?;
            json!({"t": "place", "die": die(), "slot": slot, "space": space()?})
        }
        "sell_goods" => json!({"t": "sell", "die": die()}),
        "take_workers" => json!({"t": "workers", "die": die()}),
        "adjust_die" => json!({"t": "adjust", "die": die(),
                               "to": mv.get("to").and_then(|v| v.as_i64()).unwrap_or(1)}),
        "buy_black" => {
            let slot = (0..4)
                .find(|&i| s.black_depot[i] != 0 && ids.black_depot[i] == tile())
                .ok_or("tile not in black depot")?;
            json!({"t": "black", "slot": slot})
        }
        "discard_storage" => {
            let slot = find_storage_slot(s, ids, seat, tile()).ok_or("tile not in storage")?;
            json!({"t": "discard", "slot": slot})
        }
        "building_take_choice" => {
            let (d, slot) = find_depot_slot(s, ids, tile(), None).ok_or("tile not in a depot")?;
            json!({"t": "btake", "depot": d, "slot": slot})
        }
        "ship_take_goods" => json!({"t": "ship",
            "depot": mv.get("depot").and_then(|v| v.as_i64()).unwrap_or(1) - 1}),
        "ship_adjacent_take" => json!({"t": "ship_adj",
            "depot": mv.get("depot").and_then(|v| v.as_i64()).unwrap_or(1) - 1}),
        "goods_pick" => json!({"t": "pick",
            "color": goods_index(mv.get("color").and_then(|v| v.as_str()).unwrap_or(""))
                .ok_or("bad color")?}),
        "warehouse_sell" => json!({"t": "wh",
            "color": goods_index(mv.get("color").and_then(|v| v.as_str()).unwrap_or(""))
                .ok_or("bad color")?}),
        "townhall_place" => {
            let slot = find_storage_slot(s, ids, seat, tile()).ok_or("tile not in storage")?;
            json!({"t": "townhall", "slot": slot, "space": space()?})
        }
        "extra_action" => {
            let value = mv.get("value").and_then(|v| v.as_i64()).ok_or("extra needs value")?;
            let sub = mv.get("sub").ok_or("extra needs sub")?;
            let sub_ty = sub.get("type").and_then(|v| v.as_str()).ok_or("sub has no type")?;
            let csub = match sub_ty {
                "take_workers" => json!({"t": "workers"}),
                "sell_goods" => json!({"t": "sell"}),
                "take_hex" => {
                    let want = sub.get("depot").and_then(|v| v.as_u64()).map(|d| d as usize);
                    let tid = sub.get("tile_id").and_then(|v| v.as_str()).unwrap_or("");
                    let (d, slot) =
                        find_depot_slot(s, ids, tid, want).ok_or("sub tile not in depot")?;
                    json!({"t": "take_hex", "depot": d, "slot": slot})
                }
                "place_tile" => {
                    let tid = sub.get("tile_id").and_then(|v| v.as_str()).unwrap_or("");
                    let slot =
                        find_storage_slot(s, ids, seat, tid).ok_or("sub tile not in storage")?;
                    let sid = sub.get("space_id").and_then(|v| v.as_str()).ok_or("no space_id")?;
                    let sp = space_index(sid).ok_or("unknown space")?;
                    json!({"t": "place", "slot": slot, "space": sp})
                }
                other => return Err(format!("bad extra sub {other}")),
            };
            json!({"t": "extra", "value": value, "sub": csub})
        }
        other => return Err(format!("unknown move type {other}")),
    })
}

// ─── Legal-move enumeration (complete chains → compact moves) ──────────────

/// All legal ENGINE moves at a boundary, as compact dicts — the equivalent of
/// `engine.legal_moves`. DFS over `legal_actions_full` until each chain returns to
/// `Micro::None` (depth ≤ 3). Clones are cheap (State is almost `Copy`).
pub fn legal_compact_moves(s: &State) -> Vec<Value> {
    let mut out = Vec::new();
    if s.mode == OVER || s.micro != Micro::None {
        return out;
    }
    let mut chain: Vec<usize> = Vec::new();
    dfs(s, s, &mut chain, &mut out);
    return out;

    fn dfs(root: &State, s: &State, chain: &mut Vec<usize>, out: &mut Vec<Value>) {
        for a in crate::engine::legal_actions_full(s) {
            let mut child = s.clone();
            crate::engine::apply(&mut child, a);
            chain.push(a);
            if child.micro == Micro::None {
                let compact = crate::actions::chain_to_compact(root, chain);
                if let Ok(v) = serde_json::from_str::<Value>(&compact) {
                    out.push(v);
                }
            } else {
                dfs(root, &child, chain, out);
            }
            chain.pop();
        }
    }
}

// ─── Apply (with ledger + events) ──────────────────────────────────────────

fn depot1(v: &Value, key: &str) -> i64 {
    v.get(key).and_then(|x| x.as_i64()).unwrap_or(0) + 1
}

/// Apply one compact move for `seat`; returns the events synthesized for the log
/// (oldest→newest; the JS driver prepends them reversed). Validates that `seat` is
/// the acting seat and that every micro step is in `legal_actions_full`.
pub fn apply_compact(
    s: &mut State,
    ids: &mut Ledger,
    seat: usize,
    compact: &Value,
    pids: [&str; 2],
) -> Result<Vec<Value>, String> {
    if s.mode == OVER {
        return Err("game is over".into());
    }
    if s.actor() != seat as i8 {
        return Err("not your turn".into());
    }
    let chain = crate::actions::compact_to_actions(compact);
    if chain.is_empty() {
        return Err("empty chain".into());
    }
    let before = s.clone();
    for &a in &chain {
        if !crate::engine::legal_actions_full(s).contains(&a) {
            *s = before;
            return Err("illegal move".into());
        }
        crate::engine::apply(s, a);
    }
    if s.micro != Micro::None {
        *s = before;
        return Err("incomplete move chain".into());
    }
    let events = synth_events(&before, s, ids, seat, compact, pids);
    reconcile(&before, s, ids);
    Ok(events)
}

/// Diff-derived log records (see module header). Tile objects are looked up in the
/// PRE-move ledger so the record shows the tile where the player saw it.
fn synth_events(
    old: &State,
    new: &State,
    ids: &Ledger,
    seat: usize,
    c: &Value,
    pids: [&str; 2],
) -> Vec<Value> {
    let pid = pids[seat];
    let ph = PHASE_LETTERS[old.phase as usize];
    let rd = old.round;
    let stamp = |mut m: Map<String, Value>| -> Value {
        m.insert("ph".into(), json!(ph));
        m.insert("rd".into(), json!(rd));
        Value::Object(m)
    };
    let mk = |ty: &str, extra: Value| -> Value {
        let mut m = Map::new();
        m.insert("pid".into(), json!(pid));
        m.insert("type".into(), json!(ty));
        if let Value::Object(e) = extra {
            for (k, v) in e {
                m.insert(k, v);
            }
        }
        stamp(m)
    };
    let t = c.get("t").and_then(|v| v.as_str()).unwrap_or("");
    let mut out: Vec<Value> = Vec::new();
    let p_old = &old.players[seat];
    let p_new = &new.players[seat];
    let vp_delta = (p_new.vp - p_old.vp) as i64;

    // The primary record.
    match t {
        "end" => out.push(mk("end_turn", json!({}))),
        "skip" => {
            let kind = match old.pending {
                Pending::ExtraAction => "extra_action",
                Pending::ShipChoose => "ship_choose_depot",
                Pending::ShipAdj { .. } => "ship_adjacent_depot",
                Pending::GoodsPick { .. } => "goods_pick",
                Pending::BuildingTake { .. } => "building_take_choice",
                Pending::Warehouse => "warehouse_sell",
                Pending::Townhall => "townhall_place",
                Pending::None => "",
            };
            out.push(mk("skip_pending", json!({"kind": kind})));
        }
        "m6" => out.push(mk("monastery6_take", json!({"via": "monastery"}))),
        "castle" => {
            if let Some(sp) = c.get("space").and_then(|v| v.as_u64()) {
                out.push(mk("place_starting_castle", json!({"space_id": space_id_str(sp as usize)})));
            }
        }
        "take_hex" | "btake" => {
            let d = c.get("depot").and_then(|v| v.as_u64()).unwrap_or(0) as usize;
            let slot = c.get("slot").and_then(|v| v.as_u64()).unwrap_or(0) as usize;
            let code = old.depot_hex[d][slot];
            if code != 0 {
                let tile = tile_obj(code, &ids.depot_hex[d][slot]);
                if t == "btake" {
                    out.push(mk("building_take", json!({"tile": tile, "via": "building"})));
                } else {
                    out.push(mk("take_hex", json!({"tile": tile, "depot": d + 1})));
                }
            }
        }
        "place" | "townhall" => {
            let slot = c.get("slot").and_then(|v| v.as_u64()).unwrap_or(0) as usize;
            let sp = c.get("space").and_then(|v| v.as_u64()).unwrap_or(0) as usize;
            let code = old.players[seat].storage[slot];
            if code != 0 {
                let tile = tile_obj(code, &ids.storage[seat][slot]);
                let mut extra = json!({"tile": tile, "space_id": space_id_str(sp)});
                if t == "townhall" {
                    extra["via"] = json!("townhall");
                }
                out.push(mk("place_tile", extra));
            }
        }
        "sell" => {
            let die = c.get("die").and_then(|v| v.as_i64()).unwrap_or(0) as usize;
            let color = old.dice[seat][die].value.max(1) as usize - 1;
            let count = p_old.goods[color] as i64;
            out.push(mk("sell_goods",
                json!({"color": GOODS_COLORS[color], "count": count, "vp": vp_delta})));
        }
        "wh" => {
            if let Some(color) = c.get("color").and_then(|v| v.as_u64()) {
                let count = p_old.goods[color as usize] as i64;
                out.push(mk("sell_goods", json!({"color": GOODS_COLORS[color as usize],
                    "count": count, "vp": vp_delta, "via": "warehouse"})));
            }
        }
        "workers" => out.push(mk("take_workers", json!({}))),
        "adjust" => {
            let die = c.get("die").and_then(|v| v.as_i64()).unwrap_or(0) as usize;
            out.push(mk("adjust_die", json!({
                "die_index": die,
                "frm": old.dice[seat][die].value,
                "to": c.get("to").and_then(|v| v.as_i64()).unwrap_or(0),
                "workers": (p_old.workers - p_new.workers).max(0),
            })));
        }
        "black" => {
            let slot = c.get("slot").and_then(|v| v.as_u64()).unwrap_or(0) as usize;
            let code = old.black_depot[slot];
            if code != 0 {
                out.push(mk("buy_black", json!({"tile": tile_obj(code, &ids.black_depot[slot])})));
            }
        }
        "discard" => {
            let slot = c.get("slot").and_then(|v| v.as_u64()).unwrap_or(0) as usize;
            let code = old.players[seat].storage[slot];
            if code != 0 {
                out.push(mk("discard_storage", json!({"tile": tile_obj(code, &ids.storage[seat][slot])})));
            }
        }
        "ship" => out.push(mk("ship_take_goods", json!({"depot": depot1(c, "depot"), "via": "ship"}))),
        "ship_adj" => {
            out.push(mk("ship_adjacent_take", json!({"depot": depot1(c, "depot"), "via": "monastery"})))
        }
        "pick" => {
            if let Some(color) = c.get("color").and_then(|v| v.as_u64()) {
                let d = if let Pending::GoodsPick { depot, .. } = old.pending {
                    depot as i64 + 1
                } else {
                    0
                };
                out.push(mk("goods_pick", json!({"color": GOODS_COLORS[color as usize], "depot": d})));
            }
        }
        "extra" => {
            // Log the SUB action with via:"castle" (matches _r_extra_action's records).
            if let Some(sub) = c.get("sub") {
                let st = sub.get("t").and_then(|v| v.as_str()).unwrap_or("");
                match st {
                    "workers" => out.push(mk("take_workers", json!({"via": "castle"}))),
                    "sell" => out.push(mk("sell_goods", json!({"vp": vp_delta, "via": "castle"}))),
                    "take_hex" => {
                        let d = sub.get("depot").and_then(|v| v.as_u64()).unwrap_or(0) as usize;
                        let slot = sub.get("slot").and_then(|v| v.as_u64()).unwrap_or(0) as usize;
                        let code = old.depot_hex[d][slot];
                        if code != 0 {
                            out.push(mk("take_hex", json!({"tile": tile_obj(code, &ids.depot_hex[d][slot]),
                                "depot": d + 1, "via": "castle"})));
                        }
                    }
                    "place" => {
                        let slot = sub.get("slot").and_then(|v| v.as_u64()).unwrap_or(0) as usize;
                        let sp = sub.get("space").and_then(|v| v.as_u64()).unwrap_or(0) as usize;
                        let code = old.players[seat].storage[slot];
                        if code != 0 {
                            out.push(mk("place_tile", json!({"tile": tile_obj(code, &ids.storage[seat][slot]),
                                "space_id": space_id_str(sp), "via": "castle"})));
                        }
                    }
                    _ => {}
                }
            }
        }
        _ => {}
    }

    // Region completions (mover only): regions fully filled now but not before.
    let b = old.boards[seat] as usize;
    let mut seen: Vec<usize> = Vec::new();
    for region in 0..crate::boards_gen::N_REGIONS[b] as usize {
        let rmask = REGION_MASK[b][region];
        if p_old.filled & rmask != rmask && p_new.filled & rmask == rmask && !seen.contains(&region) {
            seen.push(region);
            let size = REGION_SIZE[b][region] as i64;
            out.push(mk("area_complete", json!({
                "region": region, "size": size,
                "vp": (AREA_SCORE[size as usize - 1] + PHASE_BONUS[old.phase as usize]) as i64,
            })));
        }
    }
    // Color-bonus claims (bonus_left decrement attributable to the mover).
    for color in 0..N_GOODS {
        if new.bonus_left[color] < old.bonus_left[color] && p_new.bonus_vp[color] > p_old.bonus_vp[color] {
            out.push(mk("bonus_tile", json!({
                "color": GOODS_COLORS[color],
                "vp": p_new.bonus_vp[color],
                "large": old.bonus_left[color] == 2,
            })));
        }
    }
    // Livestock scoring: a placed livestock tile whose VP gain exceeds area/bonus.
    if t == "place" || (t == "extra" && c["sub"]["t"] == json!("place")) {
        let slot_v = if t == "place" { &c["slot"] } else { &c["sub"]["slot"] };
        if let Some(slot) = slot_v.as_u64() {
            let code = p_old.storage[slot as usize];
            if code != 0 && type_of(code) == TileType::Livestock {
                let (animal, _) = livestock_of(code);
                let side_vp: i64 = out.iter()
                    .filter(|e| e["type"] == json!("area_complete") || e["type"] == json!("bonus_tile"))
                    .map(|e| e["vp"].as_i64().unwrap_or(0))
                    .sum();
                let gain = vp_delta - side_vp;
                if gain > 0 {
                    out.push(mk("livestock_score",
                        json!({"animal": ANIMALS[animal as usize], "vp": gain})));
                }
            }
        }
    }
    // Track advance for the mover.
    let moved = new.track_pos[seat] as i64 - old.track_pos[seat] as i64;
    if moved > 0 {
        out.push(mk("track_advance", json!({"spaces": moved})));
    }
    // Phase boundary: mine income (any player with mines) + the phase_end marker.
    if new.phase != old.phase || (new.mode == OVER && old.mode == PLAYING) {
        for st in 0..2 {
            let mines = old.players[st].mines;
            if mines > 0 {
                let mut m = Map::new();
                m.insert("pid".into(), json!(pids[st]));
                m.insert("type".into(), json!("mine_income"));
                m.insert("silver".into(), json!(mines));
                m.insert("mines".into(), json!(mines));
                out.push(stamp(m));
            }
        }
        let mut m = Map::new();
        m.insert("pid".into(), Value::Null);
        m.insert("type".into(), json!("phase_end"));
        m.insert("phase".into(), json!(ph));
        out.push(stamp(m));
    }
    // New round rolled: emit a roll record per player (values from the fresh dice).
    let rolled = new.white_die != 0
        && (old.white_die != new.white_die
            || new.round != old.round
            || new.phase != old.phase
            || (0..2).any(|st| {
                new.dice[st][0].orig != old.dice[st][0].orig
                    || new.dice[st][1].orig != old.dice[st][1].orig
            }))
        && (t == "end" || old.mode == SETUP);
    if rolled && new.mode == PLAYING {
        for st in 0..2 {
            let mut m = Map::new();
            m.insert("pid".into(), json!(pids[st]));
            m.insert("type".into(), json!("roll"));
            m.insert("d0".into(), json!(new.dice[st][0].orig));
            m.insert("d1".into(), json!(new.dice[st][1].orig));
            m.insert("ph".into(), json!(PHASE_LETTERS[new.phase as usize]));
            m.insert("rd".into(), json!(new.round));
            out.push(Value::Object(m));
        }
    }
    out
}

/// Apply an engine-style OR compact move dict (detected by "type" vs "t" key).
pub fn apply_save(
    save_json: &str,
    move_json: &str,
    seat: usize,
    pid0: &str,
    pid1: &str,
) -> Result<(String, Vec<Value>), String> {
    let (mut s, mut ids) = save_from_json(save_json).ok_or("bad save")?;
    let mv: Value = serde_json::from_str(move_json).map_err(|_| "bad move json")?;
    let compact = if mv.get("t").is_some() {
        mv
    } else {
        engine_move_to_compact(&s, &ids, seat, &mv)?
    };
    let events = apply_compact(&mut s, &mut ids, seat, &compact, [pid0, pid1])?;
    Ok((save_to_json(&s, &ids), events))
}
