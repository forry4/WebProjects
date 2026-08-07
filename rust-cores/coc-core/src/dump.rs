//! Full-fidelity State ⇄ JSON — the OFFLINE save format (IndexedDB), and nothing else.
//!
//! This is deliberately NOT the compact projection: `az_compact.project` destroys the
//! draw order of the three hidden pools (the caller sorts them) and drops `rng`/`micro`,
//! because the search must not read them. An offline save is the opposite contract —
//! the browser IS the authority, so it must round-trip the TRUE state exactly:
//! ordered pools, the rng word (every future die), and any mid-chain `micro`.
//! Field-for-field with `engine::State`; a new State field must be added here or
//! offline saves silently drop it. Variable pools serialize truncated to their `*_len`
//! (the reader reconstructs the fixed arrays), keeping the JSON small.

use crate::boards_gen::{MAX_REGIONS, N_SPACES};
use crate::engine::{Die, Micro, Pending, State};
use crate::tiles::N_GOODS;
use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize)]
pub struct PlayerDump {
    pub duchy: Vec<u16>, // N_SPACES
    pub castle_sid: u8,
    pub storage: [u16; 3],
    pub goods: [u8; N_GOODS],
    pub sold: [u8; N_GOODS],
    pub workers: i16,
    pub silver: i16,
    pub vp: i16,
    pub bonus_claimed: u8,
    pub mines: u8,
    pub buildings: [u8; 8],
    pub livestock_mask: u8,
    pub mon_mask: u32,
    pub town_bldg: Vec<u8>, // MAX_REGIONS
    pub region_vp: i16,
    pub color_vp: i16,
    pub livestock_vp: i16,
    #[serde(default)]
    pub bonus_vp: [u8; N_GOODS],
}

#[derive(Serialize, Deserialize)]
pub struct Dump {
    pub boards: [u8; 2],
    pub phase: u8,
    pub round: u8,
    pub mode: u8,
    pub winner: i8,
    pub track_pos: [u8; 2],
    pub track_top: i8,
    pub round_order: [u8; 2],
    pub start_player: u8,
    pub turn: i8,
    pub white_die: u8,
    /// [seat][die] = [value, orig, used, adjusted]
    pub dice: [[[u8; 4]; 2]; 2],
    pub black_used: bool,
    pub m6_used: bool,
    pub depot_hex: [[u16; 2]; 6],
    pub depot_goods: [[u8; N_GOODS]; 6],
    pub black_depot: [u16; 4],
    pub supply: Vec<u16>,
    pub black_supply: Vec<u16>,
    pub goods_supply: Vec<u8>,
    pub goods_queue: Vec<u8>,
    pub bonus_left: [u8; N_GOODS],
    pub players: Vec<PlayerDump>, // 2
    pub pending_pid: i8,
    pub pending_tag: u8,
    pub pending_fields: Vec<i32>,
    /// 0 None | 1 DieMenu[die,value] | 2 PlaceWhere[die,value,slot] | 3 M6
    pub micro_tag: u8,
    pub micro_fields: Vec<i32>,
    pub rng: u64,
}

fn pending_encode(p: Pending) -> (u8, Vec<i32>) {
    match p {
        Pending::None => (0, vec![]),
        Pending::ExtraAction => (1, vec![]),
        Pending::ShipChoose => (2, vec![]),
        Pending::ShipAdj { cands } => (3, vec![cands as i32]),
        Pending::GoodsPick { depot, colors, m5_from } => {
            (4, vec![depot as i32, colors as i32, m5_from as i32])
        }
        Pending::BuildingTake { types } => (5, vec![types as i32]),
        Pending::Warehouse => (6, vec![]),
        Pending::Townhall => (7, vec![]),
    }
}

fn pending_decode(tag: u8, f: &[i32]) -> Pending {
    match tag {
        1 => Pending::ExtraAction,
        2 => Pending::ShipChoose,
        3 => Pending::ShipAdj { cands: f[0] as u8 },
        4 => Pending::GoodsPick { depot: f[0] as u8, colors: f[1] as u8, m5_from: f[2] as i8 },
        5 => Pending::BuildingTake { types: f[0] as u8 },
        6 => Pending::Warehouse,
        7 => Pending::Townhall,
        _ => Pending::None,
    }
}

fn micro_encode(m: Micro) -> (u8, Vec<i32>) {
    match m {
        Micro::None => (0, vec![]),
        Micro::DieMenu { die, value } => (1, vec![die as i32, value as i32]),
        Micro::PlaceWhere { die, value, slot } => (2, vec![die as i32, value as i32, slot as i32]),
        Micro::M6 => (3, vec![]),
    }
}

fn micro_decode(tag: u8, f: &[i32]) -> Micro {
    match tag {
        1 => Micro::DieMenu { die: f[0] as i8, value: f[1] as u8 },
        2 => Micro::PlaceWhere { die: f[0] as i8, value: f[1] as u8, slot: f[2] as u8 },
        3 => Micro::M6,
        _ => Micro::None,
    }
}

impl Dump {
    pub fn from_state(s: &State) -> Dump {
        let (pending_tag, pending_fields) = pending_encode(s.pending);
        let (micro_tag, micro_fields) = micro_encode(s.micro);
        let mut dice = [[[0u8; 4]; 2]; 2];
        for seat in 0..2 {
            for die in 0..2 {
                let d = s.dice[seat][die];
                dice[seat][die] = [d.value, d.orig, d.used as u8, d.adjusted as u8];
            }
        }
        Dump {
            boards: s.boards,
            phase: s.phase,
            round: s.round,
            mode: s.mode,
            winner: s.winner,
            track_pos: s.track_pos,
            track_top: s.track_top,
            round_order: s.round_order,
            start_player: s.start_player,
            turn: s.turn,
            white_die: s.white_die,
            dice,
            black_used: s.black_used,
            m6_used: s.m6_used,
            depot_hex: s.depot_hex,
            depot_goods: s.depot_goods,
            black_depot: s.black_depot,
            supply: s.supply[..s.supply_len as usize].to_vec(),
            black_supply: s.black_supply[..s.black_supply_len as usize].to_vec(),
            goods_supply: s.goods_supply[..s.goods_supply_len as usize].to_vec(),
            goods_queue: s.goods_queue[..s.goods_queue_len as usize].to_vec(),
            bonus_left: s.bonus_left,
            players: s
                .players
                .iter()
                .map(|p| PlayerDump {
                    duchy: p.duchy.to_vec(),
                    castle_sid: p.castle_sid,
                    storage: p.storage,
                    goods: p.goods,
                    sold: p.sold,
                    workers: p.workers,
                    silver: p.silver,
                    vp: p.vp,
                    bonus_claimed: p.bonus_claimed,
                    mines: p.mines,
                    buildings: p.buildings,
                    livestock_mask: p.livestock_mask,
                    mon_mask: p.mon_mask,
                    town_bldg: p.town_bldg.to_vec(),
                    region_vp: p.region_vp,
                    color_vp: p.color_vp,
                    livestock_vp: p.livestock_vp,
                    bonus_vp: p.bonus_vp,
                })
                .collect(),
            pending_pid: s.pending_pid,
            pending_tag,
            pending_fields,
            micro_tag,
            micro_fields,
            rng: s.rng,
        }
    }

    pub fn into_state(self) -> State {
        let mut s = State::shell(self.boards);
        s.phase = self.phase;
        s.round = self.round;
        s.mode = self.mode;
        s.winner = self.winner;
        s.track_pos = self.track_pos;
        s.track_top = self.track_top;
        s.round_order = self.round_order;
        s.start_player = self.start_player;
        s.turn = self.turn;
        s.white_die = self.white_die;
        for seat in 0..2 {
            for die in 0..2 {
                let d = self.dice[seat][die];
                s.dice[seat][die] = Die {
                    value: d[0],
                    orig: d[1],
                    used: d[2] != 0,
                    adjusted: d[3] != 0,
                };
            }
        }
        s.black_used = self.black_used;
        s.m6_used = self.m6_used;
        s.depot_hex = self.depot_hex;
        s.depot_goods = self.depot_goods;
        s.black_depot = self.black_depot;
        s.supply_len = self.supply.len() as u8;
        s.supply[..self.supply.len()].copy_from_slice(&self.supply);
        s.black_supply_len = self.black_supply.len() as u8;
        s.black_supply[..self.black_supply.len()].copy_from_slice(&self.black_supply);
        s.goods_supply_len = self.goods_supply.len() as u8;
        s.goods_supply[..self.goods_supply.len()].copy_from_slice(&self.goods_supply);
        s.goods_queue_len = self.goods_queue.len() as u8;
        s.goods_queue[..self.goods_queue.len()].copy_from_slice(&self.goods_queue);
        s.bonus_left = self.bonus_left;
        for (seat, pd) in self.players.into_iter().enumerate().take(2) {
            let ps = &mut s.players[seat];
            for sid in 0..N_SPACES.min(pd.duchy.len()) {
                ps.duchy[sid] = pd.duchy[sid];
                if ps.duchy[sid] != 0 {
                    ps.filled |= 1 << sid;
                }
            }
            ps.castle_sid = pd.castle_sid;
            ps.storage = pd.storage;
            ps.goods = pd.goods;
            ps.sold = pd.sold;
            ps.workers = pd.workers;
            ps.silver = pd.silver;
            ps.vp = pd.vp;
            ps.bonus_claimed = pd.bonus_claimed;
            ps.mines = pd.mines;
            ps.buildings = pd.buildings;
            ps.livestock_mask = pd.livestock_mask;
            ps.mon_mask = pd.mon_mask;
            for r in 0..MAX_REGIONS.min(pd.town_bldg.len()) {
                ps.town_bldg[r] = pd.town_bldg[r];
            }
            ps.region_vp = pd.region_vp;
            ps.color_vp = pd.color_vp;
            ps.livestock_vp = pd.livestock_vp;
            ps.bonus_vp = pd.bonus_vp;
        }
        s.pending_pid = self.pending_pid;
        s.pending = pending_decode(self.pending_tag, &self.pending_fields);
        s.micro = micro_decode(self.micro_tag, &self.micro_fields);
        s.rng = self.rng;
        s
    }
}
