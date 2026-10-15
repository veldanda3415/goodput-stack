"""CALCULATED network bytes and time per step for LLM collectives.

Alpha-beta model: T = alpha * steps + bytes_on_wire / effective_bandwidth.
Bytes-on-wire factors follow nccl-tests busbw (sources.md S15); tree latency
follows NCCL double binary trees (S16); TP traffic follows Megatron-LM (S17).
Nothing here is measured. Derivations are in fabric/DESIGN.md section 2.

    python -m fabric.design.collectives [--config fabric/design/inputs.yaml]
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_CONFIG = Path(__file__).with_name("inputs.yaml")
SCALE_UP = "scale-up (NVLink)"
SCALE_OUT = "scale-out (backend)"


@dataclass(frozen=True)
class Link:
    """One network's effective per-GPU, per-direction bandwidth and per-step latency."""

    bytes_per_s: float
    alpha_s: float


@dataclass(frozen=True)
class Comm:
    """One collective's per-GPU cost for one call."""

    up_bytes: float
    out_bytes: float
    time_s: float


# ---- primitive collectives (N ranks, S bytes buffer per rank) -------------------------------


def ring_allreduce_bytes(n: int, s: float) -> float:
    return 2 * (n - 1) / n * s


def ring_allreduce_time(n: int, s: float, link: Link) -> float:
    # reduce-scatter (N-1 steps) + all-gather (N-1 steps), each step moves S/N.
    return 2 * (n - 1) * link.alpha_s + ring_allreduce_bytes(n, s) / link.bytes_per_s


def tree_allreduce_time(n: int, s: float, link: Link) -> float:
    # Double binary tree: reduce up + broadcast down, depth ceil(log2 N) each way;
    # NCCL reports full bandwidth (S16), so the bandwidth term equals the ring's.
    depth = math.ceil(math.log2(n)) if n > 1 else 0
    return 2 * depth * link.alpha_s + ring_allreduce_bytes(n, s) / link.bytes_per_s


def scatter_gather_bytes(n: int, s: float) -> float:
    """Reduce-scatter, all-gather and all-to-all: (N-1)/N * S on the wire per rank."""
    return (n - 1) / n * s


def scatter_gather_time(n: int, s: float, link: Link) -> float:
    return (n - 1) * link.alpha_s + scatter_gather_bytes(n, s) / link.bytes_per_s


def p2p_time(s: float, link: Link) -> float:
    return link.alpha_s + s / link.bytes_per_s


def hierarchical_allreduce(local: int, nodes: int, s: float, nvl: Link, net: Link,
                           net_rate_fraction: float = 1.0) -> Comm:
    """Intra-node reduce-scatter over NVLink, inter-node ring all-reduce of S/local per
    GPU on its own rail NIC, intra-node all-gather. net_rate_fraction < 1 models one
    slow link in the inter-node ring (the ring runs at its slowest link)."""
    shard = s / local
    up = 2 * scatter_gather_bytes(local, s) if local > 1 else 0.0
    out = ring_allreduce_bytes(nodes, shard) if nodes > 1 else 0.0
    slow = Link(net.bytes_per_s * net_rate_fraction, net.alpha_s)
    t = 0.0
    if local > 1:
        t += 2 * scatter_gather_time(local, s, nvl)
    if nodes > 1:
        t += ring_allreduce_time(nodes, shard, slow)
    return Comm(up, out, t)


# ---- placement ------------------------------------------------------------------------------


def split_group(size: int, stride: int, gpus_per_node: int) -> tuple[int, int]:
    """Members of a rank group (consecutive ranks `stride` apart) -> (per node, nodes)."""
    if size * stride <= gpus_per_node:
        return size, 1
    if stride >= gpus_per_node:
        return 1, size
    local = gpus_per_node // stride
    return local, size // local


def network_label(local: int, nodes: int) -> str:
    if nodes == 1:
        return SCALE_UP
    if local == 1:
        return SCALE_OUT
    return "both (NVLink + scale-out)"


def kv_bytes_per_token(layers: int, kv_heads: int, head_dim: int, dtype_bytes: int) -> int:
    """K and V for every layer: 2 * layers * kv_heads * head_dim * dtype_bytes."""
    return 2 * layers * kv_heads * head_dim * dtype_bytes


# ---- workloads ------------------------------------------------------------------------------


def links(cfg: dict) -> tuple[Link, Link]:
    hw, eff, alpha = cfg["hardware"], cfg["efficiency"], cfg["alpha_us"]
    nvl = Link(hw["nvlink_gbytes_per_dir"] * 1e9 * eff["nvlink"], alpha["nvlink"] * 1e-6)
    net = Link(hw["nic_gbps"] * 1e9 / 8 * eff["network"], alpha["network"] * 1e-6)
    return nvl, net


@dataclass
class Row:
    parallelism: str
    collective: str
    group: int
    network: str
    calls: int
    up_bytes: float
    out_bytes: float
    time_s: float


def training_rows(cfg: dict, w: dict, net_rate_fraction: float = 1.0) -> list[Row]:
    """Per-GPU traffic for one optimizer step of workload w."""
    m = cfg["models"][w["model"]]
    g = cfg["hardware"]["gpus_per_node"]
    nvl, net = links(cfg)
    tp, pp, dp, ep = w["tp"], w["pp"], w["dp"], w.get("ep", 1)
    d, mb = w["dtype_bytes"], w["microbatches"]
    act = w["micro_batch"] * w["seq_len"] * m["hidden"] * d  # one microbatch activation
    layers_per_stage = m["layers"] // pp
    rows: list[Row] = []

    if tp > 1:  # Megatron TP: 2 all-reduces forward + 2 backward per layer (S17)
        local, nodes = split_group(tp, 1, g)
        calls = 4 * layers_per_stage * mb
        if nodes == 1:
            one = Comm(ring_allreduce_bytes(tp, act), 0.0, ring_allreduce_time(tp, act, nvl))
        else:
            one = hierarchical_allreduce(local, nodes, act, nvl, net)
        rows.append(Row("TP", "all-reduce (activations)", tp, network_label(local, nodes),
                        calls, one.up_bytes * calls, one.out_bytes * calls, one.time_s * calls))

    if pp > 1:  # forward activation + backward gradient per microbatch per stage boundary
        stride = tp * dp
        calls = 2 * mb
        cross = stride >= g or pp * stride > g
        lk = net if cross else nvl
        rows.append(Row("PP", "send/recv (activations)", pp, SCALE_OUT if cross else SCALE_UP,
                        calls, 0.0 if cross else act * calls, act * calls if cross else 0.0,
                        p2p_time(act, lk) * calls))

    if ep > 1:  # MoE: dispatch + combine, forward and backward, per MoE layer (S18)
        local, nodes = split_group(ep, tp, g)
        s = w["micro_batch"] * w["seq_len"] * m["top_k"] * m["hidden"] * d
        calls = 4 * layers_per_stage * mb
        up = s * (local - 1) / ep
        out = s * (ep - local) / ep
        t = (ep - 1) * net.alpha_s + up / nvl.bytes_per_s + out / net.bytes_per_s
        rows.append(Row("EP", "all-to-all (tokens)", ep, network_label(local, nodes),
                        calls, up * calls, out * calls, t * calls))

    if dp > 1:  # gradient all-reduce once per optimizer step
        local, nodes = split_group(dp, tp, g)
        grads = m["params"] / (tp * pp) * d
        one = hierarchical_allreduce(local, nodes, grads, nvl, net, net_rate_fraction)
        rows.append(Row("DP", "all-reduce (gradients)", dp, network_label(local, nodes),
                        1, one.up_bytes, one.out_bytes, one.time_s))
    return rows


def compute_time_s(cfg: dict, w: dict) -> float:
    """6 * active params * tokens / (GPUs * peak * MFU), the standard dense training estimate."""
    m = cfg["models"][w["model"]]
    gpus = w["tp"] * w["pp"] * w["dp"]
    tokens = w["micro_batch"] * w["seq_len"] * w["microbatches"] * w["dp"]
    flops = 6 * m.get("active_params", m["params"]) * tokens
    return flops / (gpus * cfg["hardware"]["gpu_dense_tflops"] * 1e12 * cfg["mfu"])


def step_time_s(cfg: dict, w: dict, net_rate_fraction: float = 1.0) -> tuple[float, float]:
    """(compute, exposed communication) per step; exposed = comm * (1 - overlap)."""
    comm = sum(r.time_s for r in training_rows(cfg, w, net_rate_fraction))
    return compute_time_s(cfg, w), comm * (1 - cfg["overlap"])


def slowdown(normal: float, slow: float) -> float:
    return slow / normal - 1


def kv_transfer(cfg: dict, case: dict) -> dict:
    m = cfg["models"][case["model"]]
    per_tok = kv_bytes_per_token(m["layers"], m["kv_heads"], m["head_dim"], case["dtype_bytes"])
    per_req = per_tok * case["prompt_tokens"]
    gbps = per_req * case["requests_per_s"] * 8 / 1e9
    nic = cfg["hardware"]["nic_gbps"] * cfg["efficiency"]["network"]
    return {"per_token": per_tok, "per_request": per_req, "gbps": gbps,
            "nics": math.ceil(gbps / nic), "one_req_ms": per_req * 8 / (nic * 1e9) * 1e3}


# ---- Markdown -------------------------------------------------------------------------------


def gb(x: float) -> str:
    return "0" if x == 0 else f"{x / 1e9:,.3f}"


def ms(x: float) -> str:
    return f"{x * 1e3:,.2f}"


def table(header: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(header) + " |",
           "|" + "|".join("---" if i == 0 else "---:" for i in range(len(header))) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out)


def training_md(cfg: dict) -> str:
    parts = []
    for w in cfg["training"]:
        rows = training_rows(cfg, w)
        comp, comm = step_time_s(cfg, w)
        body = [[r.parallelism, r.collective, str(r.group), r.network, f"{r.calls:,}",
                 gb(r.up_bytes), gb(r.out_bytes), ms(r.time_s)] for r in rows]
        body.append(["**compute**", "6·P·tokens / (GPUs·peak·MFU)", "", "", "", "", "", ms(comp)])
        body.append(["**step**", "compute + exposed comm", "", "", "", "", "", ms(comp + comm)])
        parts.append(f"**{w['name']}** (TP {w['tp']} · PP {w['pp']} · DP {w['dp']} · EP "
                     f"{w.get('ep', 1)}; seq {w['seq_len']:,}, {w['microbatches']} microbatch(es))"
                     " — CALCULATED\n\n" + table(
                         ["Par.", "Collective", "Group", "Network", "Calls/step",
                          "Scale-up GB/GPU/step", "Scale-out GB/GPU/step", "Time/step (ms)"],
                         body))
    return "\n\n".join(parts)


def slow_link_md(cfg: dict) -> str:
    sl = cfg["slow_link"]
    w = next(x for x in cfg["training"] if x["name"] == sl["workload"])
    f = sl["rate_fraction"]
    dp = next(r for r in training_rows(cfg, w) if r.parallelism == "DP")
    dp_slow = next(r for r in training_rows(cfg, w, f) if r.parallelism == "DP")
    comp, comm = step_time_s(cfg, w)
    _, comm_slow = step_time_s(cfg, w, f)
    rows = [
        ["DP gradient all-reduce", ms(dp.time_s), ms(dp_slow.time_s),
         f"{slowdown(dp.time_s, dp_slow.time_s):+.1%}"],
        ["Step (compute + exposed comm)", ms(comp + comm), ms(comp + comm_slow),
         f"{slowdown(comp + comm, comp + comm_slow):+.1%}"],
    ]
    return (f"**One link at {f:.0%} rate in the inter-node ring — {w['name']}** — CALCULATED\n\n"
            + table(["Quantity", "All links healthy (ms)", "One slow link (ms)", "Change"], rows))


def inference_md(cfg: dict) -> str:
    rows = []
    for c in cfg["inference"]:
        r = kv_transfer(cfg, c)
        rows.append([c["model"], f"{r['per_token']:,}", f"{c['prompt_tokens']:,}",
                     f"{r['per_request'] / 1e6:,.1f}", f"{c['requests_per_s']:,}",
                     f"{r['gbps']:,.1f}", str(r["nics"]), f"{r['one_req_ms']:,.2f}"])
    nic = cfg["hardware"]["nic_gbps"]
    eff = cfg["efficiency"]["network"]
    return ("**Prefill → decode KV-cache transfer** — CALCULATED\n\n" + table(
        ["Model", "KV B/token", "Prompt tokens", "KV MB/request", "Requests/s",
         "Scale-out Gb/s needed", f"{nic}G NICs @ {eff:.0%}", "One request on one NIC (ms)"],
        rows))


SECTIONS = {"training": training_md, "slow-link": slow_link_md, "inference": inference_md}


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    p.add_argument("--section", choices=["all", *SECTIONS], default="all")
    a = p.parse_args(argv)
    cfg = yaml.safe_load(a.config.read_text())
    names = list(SECTIONS) if a.section == "all" else [a.section]
    print("\n\n".join(SECTIONS[n](cfg) for n in names))


if __name__ == "__main__":
    main()
