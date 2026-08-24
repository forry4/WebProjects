"""PyTorch twin of coc-core's PolicyValueNet (valuenet.rs) + JSON export.

PARITY RULES (locked; net_export_check enforces <=1e-3):
  y = x @ W^T + b (torch Linear default = Rust `linear` row-major),
  z-score input with exported mu/sd, ReLU on every trunk layer,
  value head -> tanh scalar, policy head -> raw 102 logits.
"""
from __future__ import annotations

import json

import torch
import torch.nn as nn

IN_DIM = 934
N_ACT = 102
TRUNK = (512, 256)


class PVNet(nn.Module):
    """`aux_dim>0` adds a KataGo-style auxiliary regression head (predicts
    terminal score-decomposition targets) sharing the same trunk as the
    value/policy heads — pure gradient shaping. It is DELIBERATELY excluded
    from `export_json`/`load_json` (they only ever touch trunk/vh/ph), so a
    net trained with an aux head produces a byte-identical-shape JSON to one
    trained without it: the Rust serving/search side needs zero changes."""

    def __init__(self, in_dim=IN_DIM, trunk=TRUNK, n_act=N_ACT, aux_dim=0):
        super().__init__()
        dims = [in_dim, *trunk]
        self.trunk = nn.ModuleList(
            nn.Linear(dims[i], dims[i + 1]) for i in range(len(dims) - 1))
        self.vh = nn.Linear(dims[-1], 1)
        self.ph = nn.Linear(dims[-1], n_act)
        self.ah = nn.Linear(dims[-1], aux_dim) if aux_dim > 0 else None
        self.in_dim, self.n_act, self.aux_dim = in_dim, n_act, aux_dim
        self.tdims = dims

    def trunk_out(self, x):
        for lin in self.trunk:
            x = torch.relu(lin(x))
        return x

    def forward(self, x):
        h = self.trunk_out(x)
        return torch.tanh(self.vh(h)).squeeze(-1), self.ph(h)

    def forward_aux(self, x):
        return self.ah(self.trunk_out(x))


def export_json(net: PVNet, mu, sd, path: str) -> None:
    def flat(t):
        return [float(v) for v in t.detach().cpu().flatten().tolist()]

    out = {
        "mu": [float(v) for v in mu],
        "sd": [float(v) for v in sd],
        "tdims": list(net.tdims),
        "tw": [flat(l.weight) for l in net.trunk],
        "tb": [flat(l.bias) for l in net.trunk],
        "vw": flat(net.vh.weight),
        "vb": flat(net.vh.bias),
        "pw": flat(net.ph.weight),
        "pb": flat(net.ph.bias),
        "n_act": net.n_act,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f)


def load_json(path: str, aux_dim: int = 0) -> tuple[PVNet, list[float], list[float]]:
    with open(path, encoding="utf-8") as f:
        j = json.load(f)
    net = PVNet(in_dim=len(j["mu"]), trunk=tuple(j["tdims"][1:]), n_act=j["n_act"],
                aux_dim=aux_dim)
    with torch.no_grad():
        for l, w, b in zip(net.trunk, j["tw"], j["tb"]):
            l.weight.copy_(torch.tensor(w).view_as(l.weight))
            l.bias.copy_(torch.tensor(b))
        net.vh.weight.copy_(torch.tensor(j["vw"]).view_as(net.vh.weight))
        net.vh.bias.copy_(torch.tensor(j["vb"]))
        net.ph.weight.copy_(torch.tensor(j["pw"]).view_as(net.ph.weight))
        net.ph.bias.copy_(torch.tensor(j["pb"]))
    return net, j["mu"], j["sd"]
