"""GPU inference sidecar for the CoC harvest tooling (torch, cu128 python).

Serves the SAME exported pv json the Rust CPU path loads, over localhost TCP,
so the net forward runs on the RTX instead of the CPU (the CPU forward is ~80%
of netval per-sim cost). One model per server run — the loop scripts restart it
per iteration when pv_best changes.

  python coc-core/tools/gpu_server.py <model.json> [--port 9911] [--device cuda]

Protocol (little-endian, one connection per Rust worker thread):
  handshake: server sends u32 in_dim on accept
  request:   u32 n_rows, then n_rows * in_dim f32 RAW features (unnormalized)
  response:  n_rows * (1 + N_ACT) f32 — value then all policy logits per row
Normalization ((x - mu) / sd) happens HERE, mirroring the Rust forward_raw.
NOT bit-identical to the CPU forward (torch GPU arithmetic) — harvest/screening
tier only (like int8), never ship gates.
"""
import os
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_v, "1")

import argparse
import socket
import struct
import sys
import threading

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pv_net import N_ACT, load_json  # noqa: E402


def recv_exact(conn, n):
    buf = bytearray(n)
    view = memoryview(buf)
    got = 0
    while got < n:
        k = conn.recv_into(view[got:], n - got)
        if k == 0:
            return None
        got += k
    return buf


STATS = {"evals": 0, "reqs": 0, "t0": None}
STATS_LOCK = threading.Lock()


def bump_stats(n):
    import time
    with STATS_LOCK:
        if STATS["t0"] is None:
            STATS["t0"] = time.time()
        STATS["evals"] += n
        STATS["reqs"] += 1
        dt = time.time() - STATS["t0"]
        if dt >= 10.0:
            print(f"[stats] {STATS['evals'] / dt:.0f} evals/s, "
                  f"{STATS['reqs'] / dt:.0f} reqs/s, "
                  f"{STATS['evals'] / max(STATS['reqs'], 1):.0f} rows/req", flush=True)
            STATS["evals"] = STATS["reqs"] = 0
            STATS["t0"] = time.time()


class GraphRunner:
    """Serve a small forward through one captured CUDA graph: kernel-launch
    overhead (the whole cost at these tensor sizes) collapses to a single graph
    replay. Fixed padded batch; rows are copied into a static input buffer and
    sliced out of static outputs. Replays run the exact captured kernels, so
    outputs match eager bit-for-bit. Thread-safe via a lock (the static buffers
    are shared across client threads)."""

    PAD = 256

    def __init__(self, net, in_dim, mask0, dev):
        for p in net.parameters():
            p.requires_grad_(False)
        self.lock = threading.Lock()
        self.mask0 = mask0
        with torch.inference_mode():
            self.inp = torch.zeros(self.PAD, in_dim, device=dev)
            # keep every (pad) row's token 0 live — an all-masked row would hit
            # SDPA's all-(-inf) softmax (NaN); sliced away anyway, but keep the
            # graph NaN-free on principle
            self.inp[:, mask0] = 1.0
            s = torch.cuda.Stream()
            s.wait_stream(torch.cuda.current_stream())
            with torch.cuda.stream(s):
                for _ in range(3):
                    net.forward_flat(self.inp)
            torch.cuda.current_stream().wait_stream(s)
            self.graph = torch.cuda.CUDAGraph()
            with torch.cuda.graph(self.graph):
                v, p = net.forward_flat(self.inp)
                self.val, self.pol = v, p

    def run(self, x):
        n = x.shape[0]
        vs, ps = [], []
        with self.lock:
            for i in range(0, n, self.PAD):
                chunk = x[i:i + self.PAD]
                m = chunk.shape[0]
                self.inp[:m].copy_(chunk)
                if m < self.PAD:
                    self.inp[m:].zero_()
                    self.inp[m:, self.mask0] = 1.0
                self.graph.replay()
                vs.append(self.val[:m].clone())
                ps.append(self.pol[:m].clone())
        if len(vs) == 1:
            return vs[0], ps[0]
        return torch.cat(vs), torch.cat(ps)


def handle(conn, forward, in_dim, dev):
    try:
        handle_inner(conn, forward, in_dim, dev)
    except (ConnectionError, OSError):
        pass  # client gone (normal teardown) — never noise, never a crash


def handle_inner(conn, forward, in_dim, dev):
    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    conn.sendall(struct.pack("<I", in_dim))
    row_bytes = in_dim * 4
    with torch.inference_mode():
        while True:
            hdr = recv_exact(conn, 4)
            if hdr is None:
                return
            n = struct.unpack("<I", hdr)[0]
            if n == 0:
                return
            raw = recv_exact(conn, n * row_bytes)
            if raw is None:
                return
            # zero-copy view of the recv buffer (normalization is folded into
            # trunk[0] at load, so raw features go straight in)
            x = torch.frombuffer(raw, dtype=torch.float32).view(n, in_dim).to(
                dev, non_blocking=True)
            val, logits = forward(x)
            out = torch.cat([val.reshape(n, 1), logits], dim=1).cpu().numpy()
            conn.sendall(out.astype(np.float32, copy=False).tobytes())
            bump_stats(n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("--port", type=int, default=9911)
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = ap.parse_args()

    dev = args.device
    with open(args.model, encoding="utf-8") as f:
        head = f.read(4096)
    if '"emb_w"' in head:
        # ATTENTION net (attn_net twin): forward_flat takes the tokfeats flat
        # row directly — no normalization anywhere by design. The forward is
        # LAUNCH-BOUND at these tensor sizes (~40 kernels per call), so serve it
        # through a captured CUDA GRAPH at a fixed padded batch: copy rows into a
        # static buffer, one replay, slice the static output. Same kernels as
        # eager (bit-identical outputs); the harvest's startup parity guard
        # re-verifies vs the Rust forward on every launch regardless.
        import attn_net
        net = attn_net.import_json(args.model).to(dev).eval()
        in_dim = attn_net.TOK_N * attn_net.TOK_F + attn_net.TOK_N + attn_net.TOK_STATE
        mask0 = attn_net.TOK_N * attn_net.TOK_F  # tokfeats mask-block offset
        use_graph = dev.startswith("cuda") and os.environ.get("COC_GPU_GRAPH", "1") != "0"
        if use_graph:
            try:
                forward = GraphRunner(net, in_dim, mask0, dev).run
                print("[graph] CUDA-graph forward armed (pad %d)" % GraphRunner.PAD, flush=True)
            except Exception as e:  # capture unsupported -> eager fallback
                print(f"[graph] capture failed ({e}); eager fallback", flush=True)
                forward = net.forward_flat
        else:
            forward = net.forward_flat
    else:
        net, mu, sd = load_json(args.model)
        in_dim = len(mu)
        net.to(dev).eval()
        # Fold the z-score into trunk[0] so requests skip the normalize kernels:
        #   relu(W(x-mu)/sd + b) = relu(W' x + b') with W' = W*inv_sd (col-wise),
        #   b' = b - W' @ mu. Pure algebra; the harvest's startup parity guard
        #   (CPU forward vs server) verifies it end-to-end on every run.
        mu_t = torch.tensor(mu, dtype=torch.float32, device=dev)
        inv_sd = 1.0 / torch.tensor(sd, dtype=torch.float32, device=dev)
        with torch.no_grad():
            l0 = net.trunk[0]
            l0.weight.mul_(inv_sd)
            l0.bias.sub_(l0.weight @ mu_t)
        forward = net
    # warm the kernels so the first real request isn't slow
    with torch.inference_mode():
        forward(torch.zeros(8, in_dim, device=dev))

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", args.port))
    srv.listen(32)
    print(f"gpu_server ready: {args.model} in_dim={in_dim} n_act={N_ACT} "
          f"dev={dev} port={args.port}", flush=True)
    while True:
        conn, _ = srv.accept()
        threading.Thread(
            target=handle, args=(conn, forward, in_dim, dev), daemon=True
        ).start()


if __name__ == "__main__":
    main()
