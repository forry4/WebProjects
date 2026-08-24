"""Train the attention VALUE net WITH AUXILIARY targets (multi-task regularization).

The aux heads (card-margin, crown-margin, win-condition, game-length — all game-final, from the
mover's seat) are TRAINING-ONLY: they force the shared trunk to encode development-relevant
structure, aiming to sharpen the value head's develop-vs-take sensitivity (the under-development
blind spot) WITHOUT changing what is served. Only the value path is exported (`net.export()`), so
`attn.rs` and the parity contract are unchanged — the result drops straight into serving.

Reads the `harvest_aux` CSV (harvest_attn schema + 4 trailing aux cols). GAME-SPLIT holdout. Select
by value val-AUC (the value head is what we serve). `--aux-w 0` = value-only CONTROL on the SAME
corpus — the honest baseline to isolate the aux effect from the (lower-sim) harvest distribution:
gate aux-net vs control-net, not just vs v2.

  # control (value-only) and aux, SAME corpus:
  python train_attn_aux.py --data ".../aux/shard_*.csv" --aux-w 0   --out .../control.json
  python train_attn_aux.py --data ".../aux/shard_*.csv" --aux-w 0.3 --out .../aux.json
"""
import argparse, glob, os, sys, json
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from attn_net import AttnNet, TOK_F, TOK_N, TOK_STATE  # noqa: E402

TOKS = TOK_N * TOK_F
O = 2 + TOKS + TOK_N + TOK_STATE  # index of hval; outcome=O+1, then the 4 aux cols


def load(glob_pat, dev):
    files = sorted(glob.glob(glob_pat))
    if not files:
        sys.exit(f"no CSVs match {glob_pat}")
    tk, mk, st, ys, cardm, crownm, wincond, glen, gid = [], [], [], [], [], [], [], [], []
    for k, path in enumerate(files):
        arr = np.loadtxt(path, delimiter=",", skiprows=1, dtype=np.float32)
        if arr.shape[1] < O + 6:
            sys.exit(f"{path}: {arr.shape[1]} cols, expected >= {O + 6} (aux corpus). Re-harvest with harvest_aux.")
        gid.append(arr[:, 0].astype(np.int64) + k * 10_000_000)
        tk.append(torch.tensor(arr[:, 2:2 + TOKS], device=dev).view(-1, TOK_N, TOK_F))
        mk.append(torch.tensor(arr[:, 2 + TOKS:2 + TOKS + TOK_N], device=dev))
        st.append(torch.tensor(arr[:, 2 + TOKS + TOK_N:O], device=dev))
        ys.append(torch.tensor(arr[:, O + 1], device=dev))                         # outcome +-1
        cardm.append(torch.tensor(arr[:, O + 2] / 15.0, device=dev))               # card margin
        crownm.append(torch.tensor(arr[:, O + 3] / 10.0, device=dev))              # crown margin
        wincond.append(torch.tensor((arr[:, O + 4] - 1.0).clip(0, 2), device=dev)) # 1/2/3 -> class 0/1/2
        glen.append(torch.tensor(arr[:, O + 5] / 50.0, device=dev))               # game length
        print(f"  {os.path.basename(path)}: {len(arr):,} rows", flush=True)
        del arr
    cat = lambda xs: torch.cat(xs)
    return (cat(tk), cat(mk), cat(st), cat(ys), cat(cardm), cat(crownm),
            cat(wincond).long(), cat(glen), np.concatenate(gid))


def auc(scores, labels):
    order = np.argsort(scores); ranks = np.empty(len(scores)); ranks[order] = np.arange(1, len(scores) + 1)
    npos = int(labels.sum()); nneg = len(labels) - npos
    if npos == 0 or nneg == 0:
        return 0.5
    return (ranks[labels == 1].sum() - npos * (npos + 1) / 2) / (npos * nneg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--aux-w", type=float, default=0.3, help="aux loss weight (0 = value-only CONTROL)")
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--bs", type=int, default=4096)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--weight-decay", type=float, default=2e-4)
    ap.add_argument("--val-frac", type=float, default=0.08)
    ap.add_argument("--patience", type=int, default=12)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    torch.manual_seed(a.seed)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"device {dev}  aux_w {a.aux_w}", flush=True)
    tok, msk, stt, y, cardm, crownm, wincond, glen, gid = load(a.data, dev)
    print(f"total {len(y):,} rows, {len(np.unique(gid)):,} games", flush=True)

    uniq = np.unique(gid); rng = np.random.default_rng(0); rng.shuffle(uniq)
    val_games = set(uniq[: int(len(uniq) * a.val_frac)].tolist())
    is_val = torch.tensor(np.fromiter((g in val_games for g in gid), bool, len(gid)), device=dev)
    idx_tr = torch.nonzero(~is_val).squeeze(1)
    idx_val = torch.nonzero(is_val).squeeze(1)

    net = AttnNet().to(dev)
    opt = torch.optim.Adam(net.parameters(), lr=a.lr, weight_decay=a.weight_decay)
    mse = nn.MSELoss()
    use_aux = a.aux_w > 0.0

    best_auc, best_js, since = 0.0, None, 0
    for ep in range(a.epochs):
        net.train()
        perm = idx_tr[torch.randperm(len(idx_tr), device=dev)]
        tot = 0.0
        for i in range(0, len(perm), a.bs):
            b = perm[i:i + a.bs]
            opt.zero_grad()
            if use_aux:
                v, pc, pcr, pwc, pl = net.forward_aux(tok[b], msk[b], stt[b])
                vloss = mse(v, y[b])
                aloss = (mse(pc, cardm[b]) + mse(pcr, crownm[b]) + mse(pl, glen[b])
                         + F.cross_entropy(pwc, wincond[b]))
                loss = vloss + a.aux_w * aloss
            else:
                loss = mse(net(tok[b], msk[b], stt[b]), y[b])
            loss.backward(); opt.step()
            tot += loss.item() * len(b)
        net.eval()
        with torch.no_grad():
            vp = torch.cat([net(tok[b], msk[b], stt[b]) for b in idx_val.split(16384)])
            vy = y[idx_val]
            vmse = mse(vp, vy).item()
            vauc = auc(vp.cpu().numpy(), (vy.cpu().numpy() > 0).astype(int))
        tag = ""
        if vauc > best_auc:
            best_auc, since = vauc, 0
            best_js = net.export()
            best_js.update({"val_auc": float(vauc), "val_mse": float(vmse), "epoch": ep, "aux_w": a.aux_w})
            tag = "  <- best"
        else:
            since += 1
        print(f"ep{ep:02d}  train_loss {tot/len(idx_tr):.4f}  val_mse {vmse:.4f}  val_auc {vauc:.4f}{tag}", flush=True)
        if since >= a.patience:
            print(f"early stop ep{ep} (best val_auc {best_auc:.4f})", flush=True)
            break

    with open(a.out, "w") as f:
        json.dump(best_js, f)
    print(f"saved {a.out}  (best val_auc {best_auc:.4f}, aux_w {a.aux_w})", flush=True)


if __name__ == "__main__":
    main()
