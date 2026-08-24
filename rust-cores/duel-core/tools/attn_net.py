"""PyTorch twin of `duel-core/src/attn.rs` (card-set attention VALUE net, value-only).

Must match the Rust forward OP-FOR-OP — it PLAYS (Rust) what it TRAINS (torch). Parity is verified by
`bin/attn_parity` to 1e-4 on random weights + a random input before any training is trusted.

  python duel-core/tools/attn_net.py parity --out C:/Users/Forrest/duel_run/attn_parity
"""
import argparse
import json
import os

import torch
import torch.nn as nn

D = 64
HEADS = 4
HD = D // HEADS
FF = 128
L = 2
H = 128
TOK_N = 15
TOK_F = 30
TOK_STATE = 47
N_ACTIONS = 320  # policy output space — must match duel-core/src/actions.rs::N_ACTIONS


def ln(x):  # no-affine LayerNorm over last dim, eps 1e-5 (matches attn.rs::layernorm)
    mean = x.mean(-1, keepdim=True)
    var = x.var(-1, unbiased=False, keepdim=True)
    return (x - mean) / torch.sqrt(var + 1e-5)


class AttnNet(nn.Module):
    def __init__(self):
        super().__init__()
        self.emb = nn.Linear(TOK_F, D)
        self.wq = nn.ModuleList([nn.Linear(D, D, bias=False) for _ in range(L)])
        self.wk = nn.ModuleList([nn.Linear(D, D, bias=False) for _ in range(L)])
        self.wv = nn.ModuleList([nn.Linear(D, D, bias=False) for _ in range(L)])
        self.wo = nn.ModuleList([nn.Linear(D, D, bias=False) for _ in range(L)])
        self.f1 = nn.ModuleList([nn.Linear(D, FF) for _ in range(L)])
        self.f2 = nn.ModuleList([nn.Linear(FF, D) for _ in range(L)])
        self.s = nn.Linear(TOK_STATE, D)
        self.t = nn.Linear(2 * D, H)
        self.v = nn.Linear(H, 1)
        # AUX heads (training-ONLY; NOT exported — attn.rs / the parity contract are unchanged). They
        # read the shared trunk `ht` and predict game-final quantities, regularizing the trunk so the
        # value head better encodes development (the under-development blind spot). Used only by
        # `forward_aux` in `train_attn_aux.py`; `forward`/`export` are byte-for-byte as before.
        self.aux_card = nn.Linear(H, 1)      # my final purchased-card margin
        self.aux_crown = nn.Linear(H, 1)     # my final crown margin
        self.aux_wincond = nn.Linear(H, 3)   # eventual win-condition: points / crowns / color
        self.aux_len = nn.Linear(H, 1)       # game length (turns)
        # POLICY head (AZ) — logits over the 320-action space (actions.rs). Used ONLY by the AZ
        # policy+value path (`forward_pv`, exported via `export_pv`); the value-only `forward`/`export`
        # are unchanged, so a value-only net is byte-identical to before.
        self.policy = nn.Linear(H, N_ACTIONS)

    def trunk(self, tok, mask, state):
        # tok [B,TOK_N,TOK_F], mask [B,TOK_N], state [B,TOK_STATE] -> ht [B,H]
        B = tok.shape[0]
        x = self.emb(tok)  # [B,TOK_N,D]
        scale = 1.0 / (HD ** 0.5)
        present = mask >= 0.5  # [B,TOK_N] key mask
        for l in range(L):
            q, k, v = self.wq[l](x), self.wk[l](x), self.wv[l](x)  # [B,TOK_N,D]

            def heads(z):
                return z.view(B, TOK_N, HEADS, HD).transpose(1, 2)  # [B,HEADS,TOK_N,HD]

            qh, kh, vh = heads(q), heads(k), heads(v)
            sc = (qh @ kh.transpose(-1, -2)) * scale  # [B,HEADS,TOK_N,TOK_N]
            keymask = present.view(B, 1, 1, TOK_N)
            sc = sc.masked_fill(~keymask, float("-inf"))
            a = torch.softmax(sc, dim=-1)
            ctx = (a @ vh).transpose(1, 2).contiguous().view(B, TOK_N, D)
            x = ln(x + self.wo[l](ctx))
            h = self.f2[l](torch.relu(self.f1[l](x)))
            x = ln(x + h)
        m = present.unsqueeze(-1).float()  # [B,TOK_N,1]
        pool = (x * m).sum(1) / m.sum(1).clamp(min=1.0)  # [B,D]
        se = self.s(state)  # [B,D]
        return torch.relu(self.t(torch.cat([pool, se], dim=-1)))  # [B,H]

    def forward(self, tok, mask, state):
        return torch.tanh(self.v(self.trunk(tok, mask, state))).squeeze(-1)  # [B]

    def forward_aux(self, tok, mask, state):
        """Value + the four aux predictions (training only; value output identical to `forward`)."""
        ht = self.trunk(tok, mask, state)
        return (
            torch.tanh(self.v(ht)).squeeze(-1),
            self.aux_card(ht).squeeze(-1),
            self.aux_crown(ht).squeeze(-1),
            self.aux_wincond(ht),  # [B,3] logits
            self.aux_len(ht).squeeze(-1),
        )

    def forward_pv(self, tok, mask, state):
        """Value + policy logits (AZ). Value output is identical to `forward`."""
        ht = self.trunk(tok, mask, state)
        return torch.tanh(self.v(ht)).squeeze(-1), self.policy(ht)  # [B], [B,N_ACTIONS]

    def export(self):
        def w(lin):
            return lin.weight.detach().cpu().flatten().tolist()

        def b(lin):
            return lin.bias.detach().cpu().tolist()

        return {
            "emb_w": w(self.emb), "emb_b": b(self.emb),
            "wq": [w(m) for m in self.wq], "wk": [w(m) for m in self.wk],
            "wv": [w(m) for m in self.wv], "wo": [w(m) for m in self.wo],
            "f1w": [w(m) for m in self.f1], "f1b": [b(m) for m in self.f1],
            "f2w": [w(m) for m in self.f2], "f2b": [b(m) for m in self.f2],
            "sw": w(self.s), "sb": b(self.s), "tw": w(self.t), "tb": b(self.t),
            "vw": w(self.v), "vb": b(self.v),
        }

    def export_pv(self):
        """Value export + the policy head (AZ). `attn.rs` loads the value path exactly as before,
        plus `pw`/`pb` for the policy logits used as the search prior."""
        d = self.export()
        d["pw"] = self.policy.weight.detach().cpu().flatten().tolist()
        d["pb"] = self.policy.bias.detach().cpu().tolist()
        return d


def cmd_parity(args):
    torch.manual_seed(0)
    net = AttnNet().double()  # double for a clean reference; Rust is f32 so tolerance is ~1e-4
    net.eval()
    # A random input with a realistic mask (some absent tokens).
    g = torch.Generator().manual_seed(1)
    tok = torch.rand(1, TOK_N, TOK_F, generator=g, dtype=torch.float64)
    mask = (torch.rand(1, TOK_N, generator=g, dtype=torch.float64) > 0.3).double()
    mask[0, 0] = 1.0  # ensure >=1 present
    state = torch.rand(1, TOK_STATE, generator=g, dtype=torch.float64)
    with torch.no_grad():
        val_t, pol_t = net.forward_pv(tok, mask, state)
        val = val_t.item()
        pol = pol_t.squeeze(0).tolist()  # [N_ACTIONS] policy logits (random head — parity of the matmul)
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "weights.json"), "w") as f:
        json.dump(net.export_pv(), f)  # value path + pw/pb, so the Rust side can parity the policy head
    with open(os.path.join(args.out, "input.json"), "w") as f:
        json.dump({
            "tokens": tok.flatten().tolist(),
            "mask": mask.flatten().tolist(),
            "state": state.flatten().tolist(),
            "expected": val,
            "expected_policy": pol,
        }, f)
    print(f"parity dump -> {args.out}  (torch value = {val:.8f}, |policy| = {len(pol)})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("parity")
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_parity)
    a = ap.parse_args()
    a.func(a)
