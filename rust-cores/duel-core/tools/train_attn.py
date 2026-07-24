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
    files = sorted(glob.glob(glob_pat))
    if not files:
        sys.exit(f"no CSVs match {glob_pat}")
    tk, mk, st, ys, gid = [], [], [], [], []
    for k, path in enumerate(files):
        arr = np.loadtxt(path, delimiter=",", skiprows=1, dtype=np.float32)
        gid.append(arr[:, 0].astype(np.int64) + k * 10_000_000)
        tk.append(torch.tensor(arr[:, 2:2 + TOKS], device=dev).view(-1, TOK_N, TOK_F))
        mk.append(torch.tensor(arr[:, 2 + TOKS:2 + TOKS + TOK_N], device=dev))
        st.append(torch.tensor(arr[:, 2 + TOKS + TOK_N:2 + TOKS + TOK_N + TOK_STATE], device=dev))
        ys.append(torch.tensor(arr[:, -1], device=dev))  # outcome (last col)
        print(f"  {os.path.basename(path)}: {len(arr):,} rows", flush=True)
        del arr
    return (torch.cat(tk), torch.cat(mk), torch.cat(st), torch.cat(ys), np.concatenate(gid))


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
        lin.weight.data.copy_(torch.tensor(w, dtype=torch.float32).view(o, i))
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
    a = ap.parse_args()

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"device {dev}", flush=True)
    tok, msk, stt, y, gid = load(a.data, dev)
    print(f"total {len(y):,} rows, {len(np.unique(gid)):,} games", flush=True)

    uniq = np.unique(gid)
    rng = np.random.default_rng(0)
    rng.shuffle(uniq)
    val_games = set(uniq[: int(len(uniq) * a.val_frac)].tolist())
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

    best_auc, best_js, since_best = 0.0, None, 0
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
        if vauc > best_auc:
            best_auc = vauc
            best_js = net.export()
            best_js.update({"val_auc": float(vauc), "val_mse": float(vmse), "epoch": ep})
            since_best = 0
        else:
            since_best += 1
            if since_best >= a.patience:
                print(f"early stop at ep{ep} (no val-AUC best in {a.patience} epochs; best {best_auc:.4f})", flush=True)
                break

    with open(a.out, "w") as f:
        json.dump(best_js, f)
    print(f"saved {a.out}  (best val_auc {best_auc:.4f})", flush=True)


if __name__ == "__main__":
    main()
