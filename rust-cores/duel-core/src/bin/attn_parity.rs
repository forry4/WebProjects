//! Parity: `attn::AttnNet::value` (Rust, f32) must match the PyTorch twin (`tools/attn_net.py`, f64
//! reference) on the random weights + input it dumps. Make-or-break: it PLAYS (Rust) what it TRAINS
//! (torch), so nothing is gated until this passes.
//!
//!   python duel-core/tools/attn_net.py parity --out <dir>
//!   cargo run --release --features bridge --bin attn_parity -- <dir>

use duel_core::attn::AttnNet;
use serde::Deserialize;

#[derive(Deserialize)]
struct Input {
    tokens: Vec<f64>,
    mask: Vec<f64>,
    state: Vec<f64>,
    expected: f64,
    #[serde(default)]
    expected_policy: Vec<f64>,
}

fn main() {
    let dir = std::env::args().nth(1).expect("usage: attn_parity <dir>");
    let w = std::fs::read_to_string(format!("{dir}/weights.json")).expect("read weights.json");
    let inp: Input = serde_json::from_str(
        &std::fs::read_to_string(format!("{dir}/input.json")).expect("read input.json"),
    )
    .expect("parse input.json");
    let net = AttnNet::from_json_str(&w).expect("load net");
    let got = net.value(&inp.tokens, &inp.mask, &inp.state);
    let diff = (got - inp.expected).abs();
    println!("rust(f32)={:.8}  torch(f64)={:.8}  |diff|={:.2e}", got, inp.expected, diff);
    // Tolerance allows f32-vs-f64 rounding + matmul summation-order differences; a STRUCTURAL bug
    // (wrong feature order / op) shows up as ~0.1+, far above this.
    assert!(diff < 1.5e-3, "PARITY FAIL: |diff|={:.2e} exceeds 1.5e-3", diff);
    println!("PARITY OK (<1.5e-3)");

    // Policy head parity — present iff the dumped weights carry a policy head (`export_pv`).
    if !inp.expected_policy.is_empty() {
        let got = net.policy_logits_raw(&inp.tokens, &inp.mask, &inp.state);
        assert_eq!(got.len(), inp.expected_policy.len(), "policy length mismatch (rust {} vs torch {})", got.len(), inp.expected_policy.len());
        let mut mx = 0.0f64;
        for (g, e) in got.iter().zip(inp.expected_policy.iter()) {
            mx = mx.max((*g as f64 - *e).abs());
        }
        println!("policy |diff|max = {:.2e} over {} logits", mx, got.len());
        assert!(mx < 1.5e-3, "POLICY PARITY FAIL: |diff|max={:.2e} exceeds 1.5e-3", mx);
        println!("POLICY PARITY OK (<1.5e-3)");
    }
}
