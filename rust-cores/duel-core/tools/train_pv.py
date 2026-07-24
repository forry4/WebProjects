"""Phase 3 chunk 2: train a policy+value net for Spender Duel.

The policy head is the point — it will guide the MCTS as a PUCT PRIOR while the search
KEEPS the heuristic value leaf (the value-leaf-degrades-at-depth finding). The value head
is trained alongside (free, and useful for future use) but is NOT what we serve at the
leaf.

Reads the `harvest_pv` binary (DUELPV01): per row `u32 game_id, f32x275 feats, f32
outcome, u16 n_legal, n_legal x (u16 action_idx, f32 target_prob)`. The target_prob is
softmax(mean-Q / T) over the LEGAL moves (NOT visit counts — Duel's visits are near-
uniform; the Q signal is the real one). We reconstruct a dense 320-policy + a legal mask.

Disciplines carried from the value trainer:
  * GAME-SPLIT holdout (rows within a game share correlated targets).
  * z-score inputs from TRAIN.
  * STREAM shards straight to the GPU (the box has <1GB free host RAM; the 6GB VRAM holds
    the ~1M-row corpus: features + dense policy + mask ~= 2.6GB).

Losses: value = MSE to outcome; policy = cross-entropy of the masked-softmax logits
against the soft target. Metric that matters for a prior: policy TOP-1 (does the net's
masked-argmax match the target's argmax = the search's greedy pick) and the value AUC.

    python duel-core/tools/train_pv.py --data "C:/Users/Forrest/duel_run/pv/pv_*.bin" \
        --out duel-core/src/pv_net.json
"""
import argparse
import glob
import json
import os
import struct
import sys

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

MAGIC = b"DUELPV01"


def read_shard(path, dev, gid_offset):
    """Parse one binary shard straight into GPU tensors (X, value, policy, mask, gid)."""
    with open(path, "rb") as f:
        buf = f.read()
    assert buf[:8] == MAGIC, f"{path}: bad magic {buf[:8]!r}"
    n_feats, n_act = struct.unpack_from("<II", buf, 8)
    pos = 16
    mv = memoryview(buf)
    # First count rows (variable length) so we can preallocate.
    rows = []
    p = pos
    while p < len(buf):
        # u32 gid + n_feats f32 + f32 outcome + u16 n_legal
        head = 4 + n_feats * 4 + 4
        gid = struct.unpack_from("<I", mv, p)[0]
        n_legal = struct.unpack_from("<H", mv, p + head)[0]
        rows.append((p, gid, n_legal))
        p += head + 2 + n_legal * 6
    n = len(rows)
    X = np.empty((n, n_feats), dtype=np.float32)
    val = np.empty(n, dtype=np.float32)
    pol = np.zeros((n, n_act), dtype=np.float32)
    mask = np.zeros((n, n_act), dtype=np.bool_)
    gid = np.empty(n, dtype=np.int64)
    fstr = "<%df" % n_feats
    for r, (p, g, n_legal) in enumerate(rows):
        X[r] = struct.unpack_from(fstr, mv, p + 4)
        val[r] = struct.unpack_from("<f", mv, p + 4 + n_feats * 4)[0]
        gid[r] = g + gid_offset
        base = p + 4 + n_feats * 4 + 4 + 2
        for k in range(n_legal):
            idx, prob = struct.unpack_from("<Hf", mv, base + k * 6)
            mask[r, idx] = True
            pol[r, idx] = prob
    return (torch.tensor(X, device=dev), torch.tensor(val, device=dev),
            torch.tensor(pol, device=dev), torch.tensor(mask, device=dev),
            gid, n_act)


def load(data_glob, dev):
    files = sorted(glob.glob(data_glob))
    if not files:
        sys.exit(f"no PV shards match {data_glob}")
    Xs, Vs, Ps, Ms, Gs, n_act = [], [], [], [], [], None
    for k, path in enumerate(files):
        X, v, p, m, g, na = read_shard(path, dev, k * 10_000_000)
        n_act = na
        Xs.append(X); Vs.append(v); Ps.append(p); Ms.append(m); Gs.append(g)
        print(f"  {os.path.basename(path)}: {len(X):,} rows", flush=True)
    X = torch.cat(Xs); V = torch.cat(Vs); P = torch.cat(Ps); M = torch.cat(Ms)
    G = np.concatenate(Gs)
    print(f"total: {len(X):,} rows, {X.shape[1]} feats, {n_act} actions, "
          f"{len(np.unique(G)):,} games")
    return X, V, P, M, G, n_act


class PVNet(nn.Module):
    def __init__(self, d_in, n_act, h=256, dropout=0.3):
        super().__init__()
        self.trunk = nn.Sequential(
            nn.Linear(d_in, h), nn.ReLU(), nn.Dropout(dropout),
            nn.Linear(h, h), nn.ReLU(), nn.Dropout(dropout),
        )
        self.value = nn.Linear(h, 1)
        self.policy = nn.Linear(h, n_act)

    def forward(self, x):
        z = self.trunk(x)
        return torch.tanh(self.value(z)).squeeze(-1), self.policy(z)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", default="duel-core/src/pv_net.json")
    ap.add_argument("--hidden", type=int, default=256)
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--batch", type=int, default=8192)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--wd", type=float, default=3e-4)
    ap.add_argument("--dropout", type=float, default=0.3)
    ap.add_argument("--policy-w", type=float, default=1.0, help="policy loss weight")
    ap.add_argument("--val-frac", type=float, default=0.1)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    torch.manual_seed(args.seed); np.random.seed(args.seed)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    X, V, P, M, G, n_act = load(args.data, dev)

    games = np.unique(G)
    rng = np.random.default_rng(args.seed); rng.shuffle(games)
    n_val = int(len(games) * args.val_frac)
    val_games = set(games[:n_val].tolist())
    is_val = np.isin(G, list(val_games))
    tr_t = torch.tensor(np.where(~is_val)[0], device=dev)
    va_t = torch.tensor(np.where(is_val)[0], device=dev)
    print(f"train {len(tr_t):,} / val {len(va_t):,} rows", flush=True)

    mu = X[tr_t].mean(0); sd = X[tr_t].std(0); sd[sd < 1e-6] = 1.0
    Xz = (X - mu) / sd
    mu_np, sd_np = mu.cpu().numpy(), sd.cpu().numpy()

    net = PVNet(X.shape[1], n_act, args.hidden, args.dropout).to(dev)
    opt = torch.optim.Adam(net.parameters(), lr=args.lr, weight_decay=args.wd)
    NEG = torch.finfo(torch.float32).min

    def masked_logp(logits, mask):
        return F.log_softmax(logits.masked_fill(~mask, NEG), dim=1)

    def evaluate():
        net.eval()
        with torch.no_grad():
            vp, lp = net(Xz[va_t])
            yv = V[va_t]
            vmse = F.mse_loss(vp, yv).item()
            won = (yv > 0).float()
            order = torch.argsort(vp); ranks = torch.argsort(order).float() + 1
            npos = won.sum().item(); nneg = len(won) - npos
            auc = ((ranks[won == 1].sum().item() - npos * (npos + 1) / 2) / (npos * nneg)
                   if npos and nneg else float("nan"))
            logp = masked_logp(lp, M[va_t])
            tgt = P[va_t]
            pce = -(tgt * logp).sum(1).mean().item()
            # top-1: the net's masked-argmax vs the target's argmax (the search's pick)
            net_pick = logp.argmax(1)
            tgt_pick = tgt.argmax(1)
            top1 = (net_pick == tgt_pick).float().mean().item()
        return vmse, auc, pce, top1

    best = {"score": -1}
    for ep in range(args.epochs):
        net.train()
        perm = tr_t[torch.randperm(len(tr_t), device=dev)]
        for i in range(0, len(perm), args.batch):
            idx = perm[i:i + args.batch]
            vp, lp = net(Xz[idx])
            vloss = F.mse_loss(vp, V[idx])
            ploss = -(P[idx] * masked_logp(lp, M[idx])).sum(1).mean()
            loss = vloss + args.policy_w * ploss
            opt.zero_grad(); loss.backward(); opt.step()
        vmse, auc, pce, top1 = evaluate()
        # select on policy top-1 (the prior's quality is the point)
        tag = ""
        if top1 > best["score"]:
            best = {"score": top1, "vmse": vmse, "auc": auc, "pce": pce, "top1": top1,
                    "state": {k: v.detach().cpu().clone() for k, v in net.state_dict().items()}}
            tag = "  <- best"
        print(f"  ep {ep:2d}  vMSE {vmse:.4f} AUC {auc:.4f} | pCE {pce:.4f} top1 {top1:.4f}{tag}",
              flush=True)

    net.load_state_dict(best["state"])
    print(f"\nbest: value AUC {best['auc']:.4f} | policy top1 {best['top1']:.4f} "
          f"(CE {best['pce']:.4f})")

    # export (Rust parity contract): trunk layers + value head + policy head, mu/sd, samples
    sdct = net.state_dict()
    def lin(name):
        return {"w": sdct[f"{name}.weight"].cpu().numpy().tolist(),
                "b": sdct[f"{name}.bias"].cpu().numpy().tolist()}
    trunk = [lin("trunk.0"), lin("trunk.3")]
    net.eval()
    with torch.no_grad():
        si = np.random.default_rng(1).choice(len(X), 32, replace=False).tolist()
        samples = []
        for j in si:
            v, l = net(Xz[j:j + 1])
            samples.append({"x": X[j].cpu().numpy().tolist(),
                            "v": float(v[0]), "logits": l[0].cpu().numpy().tolist()})
    blob = {"n_feats": X.shape[1], "n_act": n_act, "hidden": args.hidden,
            "mu": mu_np.tolist(), "sd": sd_np.tolist(),
            "trunk": trunk, "value": lin("value"), "policy": lin("policy"),
            "val_auc": best["auc"], "policy_top1": best["top1"], "samples": samples}
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(blob, f)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
