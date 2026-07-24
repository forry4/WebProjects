"""PyTorch twin of coc-core's attention net (src/attn.rs). PARITY-LOCKED:
attn_export_check.exe verifies torch and Rust agree <=1e-3 on stored check
vectors before any trained json is trusted.

Shape (the P4b throughput-gate winner): 32 tokens x 28 feats -> embed D=48 ->
2 x [4-head MHA (key-masked) + FFN96] (residual + LayerNorm WITHOUT affine) ->
masked mean-pool + state-embed(96) -> trunk 128 -> value(tanh) + policy:
80 GLOBAL logits scattered to their action ids + token-TIED logits (tokens
0..19: 12 depot->TAKE_HEX, 4 black->BUY_BLACK, 3 my-storage->DISCARD +
PLACE_SLOT). Masked/tied-absent logits are -1e9. NO input normalization —
tokfeats features are bounded by construction (no mu/sd anywhere).

  python attn_net.py selfcheck out.json    # random net -> json + .check (parity fixture)
"""
from __future__ import annotations

import json
import sys

import torch
import torch.nn as nn

TOK_N, TOK_F, TOK_STATE = 32, 28, 96
D, HEADS, FF, LAYERS, TRUNK = 48, 4, 96, 2, 128
N_ACT = 102
NEG = -1e9

# token-tied action map (mirror of attn.rs tied_actions / tokfeats layout)
A_BUY_BLACK0, A_DISCARD0, A_TAKE_HEX0, A_PLACE_SLOT0 = 15, 19, 48, 62
TIED = {}
for t in range(12):
    TIED[t] = (A_TAKE_HEX0 + t, None)
for t in range(4):
    TIED[12 + t] = (A_BUY_BLACK0 + t, None)
for t in range(3):
    TIED[16 + t] = (A_DISCARD0 + t, A_PLACE_SLOT0 + t)
TIED_IDS = {a for pair in TIED.values() for a in pair if a is not None}
GIDX = [a for a in range(N_ACT) if a not in TIED_IDS]
assert len(GIDX) == 80
# vectorized-scatter index tensors (the python per-token loop was ~38 GPU kernel
# launches per forward — it made the inference sidecar launch-bound, 10k evals/s)
TIED_TOK = torch.tensor(sorted(TIED))                              # [19]
TIED_A0 = torch.tensor([TIED[t][0] for t in sorted(TIED)])         # [19]
PLACE_TOK = torch.tensor([t for t in sorted(TIED) if TIED[t][1] is not None])
PLACE_A1 = torch.tensor([TIED[t][1] for t in sorted(TIED) if TIED[t][1] is not None])


class AttnNet(nn.Module):
    """`aux_dim>0` adds a trunk-shared auxiliary regression head (terminal
    score-decomposition targets — the +9.6pp MLP-distill lever, 2026-07-12)
    that is EXCLUDED from export_json/import_json: exported jsons stay
    shape-identical, so attn.rs / the sidecar / parity checks need no change."""

    def __init__(self, aux_dim: int = 0):
        super().__init__()
        self.emb = nn.Linear(TOK_F, D)
        self.wq = nn.ModuleList(nn.Linear(D, D, bias=False) for _ in range(LAYERS))
        self.wk = nn.ModuleList(nn.Linear(D, D, bias=False) for _ in range(LAYERS))
        self.wv = nn.ModuleList(nn.Linear(D, D, bias=False) for _ in range(LAYERS))
        self.wo = nn.ModuleList(nn.Linear(D, D, bias=False) for _ in range(LAYERS))
        self.f1 = nn.ModuleList(nn.Linear(D, FF) for _ in range(LAYERS))
        self.f2 = nn.ModuleList(nn.Linear(FF, D) for _ in range(LAYERS))
        self.ln1 = nn.ModuleList(nn.LayerNorm(D, elementwise_affine=False) for _ in range(LAYERS))
        self.ln2 = nn.ModuleList(nn.LayerNorm(D, elementwise_affine=False) for _ in range(LAYERS))
        self.se = nn.Linear(TOK_STATE, D)
        self.trunk = nn.Linear(2 * D, TRUNK)
        self.vh = nn.Linear(TRUNK, 1)
        self.pg = nn.Linear(TRUNK, len(GIDX))
        self.ptok = nn.Linear(D, 2)
        self.ah = nn.Linear(TRUNK, aux_dim) if aux_dim > 0 else None
        self.aux_dim = aux_dim
        # index tensors as (non-persistent) buffers so they live on the net's
        # device — indexing CUDA tensors with CPU indices does a host->device
        # copy per call, which is both slow and ILLEGAL inside CUDA-graph capture
        self.register_buffer("b_gidx", torch.tensor(GIDX), persistent=False)
        self.register_buffer("b_tied_tok", TIED_TOK.clone(), persistent=False)
        self.register_buffer("b_tied_a0", TIED_A0.clone(), persistent=False)
        self.register_buffer("b_place_tok", PLACE_TOK.clone(), persistent=False)
        self.register_buffer("b_place_a1", PLACE_A1.clone(), persistent=False)

    def _backbone(self, tokens, mask, state):
        """Shared encoder -> (trunk hidden [B,TRUNK], token states x [B,T,D])."""
        b = tokens.shape[0]
        x = self.emb(tokens)                                  # [B,T,D]
        keep = (mask >= 0.5)[:, None, None, :]                # SDPA: True = attend
        hd = D // HEADS
        for l in range(LAYERS):
            q = self.wq[l](x).view(b, TOK_N, HEADS, hd).transpose(1, 2)   # [B,H,T,hd]
            k = self.wk[l](x).view(b, TOK_N, HEADS, hd).transpose(1, 2)
            v = self.wv[l](x).view(b, TOK_N, HEADS, hd).transpose(1, 2)
            ctx = torch.nn.functional.scaled_dot_product_attention(q, k, v, attn_mask=keep)
            ctx = ctx.transpose(1, 2).reshape(b, TOK_N, D)
            x = self.ln1[l](x + self.wo[l](ctx))
            x = self.ln2[l](x + self.f2[l](torch.relu(self.f1[l](x))))
        pool = (x * mask[:, :, None]).sum(1) / mask.sum(1, keepdim=True).clamp(min=1.0)
        cat = torch.cat([pool, self.se(state)], dim=1)
        return torch.relu(self.trunk(cat)), x

    def _heads(self, ht, x, mask, tokens):
        b = tokens.shape[0]
        val = torch.tanh(self.vh(ht)).squeeze(-1)
        pol = torch.full((b, N_ACT), NEG, device=tokens.device, dtype=tokens.dtype)
        pol[:, self.b_gidx] = self.pg(ht)
        tl = self.ptok(x)                                     # [B,T,2]
        neg = pol.new_full((), NEG)
        pol[:, self.b_tied_a0] = torch.where(
            mask[:, self.b_tied_tok] >= 0.5, tl[:, self.b_tied_tok, 0], neg)
        pol[:, self.b_place_a1] = torch.where(
            mask[:, self.b_place_tok] >= 0.5, tl[:, self.b_place_tok, 1], neg)
        return val, pol

    def forward(self, tokens, mask, state):
        """tokens [B,TOK_N,TOK_F], mask [B,TOK_N] (0/1), state [B,TOK_STATE]
        -> (value [B], policy [B,N_ACT] with -1e9 at masked/absent slots)."""
        ht, x = self._backbone(tokens, mask, state)
        return self._heads(ht, x, mask, tokens)

    def forward_with_aux(self, tokens, mask, state):
        """forward + the aux head's regression output (training only)."""
        ht, x = self._backbone(tokens, mask, state)
        val, pol = self._heads(ht, x, mask, tokens)
        return val, pol, self.ah(ht)

    @staticmethod
    def split_flat(rows):
        tokens = rows[:, : TOK_N * TOK_F].view(-1, TOK_N, TOK_F)
        mask = rows[:, TOK_N * TOK_F : TOK_N * TOK_F + TOK_N]
        state = rows[:, TOK_N * TOK_F + TOK_N :]
        return tokens, mask, state

    def forward_flat(self, rows):
        """rows [B, 1024] in the tokfeats layout -> (value, policy)."""
        return self.forward(*self.split_flat(rows))

    def forward_with_aux_flat(self, rows):
        return self.forward_with_aux(*self.split_flat(rows))


def flat(t):
    return [float(v) for v in t.detach().cpu().flatten().tolist()]


def export_json(net: AttnNet, path: str) -> None:
    out = {
        "t": TOK_N, "f": TOK_F, "d": D, "heads": HEADS, "ff": FF,
        "layers": LAYERS, "state": TOK_STATE, "trunk": TRUNK,
        "emb_w": flat(net.emb.weight), "emb_b": flat(net.emb.bias),
        "wq": [flat(m.weight) for m in net.wq], "wk": [flat(m.weight) for m in net.wk],
        "wv": [flat(m.weight) for m in net.wv], "wo": [flat(m.weight) for m in net.wo],
        "f1w": [flat(m.weight) for m in net.f1], "f1b": [flat(m.bias) for m in net.f1],
        "f2w": [flat(m.weight) for m in net.f2], "f2b": [flat(m.bias) for m in net.f2],
        "sw": flat(net.se.weight), "sb": flat(net.se.bias),
        "tw": flat(net.trunk.weight), "tb": flat(net.trunk.bias),
        "vw": flat(net.vh.weight), "vb": flat(net.vh.bias),
        "pw": flat(net.pg.weight), "pb": flat(net.pg.bias),
        "ptok_w": flat(net.ptok.weight), "ptok_b": flat(net.ptok.bias),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f)


def write_check(net: AttnNet, path: str, n: int = 8) -> None:
    """Parity fixture: n random rows (some tokens masked) + torch outputs."""
    g = torch.Generator().manual_seed(7)
    tokens = torch.rand((n, TOK_N, TOK_F), generator=g) * 1.4 - 0.2
    mask = (torch.rand((n, TOK_N), generator=g) > 0.25).float()
    mask[:, 0] = 1.0  # never fully masked
    state = torch.rand((n, TOK_STATE), generator=g)
    with torch.no_grad():
        val, pol = net(tokens, mask, state)
    rows = torch.cat([tokens.reshape(n, -1), mask, state], dim=1)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "rows": [[float(v) for v in r] for r in rows],
            "values": [float(v) for v in val],
            "logits": [[float(x) for x in row] for row in pol],
        }, f)


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "selfcheck":
        torch.manual_seed(11)
        net = AttnNet().eval()
        # non-degenerate random weights
        with torch.no_grad():
            for p in net.parameters():
                p.mul_(3.0)
        export_json(net, sys.argv[2])
        write_check(net, sys.argv[2] + ".check")
        print(f"selfcheck net -> {sys.argv[2]} (+.check)")
    else:
        print(__doc__)


def import_json(path: str, aux_dim: int = 0) -> "AttnNet":
    """Inverse of export_json — load an exported net back into torch (warm starts,
    and the sidecar's attention branch). `aux_dim` attaches a FRESH-init aux
    head (the exported json never carries one)."""
    with open(path, encoding="utf-8") as f:
        j = json.load(f)
    assert j["t"] == TOK_N and j["d"] == D and j["trunk"] == TRUNK, "shape mismatch"
    net = AttnNet(aux_dim=aux_dim)
    with torch.no_grad():
        def cp(param, vals):
            param.copy_(torch.tensor(vals, dtype=torch.float32).view_as(param))
        cp(net.emb.weight, j["emb_w"]); cp(net.emb.bias, j["emb_b"])
        for l in range(LAYERS):
            cp(net.wq[l].weight, j["wq"][l]); cp(net.wk[l].weight, j["wk"][l])
            cp(net.wv[l].weight, j["wv"][l]); cp(net.wo[l].weight, j["wo"][l])
            cp(net.f1[l].weight, j["f1w"][l]); cp(net.f1[l].bias, j["f1b"][l])
            cp(net.f2[l].weight, j["f2w"][l]); cp(net.f2[l].bias, j["f2b"][l])
        cp(net.se.weight, j["sw"]); cp(net.se.bias, j["sb"])
        cp(net.trunk.weight, j["tw"]); cp(net.trunk.bias, j["tb"])
        cp(net.vh.weight, j["vw"]); cp(net.vh.bias, j["vb"])
        cp(net.pg.weight, j["pw"]); cp(net.pg.bias, j["pb"])
        cp(net.ptok.weight, j["ptok_w"]); cp(net.ptok.bias, j["ptok_b"])
    return net
