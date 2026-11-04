"""CALCULATED scale-out of LLM decode: tensor-parallel all-reduce and prefill -> decode KV transfer per link type.

"A faster GPU hands the bottleneck to the fabric", built only from measured inputs read from this repo and cited
specs (sources.md). Uses the alpha-beta model of collectives.py. Nothing here is measured.

    python -m fabric.design.scaleout [--config fabric/design/inputs.yaml] [--check]

Writes the tables between `<!-- scaleout:NAME -->` and `<!-- /scaleout -->` in fabric/design/scaleout.md.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

from fabric.design import nccl_check
from fabric.design.collectives import (DEFAULT_CONFIG, Link, kv_bytes_per_token, p2p_time, ring_allreduce_bytes,
                                       ring_allreduce_time, table)

REPO = Path(__file__).resolve().parents[2]
DOC = Path(__file__).with_name("scaleout.md")
PENDING = "pending Modal run D"


@dataclass(frozen=True)
class Model:
    name: str
    repo: str
    revision: str
    layers: int
    hidden: int
    heads: int
    kv_heads: int
    head_dim: int
    head_dim_source: str


@dataclass(frozen=True)
class NamedLink:
    name: str
    link: Link
    source: str


def load_model(m: dict) -> Model:
    c = json.loads((REPO / m["config"]).read_text())
    hd, src = (c["head_dim"], "config head_dim") if c.get("head_dim") else \
        (c["hidden_size"] // c["num_attention_heads"], "hidden_size / num_attention_heads")
    return Model(m["name"], m["repo"], m["revision"], c["num_hidden_layers"], c["hidden_size"],
                 c["num_attention_heads"], c["num_key_value_heads"], hd, src)


def dig(d, path: str):
    for k in path.split("."):
        d = d[k]
    return d


def jsonl_row(path: Path, key: str) -> dict:
    return next(r for r in map(json.loads, filter(str.strip, path.read_text().splitlines())) if r.get("key") == key)


def t4_step_ms(cfg: dict) -> dict[int, dict]:
    """Measured T4 decode-step time of Qwen2.5-3B (TP 1) by batch, read from the files named in inputs.yaml."""
    out = {}
    for batch, s in cfg["t4_step_ms"].items():
        p = REPO / s["file"]
        if "key" in s:
            v = dig(jsonl_row(p, s["key"]), s["field"])
            ms = 1000 / v if s["field"].startswith("decode_tok_s") else v
        else:
            v = dig(json.loads(p.read_text()), s["field"])
            ms = v
        out[int(batch)] = {"ms": ms, "raw": v, "file": s["file"], "row": s.get("key"), "field": s["field"], "how": s["how"]}
    return out


def ridge_step_ms(cfg: dict) -> dict[int, dict]:
    """Build 14 offline ridge (mixed prefill + decode): step ~ running mean / output tok/s (ridge.md's own method)."""
    r = cfg["t4_ridge"]
    out = {}
    for batch, key in r["keys"].items():
        row = jsonl_row(REPO / r["file"], key)
        out[int(batch)] = {"ms": row["eng_running_mean"] / row["output_tok_s"] * 1000, "running": row["eng_running_mean"],
                           "tok_s": row["output_tok_s"], "file": r["file"], "row": key}
    return out


def pcie_fit(cfg: dict) -> dict:
    return nccl_check.check(REPO / cfg["pcie_nccl_run"])["fit"]


def soft_roce_gbps(cfg: dict) -> tuple[float, list[float]]:
    d = json.loads((REPO / cfg["soft_roce"]["results"]).read_text())
    for k in cfg["soft_roce"]["path"]:
        d = d[k]
    reps = [r["parsed"]["bw_avg_gbps"] for r in d]
    return statistics.median(reps), reps


def link_set(full: dict) -> list[NamedLink]:
    """The three link models. ring busbw B and per-step alpha; N-dependence: 2(N-1) alpha + 2(N-1)/N * S / B."""
    cfg, hw, eff, alpha = full["scaleout"], full["hardware"], full["efficiency"], full["alpha_us"]
    f = pcie_fit(cfg)
    return [
        NamedLink("PCIe via host memory (2×T4, MEASURED fit)", Link(f["bytes_per_s"], f["t0_s"] / 2),
                  f"Build 7b nccl_check fit of {cfg['pcie_nccl_run']}: B = 1 GiB busbw {f['bytes_per_s'] / 1e9:.2f} GB/s, "
                  f"α = t0/2 = {f['t0_s'] / 2 * 1e6:.2f} µs"),
        NamedLink("NVLink 4 (H100)", Link(hw["nvlink_gbytes_per_dir"] * 1e9 * eff["nvlink"], alpha["nvlink"] * 1e-6),
                  f"S3/S4: {hw['nvlink_gbytes_per_dir']} GB/s per direction × {eff['nvlink']:.2f} (A2), α {alpha['nvlink']} µs (A4)"),
        NamedLink(f"{hw['nic_gbps']}G RoCE / IB per GPU", Link(hw["nic_gbps"] * 1e9 / 8 * eff["network"], alpha["network"] * 1e-6),
                  f"S1/S8: {hw['nic_gbps']} Gb/s line rate × {eff['network']:.2f} (A1) = "
                  f"{hw['nic_gbps'] / 8 * eff['network']:.0f} GB/s, α {alpha['network']} µs (A3)"),
    ]


# ---- per decode step, tensor parallel ---------------------------------------------------------------------------------


def tp_message_bytes(m: Model, batch: int, dtype_bytes: int) -> int:
    """One TP all-reduce of the decode activations: batch x hidden x dtype bytes (S17)."""
    return batch * m.hidden * dtype_bytes


def tp_messages_per_step(m: Model) -> int:
    return 2 * m.layers   # Megatron: 2 all-reduces per layer in the forward pass (S17); decode has no backward


def tp_wire_bytes_per_gpu(m: Model, tp: int, batch: int, dtype_bytes: int) -> float:
    return tp_messages_per_step(m) * ring_allreduce_bytes(tp, tp_message_bytes(m, batch, dtype_bytes))


def tp_comm_s(m: Model, tp: int, batch: int, dtype_bytes: int, link: Link, rate_fraction: float = 1.0) -> float:
    """Sum over the step's all-reduces of (2(N-1) alpha + ring busbw term); one ring link at rate_fraction slows the ring."""
    slow = Link(link.bytes_per_s * rate_fraction, link.alpha_s)
    return tp_messages_per_step(m) * ring_allreduce_time(tp, tp_message_bytes(m, batch, dtype_bytes), slow)


def share(comm: float, compute: float | None) -> float | None:
    return None if compute is None else comm / (compute + comm)


def kv_transfer_s(bytes_: float, link: Link) -> float:
    return p2p_time(bytes_, link)


# ---- Markdown -----------------------------------------------------------------------------------------------------------


def pct(x: float | None) -> str:
    return "—" if x is None else f"{x:.1%}"


def fms(s: float) -> str:
    return f"{s * 1e3:,.3f}" if s < 0.01 else f"{s * 1e3:,.2f}"


def h100_ms(cfg: dict, model: str, batch: int) -> float | None:
    v = ((cfg.get("h100_step_ms") or {}).get(model) or {}).get(batch)
    return float(v) if v not in (None, "") else None


def models_md(models: list[Model]) -> str:
    rows = [[m.name, f"`{m.revision}`", str(m.layers), f"{m.hidden:,}", str(m.heads), str(m.kv_heads),
             f"{m.head_dim} ({m.head_dim_source})"] for m in models]
    return table(["Model", "Revision", "num_hidden_layers", "hidden_size", "num_attention_heads",
                  "num_key_value_heads", "head_dim"], rows)


def links_md(links: list[NamedLink], roce: tuple[float, list[float]], cfg: dict) -> str:
    rows = [[l.name, f"{l.link.bytes_per_s / 1e9:,.2f}", f"{l.link.alpha_s * 1e6:.2f}", l.source] for l in links]
    rows.append(["Soft-RoCE, lab VMs (E3, MEASURED; KV transfer only)", f"{roce[0] / 8:,.4f}", "0 (not separated)",
                 f"E3 `ib_write_bw` 1 MiB, median of {roce[1]} Gbit/s = {roce[0]} Gbit/s ({cfg['soft_roce']['results']})"])
    return table(["Link", "B (GB/s per GPU, ring busbw)", "α (µs per ring step)", "Source"], rows)


def compute_md(t4: dict, ridge: dict) -> str:
    rows = []
    for b, v in sorted(t4.items()):
        rr = ridge.get(b)
        rows.append([str(b), f"{v['ms']:,.2f}", f"{v['how']}: `{v['field']}` = {v['raw']:g}" + (f", row `{v['row']}`" if v["row"] else ""),
                     f"`{v['file']}`", f"{rr['ms']:,.1f} (row `{rr['row']}`: {rr['running']:.1f} running ÷ {rr['tok_s']:,.1f} tok/s)" if rr else "—"])
    return table(["Batch", "T4 step ms (used)", "How", "File", "Build 14 ridge, mixed prefill+decode (cross-check)"], rows)


def bytes_md(models: list[Model], cfg: dict) -> str:
    d, rows = cfg["dtype_bytes"], []
    for m in models:
        for b in cfg["batch"]:
            s = tp_message_bytes(m, b, d)
            rows.append([m.name, str(b), f"{s:,}", str(tp_messages_per_step(m)), f"{tp_messages_per_step(m) * s / 1e6:,.3f}"]
                        + [f"{tp_wire_bytes_per_gpu(m, tp, b, d) / 1e6:,.3f}" for tp in cfg["tp"]])
    return table(["Model", "Batch", "Message B (batch × hidden × 2)", "All-reduces / step (2 × layers)",
                  "Message MB / step"] + [f"Wire MB / GPU / step, TP {tp}" for tp in cfg["tp"]], rows)


def comm_share_md(models: list[Model], links: list[NamedLink], t4: dict, cfg: dict) -> str:
    d, ks, rows = cfg["dtype_bytes"], cfg["sensitivity"], []
    measured = models[0].name
    for m in models:
        for l in links:
            for tp in cfg["tp"]:
                for b in cfg["batch"]:
                    c = tp_comm_s(m, tp, b, d, l.link)
                    comp = t4[b]["ms"] / 1e3 if m.name == measured and b in t4 else None
                    h = h100_ms(cfg, m.name, b)
                    rows.append([m.name, l.name, str(tp), str(b), fms(c),
                                 "—" if comp is None else f"{comp * 1e3:,.2f}", pct(share(c, comp))]
                                + [pct(share(c, comp / k if comp else None)) for k in ks]
                                + [PENDING if h is None else pct(share(c, h / 1e3)), fms(9 * c)])
    return table(["Model", "Link", "TP", "Batch", "Comm ms / step", "T4 compute ms (measured, TP 1)",
                  "**Comm share, T4 measured**"] + [f"share, T4 ÷ {k} (sensitivity, not a GPU claim)" for k in ks]
                 + ["Comm share, H100", "Compute ms for share ≤ 10 %"], rows)


def kv_md(models: list[Model], links: list[NamedLink], roce: tuple[float, list[float]], cfg: dict) -> str:
    d = cfg["dtype_bytes"]
    all_links = links + [NamedLink("Soft-RoCE lab (E3, MEASURED)", Link(roce[0] * 1e9 / 8, 0.0), "")]
    rows = []
    for m in models:
        per_tok = kv_bytes_per_token(m.layers, m.kv_heads, m.head_dim, d)
        for p in cfg["prompt_tokens"]:
            rows.append([m.name, f"{per_tok:,}", f"{p:,}", f"{per_tok * p / 1e6:,.2f}"]
                        + [fms(kv_transfer_s(per_tok * p, l.link)) for l in all_links])
    return table(["Model", "KV B / token", "Prompt tokens", "KV MB / prompt"] + [f"{l.name} (ms)" for l in all_links], rows)


def slow_link_md(models: list[Model], links: list[NamedLink], t4: dict, cfg: dict) -> str:
    d, f, rows = cfg["dtype_bytes"], cfg["slow_link_fraction"], []
    measured = models[0].name
    for m in models:
        for l in links:
            for tp in cfg["tp"]:
                for b in cfg["slow_link_batches"]:
                    c, cs = tp_comm_s(m, tp, b, d, l.link), tp_comm_s(m, tp, b, d, l.link, f)
                    comp = t4[b]["ms"] / 1e3 if m.name == measured and b in t4 else None
                    step = "—" if comp is None else f"{(comp + c) * 1e3:,.2f} → {(comp + cs) * 1e3:,.2f} ({(cs - c) / (comp + c):+.1%})"
                    rows.append([m.name, l.name, str(tp), str(b), fms(c), fms(cs), f"{cs / c - 1:+.1%}", step])
    return table(["Model", "Link", "TP", "Batch", "Comm ms, healthy", f"Comm ms, one link at {f:.0%}", "Comm change",
                  "T4 step ms (compute + comm), healthy → slow"], rows)


def render(full: dict) -> dict[str, str]:
    cfg = full["scaleout"]
    models = [load_model(m) for m in cfg["models"]]
    links = link_set(full)
    t4, ridge, roce = t4_step_ms(cfg), ridge_step_ms(cfg), soft_roce_gbps(cfg)
    return {"models": models_md(models), "links": links_md(links, roce, cfg), "compute": compute_md(t4, ridge),
            "bytes": bytes_md(models, cfg), "comm-share": comm_share_md(models, links, t4, cfg),
            "kv": kv_md(models, links, roce, cfg), "slow-link": slow_link_md(models, links, t4, cfg)}


def fill(doc: str, tables: dict[str, str]) -> str:
    def sub(m: re.Match) -> str:
        return f"{m.group(1)}\n{tables[m.group(2)]}\n{m.group(3)}"
    return re.sub(r"(<!-- scaleout:([a-z-]+) -->)\n.*?\n?(<!-- /scaleout -->)", sub, doc, flags=re.S)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    p.add_argument("--check", action="store_true", help="fail if scaleout.md is stale")
    a = p.parse_args(argv)
    doc = DOC.read_text()
    new = fill(doc, render(yaml.safe_load(a.config.read_text())))
    if a.check:
        if new != doc:
            print("fabric/design/scaleout.md tables are stale: run `python -m fabric.design.scaleout`", file=sys.stderr)
            return 1
        return 0
    DOC.write_text(new)
    print(f"wrote {DOC}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
