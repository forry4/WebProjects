"""Train the ATTENTION policy(+value) net for the Duel AZ line.

Reads the `harvest_attn_pv` binary (DUELAP01: token-features + outcome + softmax-over-Q policy target
over the 320-action space). Warm-starts the trunk+value from the shipped v2 net, then trains a POLICY
head that the determinized PUCT will use as a PRIOR (`actions.rs` is the shared index space).

TWO MODES:
  * --freeze-trunk (DEFAULT): freeze EVERYTHING except the policy head. The value leaf then stays
    BYTE-IDENTICAL to v2, so the Stage-1 gate isolates exactly one variable — does the policy prior
    help this search? — with no value-drift confound. Trains in minutes (a 128->320 linear).
  * --no-freeze-trunk: co-train value (MSE to outcome) + policy (masked CE), warm from v2. The full
    AZ net for the iteration loop (value may drift on a small corpus — gate the WHOLE net then).

Exports the parity JSON `attn.rs` ingests via `export_pv()` (value path + pw/pb). Model selection is
by POLICY top-1 accuracy on a GAME-SPLIT holdout (the prior-quality metric), with policy CE + value
AUC also reported.

  python train_attn_pv.py --data "C:/Users/Forrest/duel_run/pv/shard_*.bin" \
      --init duel-core/src/attn_value_net.json --out C:/Users/Forrest/duel_run/pv/pv_policy.json
"""
import argparse, glob, os, struct, sys, json
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from attn_net import AttnNet, TOK_F, TOK_N, TOK_STATE, N_ACTIONS  # noqa: E402

TOK_LEN = TOK_N * TOK_F
FEAT = TOK_LEN + TOK_N + TOK_STATE
ENTDT = np.dtype([("i", "<u2"), ("p", "<f4")])


def load_weights(net, js):
    """Inverse of AttnNet.export(): assign flattened JSON weights into the torch net's value path."""
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


def parse_bin(path, gid_offset):
    """Parse one DUELAP01 shard -> (feats[N,FEAT], outcome[N], gid[N], entries: list of (idx,prob))."""
    with open(path, "rb") as f:
        buf = f.read()
    if buf[:8] != b"DUELAP01":
        sys.exit(f"{path}: bad magic {buf[:8]!r} (expected DUELAP01)")
    tok_n, tok_f, tok_state, n_act = struct.unpack_from("<4I", buf, 8)
    if (tok_n, tok_f, tok_state, n_act) != (TOK_N, TOK_F, TOK_STATE, N_ACTIONS):
        sys.exit(f"{path}: header {(tok_n, tok_f, tok_state, n_act)} != {(TOK_N, TOK_F, TOK_STATE, N_ACTIONS)}")
    off, N = 24, len(buf)
    fb = FEAT * 4
    gids, feats, outs, eidx, eprob = [], [], [], [], []
    while off < N:
        gid = struct.unpack_from("<I", buf, off)[0]; off += 4
        feats.append(np.frombuffer(buf, np.float32, FEAT, off)); off += fb
        outs.append(struct.unpack_from("<f", buf, off)[0]); off += 4
        nl = struct.unpack_from("<H", buf, off)[0]; off += 2
        e = np.frombuffer(buf, ENTDT, nl, off); off += nl * 6
        gids.append(gid + gid_offset)
        eidx.append(e["i"].astype(np.int64)); eprob.append(e["p"].astype(np.float32))
    return (np.stack(feats), np.asarray(outs, np.float32), np.asarray(gids, np.int64), eidx, eprob)


def load(glob_pat):
    files = sorted(glob.glob(glob_pat))
    if not files:
        sys.exit(f"no .bin match {glob_pat}")
    F_, O_, G_, EI, EP = [], [], [], [], []
    for k, p in enumerate(files):
        f, o, g, ei, ep = parse_bin(p, k * 10_000_000)
        F_.append(f); O_.append(o); G_.append(g); EI += ei; EP += ep
        print(f"  {os.path.basename(p)}: {len(o):,} rows", flush=True)
    feats = np.concatenate(F_); out = np.concatenate(O_); gid = np.concatenate(G_)
    maxleg = max(len(x) for x in EI)
    n = len(out)
    idx_pad = np.full((n, maxleg), -1, np.int64)
    prob_pad = np.zeros((n, maxleg), np.float32)
    for r in range(n):
        m = len(EI[r])
        idx_pad[r, :m] = EI[r]
        prob_pad[r, :m] = EP[r]
    return feats, out, gid, idx_pad, prob_pad, maxleg


def build_dense(idx_b, prob_b, dev):
    """Sparse padded entries -> dense target[bs,320] + legal mask[bs,320] on `dev`."""
    bs = idx_b.shape[0]
    valid = (idx_b >= 0).float()
    safe = idx_b.clamp(min=0)
    target = torch.zeros(bs, N_ACTIONS, device=dev).scatter_add_(1, safe, prob_b)
    legal = torch.zeros(bs, N_ACTIONS, device=dev).scatter_add_(1, safe, valid)
    return target, (legal > 0.5)


def policy_loss(logits, target, legal):
    """Masked soft-target cross-entropy. Illegal logits are pushed out of the softmax; the numerator
    only sums legal moves (target is 0 elsewhere, so a finite masked logp gives 0*finite=0, no NaN)."""
    logp = torch.log_softmax(logits.masked_fill(~legal, -1e9), dim=1)
    return -(target * logp).sum(1).mean()


def policy_top1_acc(logits, target, legal):
    """Fraction where the policy's legal-masked argmax == the target's argmax (the search's best move)."""
    pred = logits.masked_fill(~legal, -1e9).argmax(1)
    tgt = target.argmax(1)
    return (pred == tgt).float().mean().item()


def auc(scores, labels):
    order = np.argsort(scores); ranks = np.empty(len(scores)); ranks[order] = np.arange(1, len(scores) + 1)
    npos = int(labels.sum()); nneg = len(labels) - npos
    if npos == 0 or nneg == 0:
        return 0.5
    return (ranks[labels == 1].sum() - npos * (npos + 1) / 2) / (npos * nneg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="glob of DUELAP01 .bin shards")
    ap.add_argument("--init", required=True, help="v2 attn_value_net.json to warm-start the trunk+value")
    ap.add_argument("--out", required=True)
    ap.add_argument("--freeze-trunk", dest="freeze", action="store_true", default=True,
                    help="train ONLY the policy head; value stays == v2 (default, clean gate)")
    ap.add_argument("--no-freeze-trunk", dest="freeze", action="store_false",
                    help="co-train value+policy (the full AZ net; value may drift)")
    ap.add_argument("--value-w", type=float, default=1.0, help="value MSE weight when co-training")
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--bs", type=int, default=4096)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--weight-decay", type=float, default=1e-4)
    ap.add_argument("--val-frac", type=float, default=0.08)
    ap.add_argument("--patience", type=int, default=12)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    torch.manual_seed(a.seed)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"device {dev}  freeze_trunk {a.freeze}", flush=True)

    feats, out, gid, idx_pad, prob_pad, maxleg = load(a.data)
    print(f"total {len(out):,} rows, {len(np.unique(gid)):,} games, maxleg {maxleg}", flush=True)

    tok = torch.tensor(feats[:, :TOK_LEN], device=dev).view(-1, TOK_N, TOK_F)
    msk = torch.tensor(feats[:, TOK_LEN:TOK_LEN + TOK_N], device=dev)
    stt = torch.tensor(feats[:, TOK_LEN + TOK_N:FEAT], device=dev)
    y = torch.tensor(out, device=dev)
    idxp = torch.tensor(idx_pad, device=dev)
    probp = torch.tensor(prob_pad, device=dev)

    uniq = np.unique(gid); rng = np.random.default_rng(0); rng.shuffle(uniq)
    val_games = set(uniq[: int(len(uniq) * a.val_frac)].tolist())
    is_val = torch.tensor(np.fromiter((g in val_games for g in gid), bool, len(gid)), device=dev)
    idx_tr = torch.nonzero(~is_val).squeeze(1)
    idx_val = torch.nonzero(is_val).squeeze(1)
    print(f"train {len(idx_tr):,}  val {len(idx_val):,}", flush=True)

    net = AttnNet().to(dev)
    with open(a.init) as f:
        load_weights(net, json.load(f))
    if a.freeze:
        for p in net.parameters():
            p.requires_grad = False
        for p in net.policy.parameters():
            p.requires_grad = True
    params = [p for p in net.parameters() if p.requires_grad]
    opt = torch.optim.Adam(params, lr=a.lr, weight_decay=a.weight_decay)
    mse = nn.MSELoss()

    def run_batch(b, train):
        target, legal = build_dense(idxp[b], probp[b], dev)
        v, logits = net.forward_pv(tok[b], msk[b], stt[b])
        pl = policy_loss(logits, target, legal)
        vl = mse(v, y[b]) if not a.freeze else torch.tensor(0.0, device=dev)
        loss = pl + (a.value_w * vl if not a.freeze else 0.0)
        return loss, pl, vl, v, logits, target, legal

    best_acc, best_js, since = 0.0, None, 0
    for ep in range(a.epochs):
        net.train()
        perm = idx_tr[torch.randperm(len(idx_tr), device=dev)]
        tot = 0.0
        for i in range(0, len(perm), a.bs):
            b = perm[i:i + a.bs]
            opt.zero_grad()
            loss, pl, vl, *_ = run_batch(b, True)
            loss.backward(); opt.step()
            tot += loss.item() * len(b)
        net.eval()
        with torch.no_grad():
            accs, ces, vps = [], [], []
            for b in idx_val.split(8192):
                _, pl, _, v, logits, target, legal = run_batch(b, False)
                accs.append(policy_top1_acc(logits, target, legal) * len(b))
                ces.append(pl.item() * len(b))
                vps.append(v)
            nval = len(idx_val)
            vacc = sum(accs) / nval
            vce = sum(ces) / nval
            vp = torch.cat(vps).cpu().numpy()
            vauc = auc(vp, (y[idx_val].cpu().numpy() > 0).astype(int))
        tag = ""
        if vacc > best_acc:
            best_acc, since = vacc, 0
            best_js = net.export_pv()
            best_js.update({"val_top1": float(vacc), "val_ce": float(vce), "val_vauc": float(vauc),
                            "epoch": ep, "freeze_trunk": a.freeze})
            tag = "  <- best"
        else:
            since += 1
        print(f"ep{ep:02d}  loss {tot/len(idx_tr):.4f}  val_top1 {vacc:.4f}  val_ce {vce:.4f}  val_vauc {vauc:.4f}{tag}", flush=True)
        if since >= a.patience:
            print(f"early stop ep{ep} (best val_top1 {best_acc:.4f})", flush=True)
            break

    with open(a.out, "w") as f:
        json.dump(best_js, f)
    print(f"saved {a.out}  (best val_top1 {best_acc:.4f}, freeze_trunk {a.freeze})", flush=True)


if __name__ == "__main__":
    main()
