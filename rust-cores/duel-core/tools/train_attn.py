"""Train the card-set attention VALUE net on the harvest_attn CSVs and export JSON for the Rust
forward (attn.rs). Outcome-trained (MSE to the mover's eventual win/loss in [-1,1]), GAME-SPLIT
holdout (positions in a game share a label — a position-split leaks the answer). The export is the
parity contract with Rust (already verified to 1e-8 by attn_parity).

  python duel-core/tools/train_attn.py --data "C:/Users/Forrest/duel_run/attn_shard_*.csv" \
      --out duel-core/src/attn_value_net.json
"""
import argparse
import glob
import json
import os
import sys

import numpy as np
import torch
import torch.nn as nn

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from attn_net import AttnNet, TOK_F, TOK_N, TOK_STATE  # noqa: E402

TOKS = TOK_N * TOK_F


def load(glob_pat, dev):
    files = []
    for pat in glob_pat.split(","):  # comma-separated globs → a replay buffer over several iters
        files += glob.glob(pat)
    files = sorted(set(files))
    if not files:
        sys.exit(f"no CSVs match {glob_pat}")
    base = 2 + TOKS + TOK_N + TOK_STATE  # first trailing (label) column
    tk, mk, st, ys, hv, rv, gid = [], [], [], [], [], [], []
    for k, path in enumerate(files):
        arr = np.loadtxt(path, delimiter=",", skiprows=1, dtype=np.float32)
        gid.append(arr[:, 0].astype(np.int64) + k * 10_000_000)
        tk.append(torch.tensor(arr[:, 2:2 + TOKS], device=dev).view(-1, TOK_N, TOK_F))
        mk.append(torch.tensor(arr[:, 2 + TOKS:2 + TOKS + TOK_N], device=dev))
        st.append(torch.tensor(arr[:, 2 + TOKS + TOK_N:base], device=dev))
        ys.append(torch.tensor(arr[:, -1], device=dev))    # outcome (last col, both schemas)
        hv.append(torch.tensor(arr[:, base], device=dev))  # heuristic value (first trailing, both)
        # rootval (VALUE-BOOTSTRAP): only in the new schema (base+3 cols). Legacy CSVs fall back to the
        # outcome, so --rootval-blend is a harmless no-op on them.
        has_rv = arr.shape[1] >= base + 3
        rv.append(torch.tensor(arr[:, base + 1] if has_rv else arr[:, -1], device=dev))
        print(f"  {os.path.basename(path)}: {len(arr):,} rows{'' if has_rv else '  (legacy: no rootval)'}", flush=True)
        del arr
    return (torch.cat(tk), torch.cat(mk), torch.cat(st), torch.cat(ys), torch.cat(hv), torch.cat(rv), np.concatenate(gid))


def auc(scores, labels):
    order = np.argsort(scores)
    ranks = np.empty(len(scores), dtype=np.float64)
    ranks[order] = np.arange(1, len(scores) + 1)
    n_pos = int(labels.sum())
    n_neg = len(labels) - n_pos
    if n_pos == 0 or n_neg == 0:
        return 0.5
    return (ranks[labels == 1].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def load_weights(net, js):
    """Warm-start: assign flattened export()-JSON weights into the torch net's value path."""
    def setlin(lin, w, b=None):
        o, i = lin.weight.shape
        wt = torch.tensor(w, dtype=torch.float32)
        if wt.numel() == o * i:
            lin.weight.data.copy_(wt.view(o, i))
        elif wt.numel() % o == 0 and wt.numel() // o < i:
            # warm-start across a GROWN input dim (feature add): fill the original columns and
            # ZERO the new ones, so the net starts IDENTICAL to the checkpoint and learns the rest.
            oi = wt.numel() // o
            lin.weight.data[:, :oi].copy_(wt.view(o, oi))
            lin.weight.data[:, oi:].zero_()
        else:
            raise ValueError(f"warm-start shape mismatch: {wt.numel()} into [{o},{i}]")
        if b is not None:
            lin.bias.data.copy_(torch.tensor(b, dtype=torch.float32))
    setlin(net.emb, js["emb_w"], js["emb_b"])
    for l in range(len(net.wq)):
        setlin(net.wq[l], js["wq"][l]); setlin(net.wk[l], js["wk"][l])
        setlin(net.wv[l], js["wv"][l]); setlin(net.wo[l], js["wo"][l])
        setlin(net.f1[l], js["f1w"][l], js["f1b"][l]); setlin(net.f2[l], js["f2w"][l], js["f2b"][l])
    setlin(net.s, js["sw"], js["sb"]); setlin(net.t, js["tw"], js["tb"]); setlin(net.v, js["vw"], js["vb"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--bs", type=int, default=4096)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--weight-decay", type=float, default=2e-4)  # L2 reg — curbs the small-data overfit
    ap.add_argument("--val-frac", type=float, default=0.08)
    ap.add_argument("--patience", type=int, default=12)  # early-stop after N epochs without a val-AUC best
    ap.add_argument("--init", default=None, help="warm-start from this attn value-net JSON (fine-tune)")
    ap.add_argument("--hval-blend", type=float, default=0.0, help="target = (1-b)*outcome + b*heuristic_value (bakes in the move-ranking signal AUC can't see)")
    ap.add_argument("--rootval-blend", type=float, default=0.0, help="target = (1-b)*outcome + b*search_root_value — VALUE-BOOTSTRAP (β≈0.3): the search's own root eval, a richer per-position signal than the coarse game outcome (Spender keeper; its absence made value-only self-play wash)")
    ap.add_argument("--save-final", action="store_true", help="save the LAST epoch (no early stop) — for AZ co-evolution, where the net must MOVE toward the new data, not sit at the warm-start optimum")
    a = ap.parse_args()

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"device {dev}", flush=True)
    tok, msk, stt, y, hval, rootval, gid = load(a.data, dev)
    print(f"total {len(y):,} rows, {len(np.unique(gid)):,} games", flush=True)
    if a.hval_blend > 0.0:
        y = (1.0 - a.hval_blend) * y + a.hval_blend * hval
        print(f"target = {1 - a.hval_blend:.2f}*outcome + {a.hval_blend:.2f}*heuristic_value  (move-ranking signal)", flush=True)
    if a.rootval_blend > 0.0:
        y = (1.0 - a.rootval_blend) * y + a.rootval_blend * rootval
        print(f"target = {1 - a.rootval_blend:.2f}*outcome + {a.rootval_blend:.2f}*search_root_value  (VALUE-BOOTSTRAP)", flush=True)

    uniq = np.unique(gid)
    rng = np.random.default_rng(0)
    rng.shuffle(uniq)
    val_games = set(uniq[: max(1, int(len(uniq) * a.val_frac))].tolist())  # >=1 val game (0 -> vmse=NaN -> best_js stays None -> saves null)
    is_val = torch.tensor(np.fromiter((g in val_games for g in gid), dtype=bool, count=len(gid)), device=dev)
    idx_tr = torch.nonzero(~is_val).squeeze(1)
    idx_val = torch.nonzero(is_val).squeeze(1)

    net = AttnNet().to(dev)
    if a.init:
        with open(a.init) as f:
            load_weights(net, json.load(f))
        print(f"warm-started from {a.init}", flush=True)
    opt = torch.optim.Adam(net.parameters(), lr=a.lr, weight_decay=a.weight_decay)
    lossf = nn.MSELoss()

    best_mse, best_js, since_best = float("inf"), None, 0
    for ep in range(a.epochs):
        net.train()
        perm = idx_tr[torch.randperm(len(idx_tr), device=dev)]
        tot = 0.0
        for i in range(0, len(perm), a.bs):
            b = perm[i:i + a.bs]
            opt.zero_grad()
            loss = lossf(net(tok[b], msk[b], stt[b]), y[b])
            loss.backward()
            opt.step()
            tot += loss.item() * len(b)
        net.eval()
        with torch.no_grad():
            vp = torch.cat([net(tok[b], msk[b], stt[b]) for b in idx_val.split(16384)])
            vy = y[idx_val]
            vmse = lossf(vp, vy).item()
            vauc = auc(vp.cpu().numpy(), (vy.cpu().numpy() > 0).astype(int))
        print(f"ep{ep:02d}  train_mse {tot/len(idx_tr):.4f}  val_mse {vmse:.4f}  val_auc {vauc:.4f}", flush=True)
        if a.save_final:
            best_mse, best_js = vmse, net.export()
            best_js.update({"val_auc": float(vauc), "val_mse": float(vmse), "epoch": ep})
        elif vmse < best_mse:
            best_mse = vmse
            best_js = net.export()
            best_js.update({"val_auc": float(vauc), "val_mse": float(vmse), "epoch": ep})
            since_best = 0
        else:
            since_best += 1
            if since_best >= a.patience:
                print(f"early stop at ep{ep} (no val-MSE best in {a.patience} epochs; best_mse {best_mse:.4f})", flush=True)
                break

    if best_js is None:  # no epoch improved val (e.g. NaN val) -> save the final net so a cand always exists
        best_js = net.export()
        best_js.update({"val_auc": 0.0, "val_mse": float(best_mse), "epoch": a.epochs - 1})
        print("WARNING: best_js was None (no valid val epoch) -> saved final net", flush=True)
    with open(a.out, "w") as f:
        json.dump(best_js, f)
    print(f"saved {a.out}  (best val_mse {best_mse:.4f})", flush=True)


if __name__ == "__main__":
    main()
