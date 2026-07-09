//! Torch <-> Rust parity gate for the attention net. Loads <model.json> +
//! <model.json.check> (rows in the tokfeats flat layout + torch outputs, from
//! attn_net.py write_check) and compares the Rust forward. Values must agree
//! <=1e-4 and every FINITE logit <=1e-3 (masked/absent logits are -1e9 on both
//! sides and are skipped). Non-negotiable before any trained json is trusted —
//! same contract as net_export_check for the MLP.
//!
//!   attn_export_check <model.json>
use coc_core::attn::AttnNet;
use coc_core::valuenet::PvEval;

#[derive(serde::Deserialize)]
struct Check {
    rows: Vec<Vec<f32>>,
    values: Vec<f32>,
    logits: Vec<Vec<f32>>,
}

fn main() {
    let path = std::env::args().nth(1).expect("usage: attn_export_check <model.json>");
    let net = AttnNet::from_json(&path);
    let check: Check = serde_json::from_str(
        &std::fs::read_to_string(format!("{path}.check")).expect("check file"),
    )
    .expect("parse check");
    let (mut vmax, mut lmax) = (0f32, 0f32);
    for (i, row) in check.rows.iter().enumerate() {
        let (v, pol) = net.forward_raw(row);
        vmax = vmax.max((v - check.values[i]).abs());
        for (a, (&r, &t)) in pol.iter().zip(&check.logits[i]).enumerate() {
            let finite = t > -1e8;
            assert_eq!(
                r > -1e8,
                finite,
                "row {i} action {a}: masked-slot disagreement (rust {r}, torch {t})"
            );
            if finite {
                lmax = lmax.max((r - t).abs());
            }
        }
    }
    println!("attn_export_check: max value diff {vmax:.2e}, max logit diff {lmax:.2e}");
    assert!(vmax <= 1e-4 && lmax <= 1e-3, "PARITY FAIL");
    println!("PASS");
}
