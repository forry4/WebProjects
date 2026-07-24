//! Torch↔Rust net parity: forward_raw the check vectors train_pv.py exported and
//! compare value + first-8 logits (<=1e-3; f32 summation order differs slightly).
//! With a second arg (a pv_json_to_bin.py blob), also verifies the bin loader
//! yields a BIT-IDENTICAL forward (both readers round float-text -> f64 -> f32).
//!
//!   cargo run --release --features bridge --bin net_export_check -- <model.json> [model.bin]

use coc_core::netio::{pv_from_bin, pv_from_json};
use serde_json::Value;

fn main() {
    let path = std::env::args().nth(1).expect("usage: net_export_check <model.json> [model.bin]");
    let net = pv_from_json(&std::fs::read_to_string(&path).expect("model"));
    if let Some(bin_path) = std::env::args().nth(2) {
        let bnet = pv_from_bin(&std::fs::read(&bin_path).expect("bin")).expect("bin parse");
        let x = vec![0.1f32; coc_core::feats::N_FEATS];
        let (v1, l1) = net.forward_raw(&x);
        let (v2, l2) = bnet.forward_raw(&x);
        assert!(v1 == v2 && l1 == l2, "bin blob not bit-identical to json model");
        println!("bin check: bit-identical forward PASS ({bin_path})");
    }
    let check: Value = serde_json::from_str(
        &std::fs::read_to_string(format!("{path}.check")).expect("check file"),
    )
    .expect("check json");
    let inputs = check["inputs"].as_array().expect("inputs");
    let mut max_v = 0.0f64;
    let mut max_l = 0.0f64;
    for (i, row) in inputs.iter().enumerate() {
        let x: Vec<f32> = row
            .as_array()
            .expect("row")
            .iter()
            .map(|v| v.as_f64().expect("f") as f32)
            .collect();
        let (v, logits) = net.forward_raw(&x);
        let want_v = check["values"][i].as_f64().expect("v");
        max_v = max_v.max((v as f64 - want_v).abs());
        for k in 0..8 {
            let want = check["logits8"][i][k].as_f64().expect("l");
            max_l = max_l.max((logits[k] as f64 - want).abs());
        }
    }
    println!("net_export_check: max value diff {max_v:.2e}, max logit diff {max_l:.2e}");
    assert!(max_v < 1e-3 && max_l < 1e-3, "parity FAILED");
    println!("PASS");
}
