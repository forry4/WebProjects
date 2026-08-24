//! Featurize externally-supplied positions (native-only, `--features bridge`).
//!
//! Reads a JSONL of `{"proj": <compact.py projection>, "outcome": f32, "gid": u64}` and emits, in
//! input order:
//!   * `<out.csv>`  — the EXACT `harvest_attn` schema (`game_id,seat,tokens,mask,state,hval,outcome`)
//!     so `train_attn.py` ingests it unchanged.
//!   * `<diag.csv>` — `gid,seat,net_pred,hval,outcome`, the SHIPPED net's value at each position, for
//!     a calibration diagnostic (does the value head over-rate positions the bot went on to lose?).
//!
//! Featurization + the net forward go through the SAME `compact::from_proj` + `feats::features_tokens`
//! + `attn::AttnNet` code the browser serves with, so these rows are drift-free vs the net's own
//! training distribution and the diagnostic reflects the deployed net exactly.
//!
//!   cargo run --release --features bridge --bin featurize_positions -- in.jsonl out.csv diag.csv

use std::io::{BufRead, BufReader, BufWriter, Write};

use duel_core::attn::AttnNet;
use duel_core::compact::from_proj;
use duel_core::feats::{features_tokens, TOK_F, TOK_N, TOK_STATE};
use duel_core::value::value;
use serde_json::Value;

static ATTN_NET_JSON: &str = include_str!("../attn_value_net.json");

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let inp = args.get(1).expect("usage: featurize_positions <in.jsonl> <out.csv> <diag.csv>");
    let outp = args.get(2).expect("usage: featurize_positions <in.jsonl> <out.csv> <diag.csv>");
    let diagp = args.get(3).expect("usage: featurize_positions <in.jsonl> <out.csv> <diag.csv>");

    let net = AttnNet::from_json_str(ATTN_NET_JSON).expect("load embedded attn_value_net.json");

    let f = std::fs::File::open(inp).unwrap_or_else(|e| panic!("open {inp}: {e}"));
    let mut w = BufWriter::new(std::fs::File::create(outp).expect("create out.csv"));
    let mut dw = BufWriter::new(std::fs::File::create(diagp).expect("create diag.csv"));

    write!(w, "game_id,seat").unwrap();
    for i in 0..TOK_N * TOK_F {
        write!(w, ",tok{i}").unwrap();
    }
    for i in 0..TOK_N {
        write!(w, ",mask{i}").unwrap();
    }
    for i in 0..TOK_STATE {
        write!(w, ",st{i}").unwrap();
    }
    writeln!(w, ",hval,outcome").unwrap();
    writeln!(dw, "gid,seat,net_pred,hval,outcome").unwrap();

    let (mut rows, mut skipped) = (0u64, 0u64);
    let mut line = String::with_capacity(8192);
    for raw in BufReader::new(f).lines() {
        let raw = raw.expect("read line");
        if raw.trim().is_empty() {
            continue;
        }
        let rec: Value = serde_json::from_str(&raw).expect("parse jsonl");
        let proj = &rec["proj"];
        let outcome = rec["outcome"].as_f64().expect("outcome") as f32;
        let gid = rec["gid"].as_u64().unwrap_or(0);
        let (st, seat) = match from_proj(proj) {
            Some(x) => x,
            None => {
                skipped += 1;
                continue;
            }
        };
        let (tok, mask, state) = features_tokens(&st, seat);
        let hval = value(&st, seat);
        let npred = net.value(&tok, &mask, &state);

        line.clear();
        use std::fmt::Write as _;
        let _ = write!(line, "{gid},{seat}");
        for &v in &tok {
            let _ = write!(line, ",{v}");
        }
        for &v in &mask {
            let _ = write!(line, ",{v}");
        }
        for &v in &state {
            let _ = write!(line, ",{v}");
        }
        let _ = write!(line, ",{hval},{outcome}");
        writeln!(w, "{line}").unwrap();
        writeln!(dw, "{gid},{seat},{npred},{hval},{outcome}").unwrap();
        rows += 1;
    }
    w.flush().unwrap();
    dw.flush().unwrap();
    eprintln!("featurize_positions: {rows} rows written, {skipped} skipped (rejected proj)");
}
