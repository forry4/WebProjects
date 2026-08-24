"""Train the CoC PolicyValueNet on harvest_boot CSVs (streaming, low-RAM).

Usage (run with the cu128 torch python; outputs land wherever --out points):
  python coc-core/tools/train_pv.py --data "C:/Users/Forrest/coc_run/boot.t*.csv" \
      --out C:/Users/Forrest/coc_run/pv_boot.json --epochs 4

Columns (harvest_boot, no header):
  0 game_id, 1..934 feats, 935 label, 936 margin, 937 root_value,
  [938..952 aux x14, only if --aux-dim is set — a harvest_boot build predating
  the aux columns writes the old 939-field format; --aux-dim 0 (default)
  parses that], last: sparse policy
Value target: (1-BETA)*[(1-SHAPE_A)*(2*label-1) + SHAPE_A*tanh(margin/SCALE)]
              + BETA*root_value       (SHAPE_A=0.3, BETA=0.3; SCALE = harvest
              margin std, computed in the stats pass)
Policy target: normalized sparse visit distribution; loss = MSE + CE.
Aux target (--aux-dim>0, KataGo-style score-decomposition head; see pv_net.PVNet
  — trunk-shared, EXCLUDED from export_json, so the exported net is shape-
  identical to one trained without it): per-column z-scored (stats pass),
  MSE averaged over columns, weighted by --aux-weight into the total loss.
Holdout: GAME-split (game_id % 11 == 0 -> val). Early stop on val AUC + top1.
Exports pv_net JSON + a check file (8 val rows + f32 outputs) for net_export_check.
"""
# BLAS pins BEFORE numpy/torch (box lesson: workers thrash without this).
import os
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_v, "1")

import argparse
import glob
import json
import math
import random
import sys

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pv_net  # noqa: E402
from pv_net import N_ACT, PVNet, export_json, load_json  # noqa: E402

IN_DIM = pv_net.IN_DIM  # reset by --in-dim before any parsing
AUX_DIM = 0  # reset by --aux-dim; 0 = old CSV format (no aux columns)

SHAPE_A = 0.3
BETA = 0.3
VAL_MOD = 11  # game_id % VAL_MOD == 0 -> validation


def parse_row(line):
    parts = line.rstrip("\n").split(",")
    gid = int(parts[0])
    feats = np.array(parts[1:1 + IN_DIM], dtype=np.float32)
    label = float(parts[1 + IN_DIM])
    margin = float(parts[2 + IN_DIM])
    rootv = float(parts[3 + IN_DIM])
    off = 4 + IN_DIM
    if AUX_DIM:
        aux = np.array(parts[off:off + AUX_DIM], dtype=np.float32)
        pol = parts[off + AUX_DIM]
    else:
        aux = None
        pol = parts[off]
    return gid, feats, label, margin, rootv, aux, pol


def policy_target(pol_str):
    t = np.zeros(N_ACT, dtype=np.float32)
    total = 0
    for tok in pol_str.split(" "):
        if not tok:
            continue
        a, n = tok.split(":")
        t[int(a)] = float(n)
        total += float(n)
    if total > 0:
        t /= total
    return t


def stream_rows(files, want_val):
    for path in files:
        with open(path, encoding="utf-8") as f:
            for line in f:
                gid = int(line[:line.index(",")])
                if (gid % VAL_MOD == 0) != want_val:
                    continue
                yield parse_row(line)


def stats_pass(files, sample_every=8):
    n = 0
    mu = np.zeros(IN_DIM, dtype=np.float64)
    m2 = np.zeros(IN_DIM, dtype=np.float64)
    margins = []
    aux_rows = [] if AUX_DIM else None
    k = 0
    for path in files:
        with open(path, encoding="utf-8") as f:
            for line in f:
                k += 1
                if k % sample_every:
                    continue
                _, feats, _, margin, _, aux, _ = parse_row(line)
                n += 1
                d = feats - mu
                mu += d / n
                m2 += d * (feats - mu)
                margins.append(margin)
                if AUX_DIM:
                    aux_rows.append(aux)
    sd = np.sqrt(m2 / max(n - 1, 1))
    sd[sd < 1e-6] = 1.0
    scale = float(np.std(margins)) or 12.0
    if AUX_DIM:
        am = np.stack(aux_rows)
        aux_mu = am.mean(0).astype(np.float32)
        aux_sd = am.std(0).astype(np.float32)
        aux_sd[aux_sd < 1e-6] = 1.0
    else:
        aux_mu = aux_sd = None
    return mu.astype(np.float32), sd.astype(np.float32), scale, k, aux_mu, aux_sd


def batches(files, want_val, mu, sd, scale, batch, aux_mu=None, aux_sd=None,
            block=32768, shuffle=True, seed=0):
    rng = random.Random(seed)
    buf = []

    def flush():
        if shuffle:
            rng.shuffle(buf)
        for i in range(0, len(buf) - batch + 1, batch):
            chunk = buf[i:i + batch]
            x = np.stack([c[0] for c in chunk])
            x = (x - mu) / sd
            y = np.array([c[1] for c in chunk], dtype=np.float32)
            p = np.stack([c[2] for c in chunk])
            if AUX_DIM:
                a = np.stack([c[3] for c in chunk])
                yield (torch.from_numpy(x), torch.from_numpy(y), torch.from_numpy(p),
                       torch.from_numpy(a))
            else:
                yield (torch.from_numpy(x), torch.from_numpy(y), torch.from_numpy(p), None)
        buf.clear()

    for gid, feats, label, margin, rootv, aux, pol in stream_rows(files, want_val):
        shaped = (1 - SHAPE_A) * (2 * label - 1) + SHAPE_A * math.tanh(margin / scale)
        target = (1 - BETA) * shaped + BETA * rootv
        if AUX_DIM:
            a_norm = ((aux - aux_mu) / aux_sd).astype(np.float32)
            buf.append((feats, np.float32(target), policy_target(pol), a_norm))
        else:
            buf.append((feats, np.float32(target), policy_target(pol), None))
        if len(buf) >= block:
            yield from flush()
    yield from flush()


def evaluate(net, dev, files, mu, sd, scale, batch):
    net.eval()
    vs, labels, top1, n, n_pol = [], [], 0, 0, 0
    with torch.no_grad():
        for gid, feats, label, margin, rootv, aux, pol in stream_rows(files, True):
            vs.append((feats, label, policy_target(pol)))
            if len(vs) >= batch:
                x = np.stack([v[0] for v in vs])
                x = torch.from_numpy((x - mu) / sd).to(dev)
                val, logits = net(x)
                pt = np.stack([v[2] for v in vs])
                haspol = pt.sum(1) > 0  # PCR value-only rows carry no policy
                top1 += int(((logits.argmax(1).cpu().numpy() == pt.argmax(1)) & haspol).sum())
                labels.extend([(float(v_), l_) for v_, l_ in
                               zip(val.cpu().numpy(), [v[1] for v in vs])])
                n += len(vs)
                n_pol += int(haspol.sum())
                vs = []
    if not labels:
        return 0.5, 0.0, 0
    preds = np.array([p for p, _ in labels])
    ls = np.array([l for _, l in labels])
    # AUC via rank statistic
    order = np.argsort(preds)
    ranks = np.empty_like(order, dtype=np.float64)
    ranks[order] = np.arange(1, len(preds) + 1)
    pos = ls == 1
    npos, nneg = int(pos.sum()), int((~pos).sum())
    auc = 0.5 if not npos or not nneg else (
        (ranks[pos].sum() - npos * (npos + 1) / 2) / (npos * nneg))
    return float(auc), top1 / max(n_pol, 1), n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="glob of harvest csvs")
    ap.add_argument("--out", required=True)
    ap.add_argument("--epochs", type=int, default=4)
    ap.add_argument("--batch", type=int, default=4096)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--warm", default=None, help="warm-start from an exported json")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--in-dim", type=int, default=pv_net.IN_DIM,
                    help="feature count in the harvest rows (934=v1, 1078=v2)")
    ap.add_argument("--trunk", default=None,
                    help="hidden layer sizes, comma-separated (default 512,256; "
                         "the Rust loader is shape-generic — dims come from the json)")
    ap.add_argument("--aux-dim", type=int, default=0,
                    help="KataGo-style aux score-decomposition head width (0=off; "
                         "harvest_boot's terminal-score columns give 14). Trunk-shared, "
                         "EXCLUDED from export — gradient shaping only, zero Rust-side change")
    ap.add_argument("--aux-weight", type=float, default=0.3,
                    help="weight on the (per-column z-scored, mean-reduced) aux MSE")
    args = ap.parse_args()
    global IN_DIM, AUX_DIM
    IN_DIM = args.in_dim
    AUX_DIM = args.aux_dim

    files = sorted(set(sum((glob.glob(g) for g in args.data.split(";")), [])))
    assert files, f"no files match {args.data}"
    torch.manual_seed(args.seed)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"device={dev}, files={len(files)}, aux_dim={AUX_DIM}")

    print("stats pass...", flush=True)
    mu, sd, scale, total_rows, aux_mu, aux_sd = stats_pass(files)
    print(f"rows~{total_rows}, margin-scale={scale:.2f}")
    aux_mu_t = torch.from_numpy(aux_mu).to(dev) if AUX_DIM else None
    aux_sd_t = torch.from_numpy(aux_sd).to(dev) if AUX_DIM else None

    if args.warm:
        net, wmu, wsd = load_json(args.warm, aux_dim=AUX_DIM)
        mu, sd = np.array(wmu, dtype=np.float32), np.array(wsd, dtype=np.float32)
        print(f"warm-start from {args.warm}")
    elif args.trunk:
        trunk = tuple(int(d) for d in args.trunk.split(","))
        net = PVNet(in_dim=args.in_dim, trunk=trunk, aux_dim=AUX_DIM)
        print(f"fresh net, trunk={trunk}")
    else:
        net = PVNet(in_dim=args.in_dim, aux_dim=AUX_DIM)
    net.to(dev)
    opt = torch.optim.Adam(net.parameters(), lr=args.lr)

    best = -1.0
    for ep in range(args.epochs):
        net.train()
        steps, vloss_s, closs_s, aloss_s = 0, 0.0, 0.0, 0.0
        for x, y, p, a in batches(files, False, mu, sd, scale, args.batch,
                                  aux_mu=aux_mu, aux_sd=aux_sd,
                                  seed=args.seed * 100 + ep):
            x, y, p = x.to(dev), y.to(dev), p.to(dev)
            val, logits = net(x)
            vloss = torch.mean((val - y) ** 2)
            # normalize CE by rows that HAVE a policy target (PCR value-only
            # rows are all-zero targets -> zero CE, and must not dilute scale)
            ce_rows = -(p * torch.log_softmax(logits, 1)).sum(1)
            n_pol = (p.sum(1) > 0).sum().clamp(min=1)
            closs = ce_rows.sum() / n_pol
            loss = vloss + closs
            if AUX_DIM:
                a = a.to(dev)
                aux_pred = net.forward_aux(x)
                aloss = torch.mean((aux_pred - a) ** 2)
                loss = loss + args.aux_weight * aloss
                aloss_s += float(aloss)
            opt.zero_grad()
            loss.backward()
            opt.step()
            vloss_s += float(vloss)
            closs_s += float(closs)
            steps += 1
        auc, top1, nval = evaluate(net, dev, files, mu, sd, scale, args.batch)
        score = auc + top1
        aux_str = f" aloss {aloss_s / max(steps,1):.4f}" if AUX_DIM else ""
        print(f"epoch {ep}: vloss {vloss_s / max(steps,1):.4f} closs "
              f"{closs_s / max(steps,1):.4f}{aux_str} | val AUC {auc:.4f} top1 {top1:.4f} "
              f"(n={nval}) {'*BEST*' if score > best else ''}", flush=True)
        if score > best:
            best = score
            export_json(net.cpu(), mu, sd, args.out)
            net.to(dev)
            # check vectors for net_export_check (f32 CPU forward)
            net_cpu, cmu, csd = load_json(args.out)
            rng = np.random.default_rng(7)
            xs = rng.standard_normal((8, IN_DIM)).astype(np.float32) * 0.5
            with torch.no_grad():
                xin = torch.from_numpy((xs - np.array(cmu, dtype=np.float32))
                                       / np.array(csd, dtype=np.float32))
                cv, cl = net_cpu(xin)
            with open(args.out + ".check", "w", encoding="utf-8") as f:
                json.dump({
                    "inputs": xs.tolist(),
                    "values": [float(v) for v in cv.numpy()],
                    "logits8": [[float(x) for x in row[:8]] for row in cl.numpy()],
                }, f)
    print(f"done; best val score {best:.4f} -> {args.out}")


if __name__ == "__main__":
    main()
