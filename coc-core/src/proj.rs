//! Canonical projection string + FNV-1a 64 hash — the parity surface.
//!
//! MUST render byte-identically to games/castles_of_crimson/ai/az/compact.py's
//! `proj_string(project(game))` (same fields, same order, space-separated decimal
//! ints). The differential parity test compares hashes after every engine move;
//! never change one side without the other.

use crate::boards_gen::MAX_REGIONS;
use crate::engine::{Pending, State};
use crate::tiles::N_GOODS;

pub fn fnv64(s: &str) -> u64 {
    let mut h: u64 = 0xCBF2_9CE4_8422_2325;
    for &b in s.as_bytes() {
        h ^= b as u64;
        h = h.wrapping_mul(0x1_0000_0001_B3);
    }
    h
}

pub fn proj_string(s: &State) -> String {
    let mut out: Vec<i64> = Vec::with_capacity(512);
    out.extend([s.boards[0] as i64, s.boards[1] as i64]);
    out.extend([s.phase as i64, s.round as i64, s.mode as i64, s.winner as i64]);
    out.extend([s.track_pos[0] as i64, s.track_pos[1] as i64, s.track_top as i64]);
    out.extend([s.round_order[0] as i64, s.round_order[1] as i64]);
    out.extend([s.start_player as i64, s.turn as i64, s.white_die as i64]);
    for seat in 0..2 {
        for die in 0..2 {
            let d = s.dice[seat][die];
            out.extend([d.value as i64, d.orig as i64, d.used as i64, d.adjusted as i64]);
        }
    }
    out.extend([s.black_used as i64, s.m6_used as i64]);
    for d in 0..6 {
        out.extend([s.depot_hex[d][0] as i64, s.depot_hex[d][1] as i64]);
    }
    for d in 0..6 {
        for c in 0..N_GOODS {
            out.push(s.depot_goods[d][c] as i64);
        }
    }
    for slot in 0..4 {
        out.push(s.black_depot[slot] as i64);
    }
    out.push(s.supply_len as i64);
    for i in 0..s.supply_len as usize {
        out.push(s.supply[i] as i64);
    }
    out.push(s.black_supply_len as i64);
    for i in 0..s.black_supply_len as usize {
        out.push(s.black_supply[i] as i64);
    }
    out.push(s.goods_supply_len as i64);
    for i in 0..s.goods_supply_len as usize {
        out.push(s.goods_supply[i] as i64);
    }
    out.push(s.goods_queue_len as i64);
    for i in 0..s.goods_queue_len as usize {
        out.push(s.goods_queue[i] as i64);
    }
    for c in 0..N_GOODS {
        out.push(s.bonus_left[c] as i64);
    }
    for seat in 0..2 {
        let p = &s.players[seat];
        for sid in 0..crate::boards_gen::N_SPACES {
            out.push(p.duchy[sid] as i64);
        }
        out.push(p.castle_sid as i64);
        for slot in 0..3 {
            out.push(p.storage[slot] as i64);
        }
        for c in 0..N_GOODS {
            out.push(p.goods[c] as i64);
        }
        for c in 0..N_GOODS {
            out.push(p.sold[c] as i64);
        }
        out.extend([
            p.workers as i64,
            p.silver as i64,
            p.vp as i64,
            p.bonus_claimed as i64,
            p.mines as i64,
        ]);
        for b in 0..crate::tiles::N_BUILDINGS {
            out.push(p.buildings[b] as i64);
        }
        out.extend([p.livestock_mask as i64, p.mon_mask as i64]);
        for r in 0..MAX_REGIONS {
            out.push(p.town_bldg[r] as i64);
        }
    }
    out.push(s.pending_pid as i64);
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
    out.push(tag);
    out.extend(fields);

    let mut str_out = String::with_capacity(out.len() * 3);
    for (i, v) in out.iter().enumerate() {
        if i > 0 {
            str_out.push(' ');
        }
        str_out.push_str(&v.to_string());
    }
    str_out
}

pub fn proj_hash(s: &State) -> u64 {
    fnv64(&proj_string(s))
}
