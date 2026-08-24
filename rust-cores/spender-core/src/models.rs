//! The embedded nets' serde twins — one struct each, two wire formats. JSON is the
//! TRAINING-side format (the campaign tooling exports it; human-diffable, stays
//! committed as the source of truth). The wasm embeds the bincode encoding of the
//! SAME struct instead: a JSON float costs ~11 bytes of text where bincode stores
//! the parsed f32's 4 bytes verbatim — ~3x smaller wasm for byte-identical weights
//! (`from_bin(bincode(from_json(x)))` reconstructs exactly what `from_json(x)`
//! parsed). Regenerate the .bin files with `gen_net_bins` after ANY net swap; the
//! `net_bins_match_their_source_jsons` test pins bin==bincode(json) so a stale bin
//! fails `cargo test --features bridge` instead of silently shipping the old net.

use serde::{Deserialize, Serialize};

/// Variant N's original MLP value leaf (`n_model.json`).
#[derive(Deserialize, Serialize)]
pub struct NModel {
    pub dims: Vec<usize>,
    pub w: Vec<Vec<f32>>,
    pub b: Vec<Vec<f32>>,
    pub mu: Vec<f32>,
    pub sd: Vec<f32>,
}

/// The AZ policy+value MLP (`pv_model.json` = net_night_14, `pv_model_21.json` =
/// net_ext21_13 — the Long-mode specialization).
#[derive(Deserialize, Serialize)]
pub struct PVModel {
    pub mu: Vec<f32>,
    pub sd: Vec<f32>,
    pub tdims: Vec<usize>,
    pub tw: Vec<Vec<f32>>,
    pub tb: Vec<Vec<f32>>,
    pub vw: Vec<f32>,
    pub vb: Vec<f32>,
    pub pw: Vec<f32>,
    pub pb: Vec<f32>,
    pub n_act: usize,
}

/// The card-set attention net (`attn_model.json` = net_attn_3, the served Classic N).
#[derive(Deserialize, Serialize)]
pub struct AttnModel {
    pub emb_w: Vec<f32>,
    pub emb_b: Vec<f32>,
    pub wq: Vec<Vec<f32>>,
    pub wk: Vec<Vec<f32>>,
    pub wv: Vec<Vec<f32>>,
    pub wo: Vec<Vec<f32>>,
    pub f1w: Vec<Vec<f32>>,
    pub f1b: Vec<Vec<f32>>,
    pub f2w: Vec<Vec<f32>>,
    pub f2b: Vec<Vec<f32>>,
    pub sw: Vec<f32>,
    pub sb: Vec<f32>,
    pub tw: Vec<f32>,
    pub tb: Vec<f32>,
    pub vw: Vec<f32>,
    pub vb: Vec<f32>,
    pub pg_w: Vec<f32>,
    pub pg_b: Vec<f32>,
    pub ptok_w: Vec<f32>,
    pub ptok_b: Vec<f32>,
}

pub fn from_json<T: serde::de::DeserializeOwned>(s: &str, what: &str) -> T {
    serde_json::from_str(s).unwrap_or_else(|e| panic!("embedded {what} json: {e}"))
}

pub fn from_bin<T: serde::de::DeserializeOwned>(b: &[u8], what: &str) -> T {
    bincode::deserialize(b).unwrap_or_else(|e| panic!("embedded {what} bin: {e}"))
}

// The stale-bin guard (see the module header). Byte equality of the bincode
// encodings implies bit-identical weights — bincode is a pure function of the
// parsed f32s.
#[cfg(test)]
mod tests {
    use super::*;

    fn check<T: serde::de::DeserializeOwned + Serialize>(json: &str, bin: &[u8], name: &str) {
        let m: T = from_json(json, name);
        assert_eq!(
            bincode::serialize(&m).unwrap(),
            bin,
            "{name}.bin is stale — rerun: cargo run --release --features bridge --bin gen_net_bins"
        );
    }

    #[test]
    fn net_bins_match_their_source_jsons() {
        check::<NModel>(include_str!("n_model.json"), include_bytes!("n_model.bin"), "n_model");
        check::<PVModel>(include_str!("pv_model.json"), include_bytes!("pv_model.bin"), "pv_model");
        check::<PVModel>(include_str!("pv_model_21.json"), include_bytes!("pv_model_21.bin"), "pv_model_21");
        check::<AttnModel>(include_str!("attn_model.json"), include_bytes!("attn_model.bin"), "attn_model");
    }
}
