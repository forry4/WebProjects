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
    assert!(
        mu.len() == crate::feats::N_FEATS || mu.len() == crate::feats::N_FEATS_V2,
        "model in_dim {} matches no encoder", mu.len()
    );
    assert_eq!(n_act, crate::engine::N_ACTIONS, "model n_act != N_ACTIONS");
    PolicyValueNet::from_parts(mu, sd, tdims, tw, tb, vw, vb, pw, pb, n_act)
}

/// Compact binary model blob (tools/pv_json_to_bin.py): magic "CPV1", u32 LE
/// header (in_dim, n_dims, tdims[n_dims] incl. the input dim, n_act), then f32 LE
/// arrays in export order (mu, sd, per-layer w+b, vw, vb, pw, pb). ~5.6x smaller
/// than the JSON export and parses in ~ms — the wasm worker fetch format (a model
/// swap is a file replace, no wasm rebuild). None on any malformed/mismatched blob.
pub fn pv_from_bin(b: &[u8]) -> Option<PolicyValueNet> {
    struct Rd<'a> {
        b: &'a [u8],
        i: usize,
    }
    impl Rd<'_> {
        fn u32(&mut self) -> Option<u32> {
            let v = u32::from_le_bytes(self.b.get(self.i..self.i + 4)?.try_into().ok()?);
            self.i += 4;
            Some(v)
        }
        fn f32s(&mut self, n: usize) -> Option<Vec<f32>> {
            let end = self.i.checked_add(n.checked_mul(4)?)?;
            let s = self.b.get(self.i..end)?;
            let mut v = Vec::with_capacity(n);
            for c in s.chunks_exact(4) {
                v.push(f32::from_le_bytes(c.try_into().ok()?));
            }
            self.i = end;
            Some(v)
        }
    }
    if b.get(..4)? != b"CPV1" {
        return None;
    }
    let mut r = Rd { b, i: 4 };
    let in_dim = r.u32()? as usize;
    let n_dims = r.u32()? as usize;
    if !(2..=8).contains(&n_dims) {
        return None;
    }
    let mut tdims = Vec::with_capacity(n_dims);
    for _ in 0..n_dims {
        tdims.push(r.u32()? as usize);
    }
    let n_act = r.u32()? as usize;
    if (in_dim != crate::feats::N_FEATS && in_dim != crate::feats::N_FEATS_V2)
        || tdims[0] != in_dim
        || n_act != crate::engine::N_ACTIONS
    {
        return None;
    }
    let mu = r.f32s(in_dim)?;
    let sd = r.f32s(in_dim)?;
    let mut tw = Vec::with_capacity(n_dims - 1);
    let mut tb = Vec::with_capacity(n_dims - 1);
    for i in 1..n_dims {
        tw.push(r.f32s(tdims[i] * tdims[i - 1])?);
        tb.push(r.f32s(tdims[i])?);
    }
    let h = tdims[n_dims - 1];
    let vw = r.f32s(h)?;
    let vb = r.f32s(1)?;
    let pw = r.f32s(n_act * h)?;
    let pb = r.f32s(n_act)?;
    if r.i != b.len() {
        return None;
    }
    Some(PolicyValueNet::from_parts(mu, sd, tdims, tw, tb, vw, vb, pw, pb, n_act))
}
