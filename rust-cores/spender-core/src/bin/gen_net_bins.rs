//! Regenerate the embedded-net .bin files (the compact wasm embed format) from their
//! source JSONs — see `models.rs` for the format contract. Run after ANY net swap;
//! the `net_bins_match_their_source_jsons` lib test fails until the bins match again.
//!
//!     cargo run --release --features bridge --bin gen_net_bins

use spender_core::models::{from_bin, from_json, AttnModel, NModel, PVModel};

fn convert<T: serde::de::DeserializeOwned + serde::Serialize>(name: &str) {
    let dir = concat!(env!("CARGO_MANIFEST_DIR"), "/src");
    let json_path = format!("{dir}/{name}.json");
    let bin_path = format!("{dir}/{name}.bin");
    let text = std::fs::read_to_string(&json_path).expect(&json_path);
    let m: T = from_json(&text, name);
    let bytes = bincode::serialize(&m).expect("bincode");
    // Round-trip through the loader path and re-encode: stability check.
    let back: T = from_bin(&bytes, name);
    assert_eq!(bincode::serialize(&back).unwrap(), bytes, "{name}: bin round-trip drifted");
    std::fs::write(&bin_path, &bytes).expect(&bin_path);
    println!("{json_path} -> {bin_path} ({} -> {} bytes)", text.len(), bytes.len());
}

fn main() {
    convert::<NModel>("n_model");
    convert::<PVModel>("pv_model");
    convert::<PVModel>("pv_model_21");
    convert::<AttnModel>("attn_model");
}
