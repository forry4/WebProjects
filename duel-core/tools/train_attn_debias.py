"""Human-game value DEBIAS: warm-start from the shipped v2 attention net and gently fine-tune on a
strong-play ANCHOR (v3 self-play shards, to prevent forgetting) + the human bot-loss positions
REPLICATED K times (clean up-weighting). The point is to inject the ONE signal self-play cannot
generate — that patient development wins the long game — via the true LOSS label on the bot's own
under-developed positions. NOT imitation (the demonstrator is below-average): we relabel the bot's
OWN positions with the real outcome, never copy the human's moves.

Same row schema as harvest_attn / featurize_positions (game_id,seat,tok*300,mask*15,st*46,hval,outcome),
so the SAME loader reads corpus + human. Exports the parity JSON `attn.rs` ingests (identical to
train_attn's export), then `gate_netleaf --leaf attnfile --attn-file <out> --leaf-b attnval` gates it
vs v2 at equal sims (== equal time; same D=64 arch).

  python train_attn_debias.py --corpus "C:/Users/Forrest/duel_run/v3/shard_[0-2].csv" \
      --human .../human_train.csv --init duel-core/src/attn_value_net.json \
      --k 20 --out C:/Users/Forrest/duel_run/debias/attn_k20.json
"""
import argparse, glob, json, os, sys
import numpy as np
import torch
import torch.nn as nn

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from attn_net import AttnNet, TOK_F, TOK_N, TOK_STATE  # noqa: E402

TOKS = TOK_N * TOK_F


def load_csv(path, dev, gid_offset):
    arr = np.loadtxt(path, delimiter=",", skiprows=1, dtype=np.float32)
    if arr.ndim == 1:
        arr = arr[None, :]
    gid = arr[:, 0].astype(np.int64) + gid_offset
    tk = torch.tensor(arr[:, 2:2 + TOKS], device=dev).view(-1, TOK_N, TOK_F)
    mk = torch.tensor(arr[:, 2 + TOKS:2 + TOKS + TOK_N], device=dev)
    st = torch.tensor(arr[:, 2 + TOKS + TOK_N:2 + TOKS + TOK_N + TOK_STATE], device=dev)
    y = torch.tensor(arr[:, -1], device=dev)
    return tk, mk, st, y, gid


def load_glob(pat, dev):
    files = sorted(glob.glob(pat))
    if not files:
        sys.exit(f"no CSVs match {pat}")
    tks, mks, sts, ys, gids = [], [], [], [], []
    for k, p in enumerate(files):
        tk, mk, st, y, gid = load_csv(p, dev, k * 10_000_000)
        tks.append(tk); mks.append(mk); sts.append(st); ys.append(y); gids.append(gid)
        print(f"  {os.path.basename(p)}: {len(y):,} rows", flush=True)
    return (torch.cat(tks), torch.cat(mks), torch.cat(sts), torch.cat(ys),
            np.concatenate(gids))


def load_weights(net, js):
    """Inverse of AttnNet.export(): assign flattened JSON weights back into the torch net."""
    def setlin(lin, w, b=None):
        o, i = lin.weight.shape
        # copy_ into the existing params so their device (cuda) is preserved
        lin.weight.data.copy_(torch.tensor(w, dtype=torch.float32).view(o, i))
        if b is not None:
            lin.bias.data.copy_(torch.tensor(b, dtype=torch.float32))
    setlin(net.emb, js["emb_w"], js["emb_b"])
    for l in range(len(net.wq)):
        setlin(net.wq[l], js["wq"][l]); setlin(net.wk[l], js["wk"][l])
        setlin(net.wv[l], js["wv"][l]); setlin(net.wo[l], js["wo"][l])
        setlin(net.f1[l], js["f1w"][l], js["f1b"][l]); setlin(net.f2[l], js["f2w"][l], js["f2b"][l])
    setlin(net.s, js["sw"], js["sb"]); setlin(net.t, js["tw"], js["tb"]); setlin(net.v, js["vw"], js["vb"])


def auc(scores, labels):
    order = np.argsort(scores); ranks = np.empty(len(scores)); ranks[order] = np.arange(1, len(scores) + 1)
    npos = int(labels.sum()); nneg = len(labels) - npos
    if npos == 0 or nneg == 0:
        return 0.5
    return (ranks[labels == 1].sum() - npos * (npos + 1) / 2) / (npos * nneg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True, help="glob of anchor shards (strong-play)")
    ap.add_argument("--human", required=True, help="human_train.csv (featurized bot loss/win positions)")
    ap.add_argument("--init", required=True, help="v2 attn_value_net.json (warm start)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--k", type=int, default=20, help="human-row replication factor (up-weight)")
    ap.add_argument("--holdout-human", type=int, default=6, help="hold out every Nth human game (by gid modulo N)")
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--bs", type=int, default=4096)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--weight-decay", type=float, default=2e-4)
    a = ap.parse_args()

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"device {dev}", flush=True)

    print("corpus (anchor):", flush=True)
    ctk, cmk, cst, cy, cgid = load_glob(a.corpus, dev)
    print("human:", flush=True)
    htk, hmk, hst, hy, hgid = load_csv(a.human, dev, 900_000_000)  # offset so human gids never collide
    hgid_raw = hgid - 900_000_000

    # Hold out some human GAMES entirely (by raw gid) to test debias generalization.
    hold_mask = (hgid_raw % a.holdout_human) == (a.holdout_human - 1)
    tr_h = ~hold_mask
    n_hold_games = len(np.unique(hgid_raw[hold_mask]))
    print(f"human: {len(hy):,} positions, {len(np.unique(hgid_raw))} games; "
          f"holding out {n_hold_games} games ({hold_mask.sum()} positions)", flush=True)

    # Corpus val split (game-split) for a don't-regress AUC check.
    uniq = np.unique(cgid); rng = np.random.default_rng(0); rng.shuffle(uniq)
    val_c = set(uniq[: max(1, int(len(uniq) * 0.06))].tolist())
    cval = torch.tensor(np.fromiter((g in val_c for g in cgid), bool, len(cgid)), device=dev)

    # Build the TRAIN set: all corpus-train rows + human-train rows replicated K times.
    tr_h_idx = torch.tensor(np.where(tr_h)[0], device=dev)
    htk_tr, hmk_tr, hst_tr, hy_tr = htk[tr_h_idx], hmk[tr_h_idx], hst[tr_h_idx], hy[tr_h_idx]
    ctr = torch.nonzero(~cval).squeeze(1)
    train_tk = torch.cat([ctk[ctr]] + [htk_tr] * a.k)
    train_mk = torch.cat([cmk[ctr]] + [hmk_tr] * a.k)
    train_st = torch.cat([cst[ctr]] + [hst_tr] * a.k)
    train_y = torch.cat([cy[ctr]] + [hy_tr] * a.k)
    print(f"train rows: {len(train_y):,} (corpus {len(ctr):,} + human {len(hy_tr):,}x{a.k}); "
          f"corpus val {int(cval.sum()):,}", flush=True)

    net = AttnNet().to(dev)
    load_weights(net, json.load(open(a.init)))

    # Baseline (v2, pre-fine-tune) on the held-out human positions — the reference for "did it move".
    hold_idx = torch.tensor(np.where(hold_mask)[0], device=dev)
    def human_hold_stats(model):
        model.eval()
        with torch.no_grad():
            p = torch.cat([model(htk[b], hmk[b], hst[b]) for b in hold_idx.split(8192)])
        yv = hy[hold_idx]
        lost = yv < 0; wonm = yv > 0
        return (p[lost].mean().item() if lost.any() else float('nan'),
                p[wonm].mean().item() if wonm.any() else float('nan'),
                nn.functional.mse_loss(p, yv).item())
    v2_lost, v2_won, v2_mse = human_hold_stats(net)
    print(f"\n[held-out human] v2 baseline:  LOST-pos mean {v2_lost:+.3f}  WON-pos mean {v2_won:+.3f}  MSE {v2_mse:.3f}", flush=True)

    opt = torch.optim.Adam(net.parameters(), lr=a.lr, weight_decay=a.weight_decay)
    lossf = nn.MSELoss()
    cval_idx = torch.nonzero(cval).squeeze(1)
    N = len(train_y)
    for ep in range(a.epochs):
        net.train()
        perm = torch.randperm(N, device=dev)
        tot = 0.0
        for i in range(0, N, a.bs):
            b = perm[i:i + a.bs]
            opt.zero_grad()
            loss = lossf(net(train_tk[b], train_mk[b], train_st[b]), train_y[b])
            loss.backward(); opt.step()
            tot += loss.item() * len(b)
        net.eval()
        with torch.no_grad():
            vp = torch.cat([net(ctk[b], cmk[b], cst[b]) for b in cval_idx.split(16384)])
            vy = cy[cval_idx]
            cauc = auc(vp.cpu().numpy(), (vy.cpu().numpy() > 0).astype(int))
        hl, hw, hm = human_hold_stats(net)
        print(f"ep{ep:02d}  train_mse {tot/N:.4f}  corpus_val_auc {cauc:.4f} | "
              f"held-human LOST {hl:+.3f} WON {hw:+.3f} MSE {hm:.3f}", flush=True)

    net.eval()
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w") as f:
        json.dump(net.export(), f)
    print(f"\nsaved {a.out}", flush=True)
    print(f"SUMMARY k={a.k}: held-out LOST-pos {v2_lost:+.3f} -> {hl:+.3f}  "
          f"(more negative = debias moved it); corpus_val_auc {cauc:.4f}", flush=True)


if __name__ == "__main__":
    main()
