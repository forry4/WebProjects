"""Train the CoC ATTENTION net on harvest_boot token-row CSVs (logenc=tok).

  python coc-core/tools/train_attn.py --data "C:/Users/Forrest/coc_run_attn/attn_boot.t*.csv" \
      --out C:/Users/Forrest/coc_run_attn/attn_distill.json --epochs 4

Row format (harvest_boot, no header): game_id, f0..f1023 (tokfeats flat layout),
label, margin, root_value, sparse policy. No input normalization (tokfeats is
bounded by construction). Value target = (1-BETA)*[(1-SHAPE_A)*(2y-1) +
SHAPE_A*tanh(margin/SCALE)] + BETA*root_value (SHAPE_A=0.3, BETA=0.3 — the
proven fresh-retrain blend). Policy CE normalized by policy-row count (PCR-safe;
identical to plain mean on dense data). GAME-split holdout (id % 11), early stop
on val AUC + top1. Exports attn json + .check via attn_net (the parity fixture
attn_export_check verifies before the json is trusted).
"""
import os
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_v, "1")

import argparse
import glob
import math
import random
import sys

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import attn_net  # noqa: E402
from attn_net import N_ACT, AttnNet, export_json, import_json, write_check  # noqa: E402

IN_DIM = 1024
AUX_DIM = 0  # set by --aux-dim; 0 parses the pre-aux CSV format
SHAPE_A = 0.3
BETA = 0.3
VAL_MOD = 11


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
    total = 0.0
    for tok in pol_str.split(" "):
        if not tok:
            continue
        a, n = tok.split(":")
        t[int(a)] = float(n)
        total += float(n)
    if total > 0:
        t /= total
    return t


try:  # multithreaded C parser (~50-100x the per-row python parse, which was
    # ~the entire training wall-clock — the net itself is tiny). Row order,
    # values, and the gid split are identical; python path kept as fallback.
    # OPT-IN (COC_ARROW=1): with arrow active in-process, the trainer's
    # loss.backward() hit CUBLAS_STATUS_EXECUTION_FAILED twice on this box
    # (2026-07-10; a clean arrow-then-backward mini-repro PASSES, so it's an
    # emergent interaction — suspect arrow readahead memory pressure vs the
    # CUDA context). Debug offline before making it the default.
    if os.environ.get("COC_ARROW") == "1":
        import pyarrow.csv as _pacsv
    else:
        _pacsv = None
except ImportError:
    _pacsv = None

_COLS = ["gid"] + [f"f{i}" for i in range(IN_DIM)] + ["label", "margin", "rootv", "pol"]


def _arrow_batches(path):
    import pyarrow as pa
    types = {"gid": pa.int64(), "label": pa.float64(), "margin": pa.float64(),
             "rootv": pa.float64(), "pol": pa.string()}
    for i in range(IN_DIM):
        types[f"f{i}"] = pa.float32()
    reader = _pacsv.open_csv(
        path,
        read_options=_pacsv.ReadOptions(column_names=_COLS, block_size=1 << 24),
        parse_options=_pacsv.ParseOptions(delimiter=","),
        convert_options=_pacsv.ConvertOptions(column_types=types),
    )
    for batch in reader:
        gids = batch.column(0).to_numpy()
        feats = np.column_stack(
            [batch.column(i).to_numpy(zero_copy_only=False) for i in range(1, 1 + IN_DIM)])
        lab = batch.column(1 + IN_DIM).to_numpy()
        mar = batch.column(2 + IN_DIM).to_numpy()
        rv = batch.column(3 + IN_DIM).to_numpy()
        pols = batch.column(4 + IN_DIM).to_pylist()
        yield gids, feats, lab, mar, rv, pols


def stream_rows(files, want_val):
    for path in files:
        if _pacsv is not None:
            # the arrow path's column map predates the aux columns
            assert AUX_DIM == 0, "COC_ARROW path does not support aux columns"
            for gids, feats, lab, mar, rv, pols in _arrow_batches(path):
                for i in range(len(gids)):
                    gid = int(gids[i])
                    if (gid % VAL_MOD == 0) != want_val:
                        continue
                    yield (gid, feats[i], float(lab[i]), float(mar[i]), float(rv[i]),
                           None, pols[i] or "")
        else:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    gid = int(line[:line.index(",")])
                    if (gid % VAL_MOD == 0) != want_val:
                        continue
                    yield parse_row(line)


def margin_scale(files, sample_every=16):
    """-> (margin std, total rows, aux_mu, aux_sd) — aux stats z-score the
    auxiliary targets (None when AUX_DIM==0)."""
    margins = []
    aux_rows = [] if AUX_DIM else None
    k = 0
    for path in files:
        if _pacsv is not None:
            assert AUX_DIM == 0, "COC_ARROW path does not support aux columns"
            for _, _, _, mar, _, _ in _arrow_batches(path):
                n = len(mar)
                # same sample set as the line loop: keep lines where the global
                # 1-based counter is a multiple of sample_every
                first = (-(k + 1)) % sample_every
                margins.extend(float(m) for m in mar[first::sample_every])
                k += n
        else:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    k += 1
                    if k % sample_every:
                        continue
                    row = parse_row(line)
                    margins.append(row[3])
                    if AUX_DIM:
                        aux_rows.append(row[5])
    if AUX_DIM:
        am = np.stack(aux_rows)
        aux_mu = am.mean(0).astype(np.float32)
        aux_sd = am.std(0).astype(np.float32)
        aux_sd[aux_sd < 1e-6] = 1.0
    else:
        aux_mu = aux_sd = None
    return float(np.std(margins)) or 12.0, k, aux_mu, aux_sd


def batches(files, scale, batch, aux_mu=None, aux_sd=None, block=16384, seed=0):
    rng = random.Random(seed)
    buf = []

    def flush():
        rng.shuffle(buf)
        for i in range(0, len(buf) - batch + 1, batch):
            chunk = buf[i:i + batch]
            x = np.stack([c[0] for c in chunk])
            y = np.array([c[1] for c in chunk], dtype=np.float32)
            p = np.stack([c[2] for c in chunk])
            a = torch.from_numpy(np.stack([c[3] for c in chunk])) if AUX_DIM else None
            yield (torch.from_numpy(x), torch.from_numpy(y), torch.from_numpy(p), a)
        buf.clear()

    for gid, feats, label, margin, rootv, aux, pol in stream_rows(files, False):
        shaped = (1 - SHAPE_A) * (2 * label - 1) + SHAPE_A * math.tanh(margin / scale)
        target = (1 - BETA) * shaped + BETA * rootv
        a_norm = ((aux - aux_mu) / aux_sd).astype(np.float32) if AUX_DIM else None
        buf.append((feats, np.float32(target), policy_target(pol), a_norm))
        if len(buf) >= block:
            yield from flush()
    yield from flush()


def evaluate(net, dev, files, batch):
    net.eval()
    labels, top1, n, n_pol = [], 0, 0, 0
    vs = []
    with torch.no_grad():
        for gid, feats, label, margin, rootv, aux, pol in stream_rows(files, True):
            vs.append((feats, label, policy_target(pol)))
            if len(vs) >= batch:
                x = torch.from_numpy(np.stack([v[0] for v in vs])).to(dev)
                val, logits = net.forward_flat(x)
                pt = np.stack([v[2] for v in vs])
                haspol = pt.sum(1) > 0
                top1 += int(((logits.argmax(1).cpu().numpy() == pt.argmax(1)) & haspol).sum())
                n_pol += int(haspol.sum())
                labels.extend([(float(v_), l_) for v_, l_ in
                               zip(val.cpu().numpy(), [v[1] for v in vs])])
                n += len(vs)
                vs = []
    if not labels:
        return 0.5, 0.0, 0
    preds = np.array([p for p, _ in labels])
    ls = np.array([l for _, l in labels])
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
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--epochs", type=int, default=4)
    ap.add_argument("--batch", type=int, default=1024)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--warm", default=None, help="warm-start from an exported attn json")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--aux-dim", type=int, default=0,
                    help="aux score-decomposition head width (14 for the 2026-07 "
                         "harvest columns; 0 parses the pre-aux CSV format). "
                         "Trunk-shared, EXCLUDED from export — json stays shape-identical")
    ap.add_argument("--aux-weight", type=float, default=0.3)
    ap.add_argument("--snap-prefix", default=None,
                    help="also export after EVERY epoch to <prefix>ep<k>.json "
                         "(+.check). The netval leaf consumes value-head "
                         "CALIBRATION that val AUC/top1 are blind to; gating "
                         "the epoch trajectory is the only way to see it settle")
    args = ap.parse_args()
    global AUX_DIM
    AUX_DIM = args.aux_dim

    files = sorted(set(sum((glob.glob(g) for g in args.data.split(";")), [])))
    assert files, f"no files match {args.data}"
    torch.manual_seed(args.seed)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"device={dev}, files={len(files)}, aux_dim={AUX_DIM}")

    scale, total_rows, aux_mu, aux_sd = margin_scale(files)
    print(f"rows~{total_rows}, margin-scale={scale:.2f}")

    net = import_json(args.warm, aux_dim=AUX_DIM) if args.warm else AttnNet(aux_dim=AUX_DIM)
    if args.warm:
        print(f"warm-start from {args.warm}")
    net.to(dev)
    opt = torch.optim.Adam(net.parameters(), lr=args.lr)

    best = -1.0
    for ep in range(args.epochs):
        net.train()
        steps, vloss_s, closs_s, aloss_s = 0, 0.0, 0.0, 0.0
        for x, y, p, a in batches(files, scale, args.batch, aux_mu=aux_mu,
                                  aux_sd=aux_sd, seed=args.seed * 100 + ep):
            x, y, p = x.to(dev), y.to(dev), p.to(dev)
            if AUX_DIM:
                val, logits, aux_pred = net.forward_with_aux_flat(x)
            else:
                val, logits = net.forward_flat(x)
            vloss = torch.mean((val - y) ** 2)
            ce_rows = -(p * torch.log_softmax(logits, 1)).sum(1)
            n_pol = (p.sum(1) > 0).sum().clamp(min=1)
            closs = ce_rows.sum() / n_pol
            loss = vloss + closs
            if AUX_DIM:
                a = a.to(dev)
                aloss = torch.mean((aux_pred - a) ** 2)
                loss = loss + args.aux_weight * aloss
                aloss_s += float(aloss.detach())
            opt.zero_grad()
            loss.backward()
            opt.step()
            vloss_s += float(vloss.detach())
            closs_s += float(closs.detach())
            steps += 1
        auc, top1, nval = evaluate(net, dev, files, args.batch)
        score = auc + top1
        aux_str = f" aloss {aloss_s / max(steps,1):.4f}" if AUX_DIM else ""
        print(f"epoch {ep}: vloss {vloss_s / max(steps,1):.4f} closs "
              f"{closs_s / max(steps,1):.4f}{aux_str} | val AUC {auc:.4f} top1 {top1:.4f} "
              f"(n={nval}) {'*BEST*' if score > best else ''}", flush=True)
        if score > best or args.snap_prefix:
            net_cpu = net.cpu().eval()
            if score > best:
                best = score
                # atomic export: write tmp then rename, so a reader (or a second
                # writer — the 2026-07-10 triple-loop race) never sees a torn file
                export_json(net_cpu, args.out + ".tmp")
                os.replace(args.out + ".tmp", args.out)
                write_check(net_cpu, args.out + ".check.tmp")
                os.replace(args.out + ".check.tmp", args.out + ".check")
            if args.snap_prefix:
                snap = f"{args.snap_prefix}ep{ep}.json"
                export_json(net_cpu, snap + ".tmp")
                os.replace(snap + ".tmp", snap)
                write_check(net_cpu, snap + ".check.tmp")
                os.replace(snap + ".check.tmp", snap + ".check")
            net.to(dev)
    print(f"done; best val score {best:.4f} -> {args.out}")


if __name__ == "__main__":
    main()
