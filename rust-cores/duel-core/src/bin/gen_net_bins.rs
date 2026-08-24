//! Regenerate the embedded-net .bin files (the compact wasm embed format) from their
//! source JSONs. Run after ANY net swap; the `net_bins_*` lib tests pin bin==bincode(json)
//! so a stale bin fails `cargo test` loudly instead of shipping an old net.
//!
//!     cargo run --release --features bridge --bin gen_net_bins
//!
//! The conversion is LOSSLESS by construction: serde parses the JSON's decimal floats
//! into f32s, and bincode writes those exact f32 bit patterns — so the wasm-side
//! `AttnNet::from_bin_bytes` reconstructs field-for-field bit-identical weights to
//! what `from_json_str` produced. The assert below proves it per run.

use duel_core::attn::AttnNet;

fn convert(json_path: &str, bin_path: &str) {
    let text = std::fs::read_to_string(json_path).expect(json_path);
    let from_json = AttnNet::from_json_str(&text).expect("parse json");
    // Re-encode through the same serde struct the loader uses.
    let j: duel_core::attn::AttnJson = serde_json::from_str(&text).unwrap();
    let bytes = bincode::serialize(&j).expect("bincode");
    let from_bin = AttnNet::from_bin_bytes(&bytes).expect("parse bin");
    // Bit-identical: f32 -> bits comparison on every field.
    let flat = |n: &AttnNet| -> Vec<u32> {
        let mut v: Vec<u32> = Vec::new();
        let mut push = |xs: &[f32]| v.extend(xs.iter().map(|x| x.to_bits()));
        push(&n.emb_w); push(&n.emb_b);
        for f in [&n.wq, &n.wk, &n.wv, &n.wo, &n.f1w, &n.f1b, &n.f2w, &n.f2b] {
            for l in f.iter() { push(l); }
        }
        push(&n.sw); push(&n.sb); push(&n.tw); push(&n.tb);
        push(&n.vw); push(&n.vb); push(&n.pw); push(&n.pb);
        v
    };
    assert_eq!(flat(&from_json), flat(&from_bin), "bin round-trip must be bit-identical");
    assert_eq!((from_json.tf, from_json.sf), (from_bin.tf, from_bin.sf));
    std::fs::write(bin_path, &bytes).expect(bin_path);
    println!("{} -> {} ({} -> {} bytes)", json_path, bin_path, text.len(), bytes.len());
}

fn main() {
    let dir = concat!(env!("CARGO_MANIFEST_DIR"), "/src");
    for name in ["attn_value_net", "attn_expert_net"] {
        convert(&format!("{dir}/{name}.json"), &format!("{dir}/{name}.bin"));
    }
}
