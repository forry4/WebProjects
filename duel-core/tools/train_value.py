"""Phase 2: train an outcome value net for Spender Duel, to replace the heuristic MCTS leaf.

Reads the harvest CSVs (game_id, seat, 275 features, outcome), trains a small MLP to
predict the game OUTCOME from a position (the mover's eventual win/loss, in [-1,1]), and
exports weights as JSON for the Rust forward pass.

Two disciplines that the prior campaigns proved are load-bearing:
  * GAME-SPLIT holdout, not position-split. Positions within a game are correlated (they
    share an outcome label); splitting by position leaks the answer into validation and
    every metric looks better than it is. We split by game_id.
  * Z-SCORE the inputs from the TRAIN corpus. The encoder deliberately leaves one feature
    (the heuristic standing-diff) unsquashed at +-4.7 while most are ~[0,1]; without
    standardization that feature dominates the first layer.

The export is the parity contract with Rust: value(x) = tanh(L3 relu(L2 relu(L1 z))) with
z = (x - mu)/sd. We also dump a handful of (raw_features -> value) samples so the Rust
port can assert it reproduces this net bit-closely before it's ever trusted in a gate.

    python duel-core/tools/train_value.py --data "C:/Users/Forrest/duel_run/shard_*.csv" \
        --out duel-core/src/value_net.json
"""
import argparse
import glob
import json
import os
import sys

import numpy as np
import torch
import torch.nn as nn


def load(data_glob, dev):
    """Load every shard STRAIGHT TO THE GPU, one shard at a time.

    The box routinely has <1GB free host RAM, so materializing the whole ~1M-row corpus
    in numpy (1.1GB of features alone) OOMs. Each shard (~100k rows, ~110MB) is parsed,
    pushed to the GPU, and freed before the next — peak host use stays ~one shard while
    the full corpus accumulates in the 6GB VRAM (the CoC-trainer pattern). game_id is
    per-shard, so offset it to stay unique across shards for the game-split holdout.
    """
    files = sorted(glob.glob(data_glob))
    if not files:
        sys.exit(f"no CSVs match {data_glob}")
    Xs, Ys, Gs, header = [], [], [], None
    for k, path in enumerate(files):
        arr = np.loadtxt(path, delimiter=",", skiprows=1, dtype=np.float32)
        with open(path) as f:
            header = header or f.readline().strip().split(",")
        Xs.append(torch.tensor(arr[:, 2:-1], device=dev))              # features
        Ys.append(torch.tensor(arr[:, -1], device=dev))                # outcome
        Gs.append(torch.tensor(arr[:, 0].astype(np.int64) + k * 10_000_000))  # unique gid (CPU)
        print(f"  {os.path.basename(path)}: {len(arr):,} rows", flush=True)
        del arr
    X = torch.cat(Xs); Y = torch.cat(Ys); G = torch.cat(Gs).numpy()
    names = header[2:-1]
    print(f"total: {len(X):,} rows, {X.shape[1]} features, {len(np.unique(G)):,} games")
    return X, Y, G, names


class Net(nn.Module):
    def __init__(self, d_in, h=256, dropout=0.0):
        super().__init__()
        # Dropout matters here: 1M rows are only ~9,900 GAMES, and rows within a game
        # share a label, so the effective sample size is ~games. Without it the net
        # memorizes fast (val MSE climbed 0.86 -> 1.39 over 60 epochs). Dropout is
        # inference-time identity, so the EXPORTED net (eval mode) is a plain MLP — the
        # Rust forward pass needs no knowledge of it.
        self.net = nn.Sequential(
            nn.Linear(d_in, h), nn.ReLU(), nn.Dropout(dropout),
            nn.Linear(h, h), nn.ReLU(), nn.Dropout(dropout),
            nn.Linear(h, 1), nn.Tanh(),
        )

    def forward(self, x):
        return self.net(x).squeeze(-1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="glob of shard CSVs")
    ap.add_argument("--out", default="duel-core/src/value_net.json")
    ap.add_argument("--hidden", type=int, default=256)
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--batch", type=int, default=8192)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--wd", type=float, default=1e-5)
    ap.add_argument("--dropout", type=float, default=0.0)
    ap.add_argument("--val-frac", type=float, default=0.1)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    torch.manual_seed(args.seed); np.random.seed(args.seed)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    X, Y, G, names = load(args.data, dev)                          # X, Y already on GPU

    # game-split holdout (positions within a game share a label — split by GAME)
    games = np.unique(G)
    rng = np.random.default_rng(args.seed)
    rng.shuffle(games)
    n_val = int(len(games) * args.val_frac)
    val_games = set(games[:n_val].tolist())
    is_val = np.isin(G, list(val_games))
    tr, va = ~is_val, is_val
    print(f"train {tr.sum():,} rows / {len(games)-n_val:,} games | "
          f"val {va.sum():,} rows / {n_val:,} games")

    tr_t = torch.tensor(np.where(tr)[0], device=dev)
    va_t = torch.tensor(np.where(va)[0], device=dev)
    mu = X[tr_t].mean(0); sd = X[tr_t].std(0); sd[sd < 1e-6] = 1.0  # z-score from TRAIN only
    Xt = (X - mu) / sd                                              # in-place-ish on GPU
    Yt = Y
    mu_np, sd_np = mu.cpu().numpy(), sd.cpu().numpy()

    net = Net(X.shape[1], args.hidden, args.dropout).to(dev)
    opt = torch.optim.Adam(net.parameters(), lr=args.lr, weight_decay=args.wd)
    lossf = nn.MSELoss()

    def evaluate():
        net.eval()
        with torch.no_grad():
            p = net(Xt[va_t])
            yv = Yt[va_t]
            mse = lossf(p, yv).item()
            # AUC of predicted value vs "mover won" — the metric that matters (ranking)
            won = (yv > 0).float()
            order = torch.argsort(p)
            ranks = torch.argsort(order).float() + 1
            n_pos = won.sum().item(); n_neg = (len(won) - n_pos)
            auc = ((ranks[won == 1].sum().item() - n_pos * (n_pos + 1) / 2)
                   / (n_pos * n_neg)) if n_pos and n_neg else float("nan")
        return mse, auc

    best = {"auc": -1}
    for ep in range(args.epochs):
        net.train()
        perm = tr_t[torch.randperm(len(tr_t), device=dev)]
        for i in range(0, len(perm), args.batch):
            idx = perm[i:i + args.batch]
            opt.zero_grad()
            loss = lossf(net(Xt[idx]), Yt[idx])
            loss.backward(); opt.step()
        mse, auc = evaluate()
        tag = ""
        if auc > best["auc"]:
            best = {"auc": auc, "mse": mse, "state": {k: v.detach().cpu().clone()
                                                      for k, v in net.state_dict().items()}}
            tag = "  <- best"
        print(f"  ep {ep:2d}  val MSE {mse:.4f}  AUC {auc:.4f}{tag}", flush=True)

    net.load_state_dict(best["state"])
    print(f"\nbest: val MSE {best['mse']:.4f}  AUC {best['auc']:.4f}")

    # export (the Rust parity contract) — find the Linear layers by type so dropout /
    # arch changes can't silently misalign the indices.
    linears = [m for m in net.net if isinstance(m, nn.Linear)]
    layers = [{"w": m.weight.detach().cpu().numpy().tolist(),
               "b": m.bias.detach().cpu().numpy().tolist()} for m in linears]
    # parity samples: raw features (pre-zscore) -> value, for the Rust export check
    net.eval()
    with torch.no_grad():
        si = np.random.default_rng(1).choice(len(X), 32, replace=False).tolist()
        samples = [{"x": X[j].cpu().numpy().tolist(),
                    "v": float(net(Xt[j:j + 1])[0])} for j in si]
    blob = {"arch": [X.shape[1], args.hidden, args.hidden, 1],
            "mu": mu_np.tolist(), "sd": sd_np.tolist(), "layers": layers,
            "val_auc": best["auc"], "val_mse": best["mse"], "samples": samples}
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(blob, f)
    print(f"wrote {args.out}  ({X.shape[1]}->{args.hidden}->{args.hidden}->1)")


if __name__ == "__main__":
    main()
