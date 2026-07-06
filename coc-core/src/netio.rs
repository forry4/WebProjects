//! PolicyValueNet JSON loader — the exact layout coc_run/train_pv.py exports
//! (mirrors the spender pattern: flat row-major arrays + z-score mu/sd).
//! Native side needs the `bridge` feature (serde); wasm gets serde unconditionally.
#![cfg(any(feature = "bridge", target_arch = "wasm32"))]

use crate::valuenet::PolicyValueNet;
use serde_json::Value;

fn vf32(v: &Value) -> Vec<f32> {
    v.as_array()
        .expect("array")
        .iter()
        .map(|x| x.as_f64().expect("num") as f32)
        .collect()
}

pub fn pv_from_json(text: &str) -> PolicyValueNet {
    let j: Value = serde_json::from_str(text).expect("pv model json");
    let mu = vf32(&j["mu"]);
    let sd = vf32(&j["sd"]);
    let tdims: Vec<usize> = j["tdims"]
        .as_array()
        .expect("tdims")
        .iter()
        .map(|x| x.as_u64().expect("dim") as usize)
        .collect();
    let tw: Vec<Vec<f32>> = j["tw"].as_array().expect("tw").iter().map(vf32).collect();
    let tb: Vec<Vec<f32>> = j["tb"].as_array().expect("tb").iter().map(vf32).collect();
    let vw = vf32(&j["vw"]);
    let vb = vf32(&j["vb"]);
    let pw = vf32(&j["pw"]);
    let pb = vf32(&j["pb"]);
    let n_act = j["n_act"].as_u64().expect("n_act") as usize;
    assert_eq!(mu.len(), crate::feats::N_FEATS, "model in_dim != N_FEATS");
    assert_eq!(n_act, crate::engine::N_ACTIONS, "model n_act != N_ACTIONS");
    PolicyValueNet::from_parts(mu, sd, tdims, tw, tb, vw, vb, pw, pb, n_act)
}
