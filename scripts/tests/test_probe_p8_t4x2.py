"""Offline tests for scripts/probe_p8_t4x2.py (no GPU): stats, metric parsing, router formulas, token-load
reconstruction, and one condition end to end against a fake streaming engine (httpx.MockTransport)."""
import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import probe_p8_t4x2 as p8  # noqa: E402

REAL_SCRAPE = REPO / "benchmarks/results/t4/20261014-215653_baseline/results/baseline/logs/metrics-load.txt"


def test_pct_and_dist():
    v = [1.0, 2.0, 3.0, 4.0]
    d = p8.dist(v)
    assert d["n"] == 4 and d["p50"] == 2.5 and d["max"] == 4.0 and d["min"] == 1.0
    assert d["p95"] == pytest.approx(3.85)
    assert p8.dist([]) == {"n": 0}


def test_gaps():
    assert p8.gaps([0.0, 0.1, 0.35]) == pytest.approx([0.1, 0.25])
    assert p8.gaps([1.0]) == [] and p8.gaps([]) == []


def test_probe_order_balanced_and_seeded():
    o = p8.probe_order(12, seed=8)
    assert len(o) == 24 and o.count("L") == 12 and o.count("S") == 12
    assert all(sorted(o[i:i + 2]) == ["L", "S"] for i in range(0, 24, 2))
    assert o == p8.probe_order(12, seed=8) and o != p8.probe_order(12, seed=9)
    assert p8.probe_order(3, 1, ("L",)) == ["L", "L", "L"]


def test_parse_metrics_real_vllm_0310_scrape():
    m = p8.parse_metrics(REAL_SCRAPE.read_text())
    assert m["running"] == 16.0 and m["waiting"] == 0.0          # _by_reason lines are a different name
    assert m["kv"] == pytest.approx(0.029898509646155258)
    assert m["prompt_tokens"] == 9062.0 and m["generation_tokens"] == 4666.0
    assert m["ttft_count"] == 42.0 and m["itl_count"] == 4624.0


def test_counter_rate_and_window():
    s = [{"t": 0.0, "server": "L", "generation_tokens": 0}, {"t": 2.0, "server": "L", "generation_tokens": 100},
         {"t": 3.0, "server": "S", "generation_tokens": 7}]
    assert p8.counter_rate(p8.window(s, 0, 2, "L"), "generation_tokens") == 50.0
    assert p8.counter_rate(p8.window(s, 0, 9, "S"), "generation_tokens") is None


def test_router_stock_profile():
    # equal waiting -> queue 1/1; kv decides; prefix 0
    r = p8.router_scores({"L": {"waiting": 0, "kv": 0.04}, "S": {"waiting": 0, "kv": 0.005}})
    assert r["per_endpoint"]["L"]["total"] == pytest.approx(2 + 2 * 0.96)
    assert r["per_endpoint"]["S"]["total"] == pytest.approx(2 + 2 * 0.995)
    assert r["pick"] == "S" and r["margin"] == pytest.approx(0.07)
    # P8 sim shape: S has 1 waiting, kv 0 everywhere -> L
    r = p8.router_scores({"L": {"waiting": 0, "kv": 0.0}, "S": {"waiting": 1, "kv": 0.0}})
    assert r["pick"] == "L" and r["per_endpoint"]["S"]["scores"]["queue"] == 0.0
    assert p8.router_scores({"L": {"waiting": 0, "kv": 0.1}, "S": {"waiting": 0, "kv": 0.1}})["pick"] == "tie"


def test_router_token_profile_matches_p8_sim_scores():
    # GAPS.md P8: threshold 8192 -> long pod 0, short pod 0.890625 (= 1 - 896/8192)
    w = {"queue": 2.0, "kv": 2.0, "prefix": 3.0, "token": 4.0}
    r = p8.router_scores({"L": {"waiting": 0, "kv": 0}, "S": {"waiting": 1, "kv": 0}}, w, {"L": 9000, "S": 896})
    assert r["per_endpoint"]["L"]["scores"]["token"] == 0.0
    assert r["per_endpoint"]["S"]["scores"]["token"] == pytest.approx(0.890625)
    assert r["pick"] == "S"
    assert p8.router_scores({"L": {"waiting": 0, "kv": 0}, "S": {"waiting": 0, "kv": 0}}, w, {"L": 0, "S": 0})["pick"] == "tie"


def test_est_tokens_and_token_load():
    assert p8.est_tokens(8) == 3            # "user" (4 B) + 8 B = 12 B -> 3
    assert p8.est_tokens(9) == 4            # 13 B padded to 16
    bg = [{"server": "L", "t_send": 0.0, "t_first_chunk": 5.0, "t_end": 9.0, "est_tokens": 750, "prompt_tokens": 3020},
          {"server": "L", "t_send": 1.0, "t_first_chunk": 2.0, "t_end": 8.0, "est_tokens": 750, "prompt_tokens": 3020},
          {"server": "S", "t_send": 0.0, "t_first_chunk": None, "t_end": 1.0, "est_tokens": 60, "prompt_tokens": 220},
          {"server": "S", "t_send": 2.0, "t_first_chunk": None, "t_end": None, "est_tokens": 60, "prompt_tokens": 220}]
    assert p8.token_load_at(bg, "L", 3.0) == 750                       # second one already got its first chunk
    assert p8.token_load_at(bg, "L", 0.5, "prompt_tokens") == 3020
    assert p8.token_load_at(bg, "L", 6.0) == 0
    assert p8.token_load_at(bg, "S", 3.0) == 60                         # errored one (ended at 1.0) excluded


def test_bootstrap_median_diff():
    ci = p8.bootstrap_median_diff([1.0, 1.1, 1.2, 0.9], [0.1, 0.12, 0.11, 0.09])
    assert ci and 0.7 < ci[0] <= ci[1] < 1.2
    assert p8.bootstrap_median_diff([1.0], [0.1]) is None


def test_make_prompt_body_cuts_to_n_tokens():
    class Tok:   # 1 token per character pair, enough to check the cut
        def encode(self, s, add_special_tokens=False):
            return [s[i:i + 2] for i in range(0, len(s), 2)]

        def decode(self, ids):
            return "".join(ids)
    b = p8.make_prompt_body(Tok(), 10)
    assert len(Tok().encode(b)) == 10 and b.startswith("w0 w1")
    u1, u2 = p8.unique_prompt(b), p8.unique_prompt(b)
    assert u1 != u2 and u1.endswith(b)


class FakeEngine:
    """Streams `max_tokens` content chunks; /metrics reports its in-flight count as running."""

    def __init__(self, ttft: float, itl: float):
        self.ttft, self.itl, self.inflight, self.prompt_tokens, self.gen = ttft, itl, 0, 0, 0

    async def stream(self, body):
        self.inflight += 1
        try:
            await asyncio.sleep(self.ttft)
            yield b'data: {"choices":[{"delta":{"role":"assistant","content":""}}]}\n\n'
            for i in range(body["max_tokens"]):
                if i:
                    await asyncio.sleep(self.itl)
                self.gen += 1
                yield f'data: {{"choices":[{{"delta":{{"content":"t{i}"}}}}]}}\n\n'.encode()
            pt = len(body["messages"][0]["content"].split())
            self.prompt_tokens += pt
            yield ('data: {"choices":[],"usage":{"prompt_tokens":%d,"completion_tokens":%d}}\n\n'
                   % (pt, body["max_tokens"])).encode()
            yield b"data: [DONE]\n\n"
        finally:
            self.inflight -= 1

    def metrics(self) -> str:
        return (f'vllm:num_requests_running{{engine="0"}} {float(self.inflight)}\n'
                f'vllm:num_requests_waiting{{engine="0"}} 0.0\n'
                f'vllm:kv_cache_usage_perc{{engine="0"}} {0.01 * self.inflight}\n'
                f'vllm:prompt_tokens_total{{engine="0"}} {float(self.prompt_tokens)}\n'
                f'vllm:generation_tokens_total{{engine="0"}} {float(self.gen)}\n')


def test_run_condition_end_to_end(tmp_path):
    engines = {8000: FakeEngine(0.05, 0.002), 8001: FakeEngine(0.01, 0.002)}

    def handler(req: httpx.Request):
        e = engines[req.url.port]
        if req.url.path == "/metrics":
            return httpx.Response(200, text=e.metrics())
        return httpx.Response(200, content=e.stream(json.loads(req.content)))

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            run = p8.Run({"L": "http://x:8000", "S": "http://x:8001"}, "m", tmp_path, {5: "a b c d e", 2: "a b"})
            stop = asyncio.Event()
            samp = asyncio.create_task(run.sampler(c, stop, 0.2))
            cond = {"name": "main", "background": {"L": (2, 5), "S": (3, 2)}, "bg_max_tokens": 4, "n": 3, "seed": 1,
                    "hold_s": 0.3, "min_gap_s": 0.05, "gate_timeout_s": 5, "probe_tokens": 2, "probe_max_tokens": 6}
            w = await p8.run_condition(run, c, cond)
            stop.set()
            await samp
            run.close()
            return w

    w = asyncio.run(go())
    assert w["probes_sent"] == 6 and w["targets"] == {"L": 2, "S": 3}
    probes = p8.read_jsonl(tmp_path / "probes.jsonl")
    assert [p["server"] for p in probes].count("L") == 3
    for p in probes:
        assert p["gate_ok"] and p["completion_tokens"] == 6 and len(p["itl_s"]) == 5
        assert p["pre_metrics"]["L"]["running"] == 2 and p["pre_metrics"]["S"]["running"] == 3
    bg = p8.read_jsonl(tmp_path / "background.jsonl")
    assert bg and all(b["t_first_chunk"] <= b["t_first_content"] <= b["t_end"] for b in bg)
    samples = p8.read_jsonl(tmp_path / "metrics_1hz.jsonl")
    s = p8.summarize_condition(w, probes, bg, samples, {})
    assert s["servers"]["L"]["ttft_s"]["n"] == 3 and s["headline"]["gap_s"] > 0.02
    rt = p8.router_table(probes, bg, "main")
    assert rt["n"] == 6 and sum(rt["stock_picks"].values()) == 6
