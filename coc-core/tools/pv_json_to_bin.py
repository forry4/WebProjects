"""Convert a train_pv.py JSON export to the compact binary blob the wasm worker
fetches (netio::pv_from_bin). f32 LE, ~5.6x smaller than the float-text JSON, and
a model swap is a file replace (no wasm rebuild).

  python coc-core/tools/pv_json_to_bin.py C:/Users/Forrest/coc_run/pv_best.json \
      webapp/public/wasm/coc_pv_model.bin

Layout: magic "CPV1" | u32 in_dim | u32 n_dims | u32 tdims[n_dims] (incl. input
dim) | u32 n_act | f32 mu, sd, per-layer w+b, vw, vb, pw, pb.
Both readers round float-text -> f64 -> f32 (IEEE round-to-nearest), so the bin
net is bit-identical to the JSON net; net_export_check verifies that.
"""
import json
import struct
import sys


def convert(src: str, dst: str) -> None:
    with open(src, encoding="utf-8") as f:
        j = json.load(f)
    tdims = j["tdims"]
    assert tdims[0] == len(j["mu"]), "tdims[0] must be the input dim"
    out = bytearray(b"CPV1")
    out += struct.pack("<II", len(j["mu"]), len(tdims))
    for d in tdims:
        out += struct.pack("<I", d)
    out += struct.pack("<I", j["n_act"])

    def f32s(a):
        return struct.pack(f"<{len(a)}f", *a)

    out += f32s(j["mu"])
    out += f32s(j["sd"])
    for w, b in zip(j["tw"], j["tb"]):
        out += f32s(w)
        out += f32s(b)
    out += f32s(j["vw"])
    out += f32s(j["vb"])
    out += f32s(j["pw"])
    out += f32s(j["pb"])
    with open(dst, "wb") as f:
        f.write(bytes(out))
    print(f"{dst}: {len(out) / 1e6:.2f} MB (from {src})")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: pv_json_to_bin.py <model.json> <out.bin>")
    convert(sys.argv[1], sys.argv[2])
