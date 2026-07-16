"""Would the trained policy make a useful PUCT prior? — a cheap read before wiring it.

Top-1 (0.34) understates a prior's value: a prior helps if it CONCENTRATES probability on
the few good moves so PUCT explores them first, even without nailing #1. So measure, over
held-out rows:
  * top-K coverage: is the search's greedy pick (the target argmax) in the net's top-K
    legal moves? (K=1,3,5)
  * prior mass on the pick: how much softmax prob the net puts on the target's top move
    (vs uniform 1/n_legal) — the concentration a PUCT prior would actually apply.
If top-3/top-5 coverage is high (~0.7+), a prior is worth wiring; if it tracks top-1, it
isn't.

    python duel-core/tools/eval_pv_coverage.py --net duel-core/src/pv_net.json \
        --data "C:/Users/Forrest/duel_run/pv/pv_9.bin"
"""
import argparse
import glob
import json
import sys

import numpy as np
import torch
import torch.nn.functional as F

sys.path.insert(0, __file__.rsplit("/", 1)[0] if "/" in __file__ else ".")
from train_pv import read_shard, PVNet  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--net", default="duel-core/src/pv_net.json")
    ap.add_argument("--data", required=True, help="glob of PV shards (use held-out ones)")
    args = ap.parse_args()
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    blob = json.load(open(args.net))
    net = PVNet(blob["n_feats"], blob["n_act"], blob["hidden"], 0.0).to(dev)
    sd = {}
    sd["trunk.0.weight"] = torch.tensor(blob["trunk"][0]["w"]); sd["trunk.0.bias"] = torch.tensor(blob["trunk"][0]["b"])
    sd["trunk.3.weight"] = torch.tensor(blob["trunk"][1]["w"]); sd["trunk.3.bias"] = torch.tensor(blob["trunk"][1]["b"])
    sd["value.weight"] = torch.tensor(blob["value"]["w"]); sd["value.bias"] = torch.tensor(blob["value"]["b"])
    sd["policy.weight"] = torch.tensor(blob["policy"]["w"]); sd["policy.bias"] = torch.tensor(blob["policy"]["b"])
    net.load_state_dict(sd); net.eval()
    mu = torch.tensor(blob["mu"], device=dev); sd_ = torch.tensor(blob["sd"], device=dev)

    files = sorted(glob.glob(args.data))
    X, V, P, M, G, n_act = [], None, [], [], None, None
    Xs, Ps, Ms = [], [], []
    for k, f in enumerate(files):
        x, v, p, m, g, na = read_shard(f, dev, k * 10_000_000)
        Xs.append(x); Ps.append(p); Ms.append(m)
    X = torch.cat(Xs); P = torch.cat(Ps); M = torch.cat(Ms)
    # only multi-move rows (a forced move is trivially top-1)
    nlegal = M.sum(1)
    keep = nlegal >= 2
    X, P, M, nlegal = X[keep], P[keep], M[keep], nlegal[keep]
    print(f"eval rows (>=2 legal): {len(X):,}  mean n_legal {nlegal.float().mean():.1f}")

    NEG = torch.finfo(torch.float32).min
    with torch.no_grad():
        z = (X - mu) / sd_
        _, logits = net(z)
        logits = logits.masked_fill(~M, NEG)
        probs = F.softmax(logits, dim=1)
        tgt_pick = P.argmax(1)                              # the search's greedy pick
        # rank of the pick under the net (0 = net's top)
        order = torch.argsort(logits, dim=1, descending=True)
        pick_rank = (order == tgt_pick.unsqueeze(1)).float().argmax(1)
        for K in (1, 3, 5):
            cov = (pick_rank < K).float().mean().item()
            print(f"  top-{K} coverage (pick in net's top-{K}): {cov:.3f}")
        # concentration: net prob on the pick vs uniform 1/n_legal
        pmass = probs.gather(1, tgt_pick.unsqueeze(1)).squeeze(1)
        unif = 1.0 / nlegal.float()
        print(f"  net prob on the pick: mean {pmass.mean():.3f}  (uniform would be {unif.mean():.3f})")
        print(f"  concentration ratio (pick-prob / uniform): {(pmass/unif).mean():.2f}x")
        # how peaked is the net overall (entropy vs uniform)
        ent = -(probs.clamp_min(1e-9).log() * probs).sum(1)
        print(f"  net policy entropy {ent.mean():.2f} nats  vs uniform {nlegal.float().log().mean():.2f}")


if __name__ == "__main__":
    main()
