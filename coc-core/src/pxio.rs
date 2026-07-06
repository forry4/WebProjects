//! Projection I/O (bridge feature): build a State from the canonical JSON
//! projection compact.py emits. Shared by the parity test, the move server, and
//! (later) the wasm Dump path.
#![cfg(feature = "bridge")]

use crate::boards_gen::{MAX_REGIONS, N_SPACES};
use crate::engine::{Die, Pending, PlayerState, State};
use serde_json::Value;

fn iu(v: &Value) -> i64 {
    v.as_i64().expect("int")
}

fn arr<'a>(v: &'a Value, k: &str) -> &'a Vec<Value> {
    v[k].as_array().unwrap_or_else(|| panic!("array {k}"))
}

pub fn from_proj(p: &Value) -> State {
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
