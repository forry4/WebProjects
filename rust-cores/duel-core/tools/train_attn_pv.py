"""Train the ATTENTION policy(+value) net for the Duel AZ line (coherent-search flywheel).

Reads the `harvest_attn_pv` binary (DUELAP02: token-features + outcome + search rootval + RAW root
stats `(action, mean_q, visits)` per legal move). Targets are built HERE, so one harvest serves any
target family:
  * --policy-target qsoftmax (default): softmax over mean-Q at --target-temp, over VISITED moves only
    (the harvest's own sanity-readout definition).
  * --policy-target visits: normalized visit counts (viable now that coherent+tight search
    concentrates visits; was garbage under per-sim PIMC).

TWO MODES:
  * --freeze-trunk (DEFAULT): freeze EVERYTHING except the policy head. The value leaf then stays
    BYTE-IDENTICAL to the donor, so the pivotal gate isolates exactly one variable — does the policy
    prior help this search? Trains in minutes (a 128->320 linear).
  * --no-freeze-trunk: co-train value (MSE to (1-b)*outcome + b*rootval, the VALUE-BOOTSTRAP target)
    + policy (masked CE), warm from the donor. The full AZ net for the iteration loop. Selection is
    by combined val loss (policy CE + value_w * value MSE); per-epoch val AUC is the F3 tripwire.

Rows with flags.policy_valid=0 (opponent seats in --leaf-b matchup harvests) contribute VALUE loss
only — pool/style games diversify the value head without foreign priors in the policy head.
Rows with flags.rootval_valid=0 (forced-move roots) use the pure outcome as the value target.

--data accepts comma-separated globs (replay buffer across iterations).

  python train_attn_pv.py --data "C:/Users/Forrest/duel_run/pv/shard_*.bin" \
      --init duel-core/src/attn_expert_net.json --out C:/Users/Forrest/duel_run/pv/pv_policy.json
"""
import argparse, glob, os, struct, sys, json
import numpy as np
import torch
import torch.nn as nn

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from attn_net import AttnNet, TOK_F, TOK_N, TOK_STATE, N_ACTIONS  # noqa: E402

TOK_LEN = TOK_N * TOK_F
FEAT = TOK_LEN + TOK_N + TOK_STATE
ENTDT = np.dtype([("i", "<u2"), ("q", "<f4"), ("n", "<f4")])  # 10 bytes/entry


def load_weights(net, js):
    """Inverse of AttnNet.export(): assign flattened JSON weights into the torch net's value path
    (+ the policy head when the donor carries one — resuming a PV champ in the loop)."""
    def setlin(lin, w, b=None):
        o, i = lin.weight.shape
        wt = torch.tensor(w, dtype=torch.float32)
        if wt.numel() == o * i:
            lin.weight.data.copy_(wt.view(o, i))
        elif wt.numel() % o == 0 and wt.numel() // o < i:
            # warm-start across a GROWN input dim (feature add): fill the original columns and ZERO
            # the new ones, so the net starts IDENTICAL to the donor and learns the rest (the same
            # trick as train_attn.py — a 20-feat champion warm-starts the 30-feat arch).
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
    if "pw" in js and js.get("pb"):
        setlin(net.policy, js["pw"], js["pb"])
        return True
    return False


def parse_bin(path, gid_offset):
    """One DUELAP02 shard -> (feats, outcome, rootval, flags, gid, entry idx/q/n lists)."""
    with open(path, "rb") as f:
        buf = f.read()
    if buf[:8] == b"DUELAP01":
        sys.exit(f"{path}: legacy DUELAP01 shard — re-harvest with the DUELAP02 harvest_attn_pv")
    if buf[:8] != b"DUELAP02":
        sys.exit(f"{path}: bad magic {buf[:8]!r} (expected DUELAP02)")
    tok_n, tok_f, tok_state, n_act = struct.unpack_from("<4I", buf, 8)
    if (tok_n, tok_f, tok_state, n_act) != (TOK_N, TOK_F, TOK_STATE, N_ACTIONS):
        sys.exit(f"{path}: header {(tok_n, tok_f, tok_state, n_act)} != {(TOK_N, TOK_F, TOK_STATE, N_ACTIONS)}")
    off, N = 24, len(buf)
    fb = FEAT * 4
    gids, feats, outs, rvs, flgs, ei, eq, en = [], [], [], [], [], [], [], []
    while off < N:
        gid = struct.unpack_from("<I", buf, off)[0]; off += 4
        feats.append(np.frombuffer(buf, np.float32, FEAT, off)); off += fb
        o, rv = struct.unpack_from("<2f", buf, off); off += 8
        flags = buf[off]; off += 1
        nl = struct.unpack_from("<H", buf, off)[0]; off += 2
        e = np.frombuffer(buf, ENTDT, nl, off); off += nl * 10
        gids.append(gid + gid_offset)
        outs.append(o); rvs.append(rv); flgs.append(flags)
        ei.append(e["i"].astype(np.int64)); eq.append(e["q"].astype(np.float32)); en.append(e["n"].astype(np.float32))
    return (np.stack(feats), np.asarray(outs, np.float32), np.asarray(rvs, np.float32),
            np.asarray(flgs, np.uint8), np.asarray(gids, np.int64), ei, eq, en)


def load(glob_pat):
    files = []
    for pat in glob_pat.split(","):  # comma-separated globs -> replay buffer over several iters
        files += glob.glob(pat)
    files = sorted(set(files))
    if not files:
        sys.exit(f"no .bin match {glob_pat}")
    F_, O_, R_, FL, G_, EI, EQ, EN = [], [], [], [], [], [], [], []
    for k, p in enumerate(files):
        f, o, rv, fl, g, ei, eq, en = parse_bin(p, k * 10_000_000)
        F_.append(f); O_.append(o); R_.append(rv); FL.append(fl); G_.append(g)
        EI += ei; EQ += eq; EN += en
        print(f"  {os.path.basename(p)}: {len(o):,} rows", flush=True)
    feats = np.concatenate(F_); out = np.concatenate(O_); rootval = np.concatenate(R_)
    flags = np.concatenate(FL); gid = np.concatenate(G_)
    maxleg = max(len(x) for x in EI)
    n = len(out)
    idx_pad = np.full((n, maxleg), -1, np.int64)
    q_pad = np.zeros((n, maxleg), np.float32)
    n_pad = np.zeros((n, maxleg), np.float32)
    for r in range(n):
        m = len(EI[r])
        idx_pad[r, :m] = EI[r]; q_pad[r, :m] = EQ[r]; n_pad[r, :m] = EN[r]
    return feats, out, rootval, flags, gid, idx_pad, q_pad, n_pad, maxleg


def build_targets(idx_b, q_b, n_b, dev, kind, temp):
    """Padded raw entries -> dense policy target[bs,320] + legal mask[bs,320].
    qsoftmax: softmax((q - max_q)/temp) over VISITED entries; rows with no visited entry -> uniform
    over legal (matches the harvest's build_target). visits: n/Σn; Σn==0 -> uniform over legal."""
    valid = idx_b >= 0
    safe = idx_b.clamp(min=0)
    if kind == "qsoftmax":
        visited = valid & (n_b > 0)
        neg = torch.finfo(q_b.dtype).min
        qm = torch.where(visited, q_b, torch.full_like(q_b, neg))
        mx = qm.max(dim=1, keepdim=True).values
        has = visited.any(dim=1, keepdim=True)
        e = torch.where(visited, torch.exp((q_b - mx) / temp), torch.zeros_like(q_b))
        s = e.sum(dim=1, keepdim=True)
        uni = valid.float() / valid.float().sum(dim=1, keepdim=True).clamp(min=1.0)
        probs = torch.where(has & (s > 0), e / s.clamp(min=1e-30), uni)
    else:  # visits
        nn_ = torch.where(valid, n_b, torch.zeros_like(n_b))
        s = nn_.sum(dim=1, keepdim=True)
        uni = valid.float() / valid.float().sum(dim=1, keepdim=True).clamp(min=1.0)
        probs = torch.where(s > 0, nn_ / s.clamp(min=1e-30), uni)
    bs = idx_b.shape[0]
    target = torch.zeros(bs, N_ACTIONS, device=dev).scatter_add_(1, safe, probs)
    legal = torch.zeros(bs, N_ACTIONS, device=dev).scatter_add_(1, safe, valid.float())
    return target, (legal > 0.5)


def policy_ce_rows(logits, target, legal):
    """Per-row masked soft-target cross-entropy (so policy_valid weighting can be applied)."""
    logp = torch.log_softmax(logits.masked_fill(~legal, -1e9), dim=1)
    return -(target * logp).sum(1)


def policy_top1_acc(logits, target, legal, w):
    pred = logits.masked_fill(~legal, -1e9).argmax(1)
    tgt = target.argmax(1)
    hit = ((pred == tgt).float() * w).sum()
    return hit.item(), w.sum().item()


def auc(scores, labels):
    order = np.argsort(scores); ranks = np.empty(len(scores)); ranks[order] = np.arange(1, len(scores) + 1)
    npos = int(labels.sum()); nneg = len(labels) - npos
    if npos == 0 or nneg == 0:
        return 0.5
    return (ranks[labels == 1].sum() - npos * (npos + 1) / 2) / (npos * nneg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="comma-separated globs of DUELAP02 .bin shards")
    ap.add_argument("--init", required=True, help="donor JSON (value net or PV net) to warm-start")
    ap.add_argument("--out", required=True)
    ap.add_argument("--freeze-trunk", dest="freeze", action="store_true", default=True,
                    help="train ONLY the policy head; value stays == donor (default, clean gate)")
    ap.add_argument("--no-freeze-trunk", dest="freeze", action="store_false",
                    help="co-train value+policy (the full AZ net)")
    ap.add_argument("--policy-target", choices=["qsoftmax", "visits"], default="qsoftmax")
    ap.add_argument("--target-temp", type=float, default=0.03, help="qsoftmax temperature")
    ap.add_argument("--rootval-blend", type=float, default=0.0,
                    help="value target = (1-b)*outcome + b*rootval (rootval_valid rows only) — VALUE-BOOTSTRAP")
    ap.add_argument("--value-w", type=float, default=1.0, help="value MSE weight when co-training")
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--bs", type=int, default=4096)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--weight-decay", type=float, default=1e-4)
    ap.add_argument("--val-frac", type=float, default=0.08)
    ap.add_argument("--val-data", default=None,
                    help="Hold out a FIXED external val set (comma-globs) instead of carving val_frac "
                         "out of --data. Required to compare runs trained on DIFFERENT data: the "
                         "default split is drawn from --data itself, so two data sizes get two "
                         "different val sets and their metrics are not comparable (the 2026-07-28 "
                         "data-scaling question). With this set, val_frac is ignored and every point "
                         "on a scaling curve is scored on the same held-out games.")
    ap.add_argument("--patience", type=int, default=12)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    torch.manual_seed(a.seed)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"device {dev}  freeze_trunk {a.freeze}  policy_target {a.policy_target}@{a.target_temp}", flush=True)

    feats, out, rootval, flags, gid, idx_pad, q_pad, n_pad, maxleg = load(a.data)
    n_train_rows = len(out)
    if a.val_data:
        # Fixed external holdout: concatenate it after the training rows and remember the boundary.
        # gid is offset so a val game can never collide with a train game id.
        vf, vo, vrv, vfl, vg, vip, vqp, vnp, vmax = load(a.val_data)
        if vf.shape[1] != feats.shape[1]:
            sys.exit(f"--val-data feature width {vf.shape[1]} != --data {feats.shape[1]}")
        pad = max(maxleg, vmax)
        def rpad(arr, want):  # right-pad the per-move arrays to a common width
            if arr.shape[1] == want:
                return arr
            z = np.zeros((arr.shape[0], want - arr.shape[1]), dtype=arr.dtype)
            return np.concatenate([arr, z], axis=1)
        idx_pad, q_pad, n_pad = (rpad(x, pad) for x in (idx_pad, q_pad, n_pad))
        vip, vqp, vnp = (rpad(x, pad) for x in (vip, vqp, vnp))
        feats = np.concatenate([feats, vf]); out = np.concatenate([out, vo])
        rootval = np.concatenate([rootval, vrv]); flags = np.concatenate([flags, vfl])
        gid = np.concatenate([gid, vg + gid.max() + 1])
        idx_pad = np.concatenate([idx_pad, vip]); q_pad = np.concatenate([q_pad, vqp])
        n_pad = np.concatenate([n_pad, vnp]); maxleg = pad
        print(f"FIXED holdout: {len(vo):,} val rows from --val-data (val_frac ignored)", flush=True)
    pol_valid = (flags & 1).astype(bool)
    rv_valid = (flags & 2).astype(bool)
    print(f"total {len(out):,} rows ({pol_valid.sum():,} policy-valid), {len(np.unique(gid)):,} games, maxleg {maxleg}", flush=True)

    tok = torch.tensor(feats[:, :TOK_LEN], device=dev).view(-1, TOK_N, TOK_F)
    msk = torch.tensor(feats[:, TOK_LEN:TOK_LEN + TOK_N], device=dev)
    stt = torch.tensor(feats[:, TOK_LEN + TOK_N:FEAT], device=dev)
    # VALUE-BOOTSTRAP target (bit1-gated: forced-move roots have no searched rootval -> pure outcome).
    yv = np.where(rv_valid, (1.0 - a.rootval_blend) * out + a.rootval_blend * rootval, out).astype(np.float32)
    y = torch.tensor(yv, device=dev)
    if a.rootval_blend > 0:
        print(f"value target = {1-a.rootval_blend:.2f}*outcome + {a.rootval_blend:.2f}*rootval ({rv_valid.sum():,} rootval-valid rows)", flush=True)
    wpol = torch.tensor(pol_valid.astype(np.float32), device=dev)
    idxp = torch.tensor(idx_pad, device=dev)
    qp = torch.tensor(q_pad, device=dev)
    np_t = torch.tensor(n_pad, device=dev)

    if a.val_data:
        # Everything past the training block is the fixed holdout.
        mask = np.zeros(len(gid), bool); mask[n_train_rows:] = True
        is_val = torch.tensor(mask, device=dev)
    else:
        uniq = np.unique(gid); rng = np.random.default_rng(0); rng.shuffle(uniq)
        val_games = set(uniq[: max(1, int(len(uniq) * a.val_frac))].tolist())  # >=1 val game (NaN guard)
        is_val = torch.tensor(np.fromiter((g in val_games for g in gid), bool, len(gid)), device=dev)
    idx_tr = torch.nonzero(~is_val).squeeze(1)
    idx_val = torch.nonzero(is_val).squeeze(1)
    # Freeze mode trains only the policy head -> policy-invalid rows carry no gradient; drop them.
    if a.freeze:
        keep = wpol[idx_tr] > 0.5
        idx_tr = idx_tr[keep]
    print(f"train {len(idx_tr):,}  val {len(idx_val):,}", flush=True)

    net = AttnNet().to(dev)
    with open(a.init) as f:
        had_policy = load_weights(net, json.load(f))
    print(f"warm-started from {a.init} (policy head {'loaded' if had_policy else 'fresh'})", flush=True)
    if a.freeze:
        for p in net.parameters():
            p.requires_grad = False
        for p in net.policy.parameters():
            p.requires_grad = True
    params = [p for p in net.parameters() if p.requires_grad]
    opt = torch.optim.Adam(params, lr=a.lr, weight_decay=a.weight_decay)
    mse = nn.MSELoss(reduction="none")

    def run_batch(b):
        target, legal = build_targets(idxp[b], qp[b], np_t[b], dev, a.policy_target, a.target_temp)
        v, logits = net.forward_pv(tok[b], msk[b], stt[b])
        w = wpol[b]
        ce = policy_ce_rows(logits, target, legal)
        pl = (ce * w).sum() / w.sum().clamp(min=1.0)
        vl = mse(v, y[b]).mean()
        loss = pl + (a.value_w * vl if not a.freeze else 0.0)
        return loss, pl, vl, v, logits, target, legal, w

    best_key, best_js, since = None, None, 0
    for ep in range(a.epochs):
        net.train()
        perm = idx_tr[torch.randperm(len(idx_tr), device=dev)]
        tot = 0.0
        for i in range(0, len(perm), a.bs):
            b = perm[i:i + a.bs]
            opt.zero_grad()
            loss, pl, vl, *_ = run_batch(b)
            loss.backward(); opt.step()
            tot += loss.item() * len(b)
        net.eval()
        with torch.no_grad():
            hits, wsum, ces, vls, vps = 0.0, 0.0, 0.0, 0.0, []
            for b in idx_val.split(8192):
                _, pl, vl, v, logits, target, legal, w = run_batch(b)
                h, ws = policy_top1_acc(logits, target, legal, w)
                hits += h; wsum += ws
                ces += pl.item() * max(ws, 1.0)
                vls += vl.item() * len(b)
                vps.append(v)
            vacc = hits / max(wsum, 1.0)
            vce = ces / max(wsum, 1.0)
            vmse = vls / len(idx_val)
            vp = torch.cat(vps).cpu().numpy()
            vauc = auc(vp, (y[idx_val].cpu().numpy() > 0).astype(int))
        # Selection: freeze -> policy top-1 (higher better); co-train -> combined loss (lower better).
        key = -vacc if a.freeze else (vce + a.value_w * vmse)
        tag = ""
        if best_key is None or key < best_key:
            best_key, since = key, 0
            best_js = net.export_pv()
            best_js.update({"val_top1": float(vacc), "val_ce": float(vce), "val_vmse": float(vmse),
                            "val_vauc": float(vauc), "epoch": ep, "freeze_trunk": a.freeze,
                            "policy_target": a.policy_target, "target_temp": a.target_temp,
                            "rootval_blend": a.rootval_blend})
            tag = "  <- best"
        else:
            since += 1
        print(f"ep{ep:02d}  loss {tot/max(len(idx_tr),1):.4f}  val_top1 {vacc:.4f}  val_ce {vce:.4f}  val_vmse {vmse:.4f}  val_vauc {vauc:.4f}{tag}", flush=True)
        if since >= a.patience:
            print(f"early stop ep{ep}", flush=True)
            break

    if best_js is None:  # NaN-val guard: always emit a net
        best_js = net.export_pv()
        best_js.update({"val_top1": 0.0, "epoch": a.epochs - 1, "freeze_trunk": a.freeze})
        print("WARNING: no valid val epoch -> saved final net", flush=True)
    with open(a.out, "w") as f:
        json.dump(best_js, f)
    print(f"saved {a.out}  (val_top1 {best_js.get('val_top1'):.4f}, val_vauc {best_js.get('val_vauc', 0.0):.4f}, freeze {a.freeze})", flush=True)


if __name__ == "__main__":
    main()
