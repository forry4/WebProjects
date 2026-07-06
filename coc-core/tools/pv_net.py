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
    def __init__(self, in_dim=IN_DIM, trunk=TRUNK, n_act=N_ACT):
        super().__init__()
        dims = [in_dim, *trunk]
        self.trunk = nn.ModuleList(
            nn.Linear(dims[i], dims[i + 1]) for i in range(len(dims) - 1))
        self.vh = nn.Linear(dims[-1], 1)
        self.ph = nn.Linear(dims[-1], n_act)
        self.in_dim, self.n_act = in_dim, n_act
        self.tdims = dims

    def forward(self, x):
        for lin in self.trunk:
            x = torch.relu(lin(x))
        return torch.tanh(self.vh(x)).squeeze(-1), self.ph(x)


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


def load_json(path: str) -> tuple[PVNet, list[float], list[float]]:
    with open(path, encoding="utf-8") as f:
        j = json.load(f)
    net = PVNet(in_dim=len(j["mu"]), trunk=tuple(j["tdims"][1:]), n_act=j["n_act"])
    with torch.no_grad():
        for l, w, b in zip(net.trunk, j["tw"], j["tb"]):
            l.weight.copy_(torch.tensor(w).view_as(l.weight))
            l.bias.copy_(torch.tensor(b))
        net.vh.weight.copy_(torch.tensor(j["vw"]).view_as(net.vh.weight))
        net.vh.bias.copy_(torch.tensor(j["vb"]))
        net.ph.weight.copy_(torch.tensor(j["pw"]).view_as(net.ph.weight))
        net.ph.bias.copy_(torch.tensor(j["pb"]))
    return net, j["mu"], j["sd"]
