"""Warm-start a 936-input net from the r2 champion (934 inputs).

The 4-animal encoder inserts exactly 2 new features (the 4th animal's livestock-mask
bit for me + opp) at fixed indices in the otherwise-identical 934-feature layout:
  NEW index 72  = me's 4th-animal bit
  NEW index 146 = opp's 4th-animal bit
(animal loops start at 69/143; the 4th bit is +3). We rebuild the input layer by
placing r2's 934 columns into their same feature slots and zero-init the 2 new ones,
so the net is IDENTICAL to r2 on chicken-free states and ignores the chicken bit
until fine-tuned. Value/policy heads + hidden layers are untouched.

Usage: python warmstart_4animal.py <r2_934.json> <out_936.json>
"""
import json, sys
import numpy as np

NEW_IDX = (72, 146)  # positions of the 2 new (4th-animal) inputs in the 936 vector

def expand_vec(old, fill):
    new = np.full(len(old) + len(NEW_IDX), fill, dtype=np.float64)
    oi = 0
    for j in range(len(new)):
        if j in NEW_IDX:
            continue
        new[j] = old[oi]; oi += 1
    assert oi == len(old)
    return new

def main():
    src, out = sys.argv[1], sys.argv[2]
    d = json.load(open(src))
    din, h1, h2 = d["tdims"]
    assert din == 934, f"expected 934-input net, got {din}"

    # z-score: new inputs get mu=0, sd=1 (their weights are 0 so this is inert).
    d["mu"] = expand_vec(np.array(d["mu"]), 0.0).tolist()
    d["sd"] = expand_vec(np.array(d["sd"]), 1.0).tolist()

    # first trunk layer [h1, 934] row-major -> [h1, 936] with 2 zero columns.
    tw0 = np.array(d["tw"][0]).reshape(h1, din)
    tw0_new = np.zeros((h1, din + len(NEW_IDX)))
    oi = 0
    for j in range(din + len(NEW_IDX)):
        if j in NEW_IDX:
            continue
        tw0_new[:, j] = tw0[:, oi]; oi += 1
    assert oi == din
    d["tw"][0] = tw0_new.flatten().tolist()
    d["tdims"] = [din + len(NEW_IDX), h1, h2]

    json.dump(d, open(out, "w"), separators=(",", ":"))

    # self-check: removing the 2 new columns must recover r2 exactly.
    chk = np.array(d["tw"][0]).reshape(h1, din + len(NEW_IDX))
    recovered = np.delete(chk, NEW_IDX, axis=1)
    assert np.array_equal(recovered, tw0), "column re-insertion mismatch"
    assert np.allclose(chk[:, list(NEW_IDX)], 0.0), "new columns not zero"
    print(f"OK: {src} (934) -> {out} (936); tw0 {tw0.shape}->{tw0_new.shape}; "
          f"2 new cols at {NEW_IDX} are zero; other 934 recover r2 exactly")

if __name__ == "__main__":
    main()
