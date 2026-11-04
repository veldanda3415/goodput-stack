"""Unit tests for small parsers in benchmarks/kaggle/t4_notebook.py (local, no GPU)."""

from __future__ import annotations

from pathlib import Path

from benchmarks.kaggle import t4_notebook as nb

F3_SMI = Path(__file__).parents[1] / "results/t4/20261031-173838_followup/results/followup/logs/f3-nvidia-smi-both-up.txt"


def test_smi_process_lines_on_the_f3_raw_output():
    text = F3_SMI.read_text()
    procs = nb.smi_process_lines(text)
    assert len(procs) == 3                        # two EngineCores + the MPS server
    clients = nb.mps_clients(text)
    assert len(clients) == 2 and all("VLLM::EngineCore" in l and "M+C" in l for l in clients)


def test_smi_process_lines_plain_and_spaced_units():
    text = ("|    0   N/A  N/A            1234      C   python3                                  512MiB |\n"
            "|    0   N/A  N/A            99      G   Xorg                                  4 MiB |\n"
            "| GPU  Name   Persistence-M | Bus-Id  Disp.A | Volatile Uncorr. ECC |\n"
            "| N/A   45C    P0   27W /  70W |   1234MiB / 15360MiB |   0%   Default |\n")
    assert len(nb.smi_process_lines(text)) == 2
    assert nb.mps_clients(text) == []


def test_supported_graphics_clocks_and_backend():
    sup = ("    Supported Clocks\n        Memory                            : 5001 MHz\n"
           "            Graphics                      : 1590 MHz\n            Graphics                      : 1575 MHz\n"
           "        Memory                            : 405 MHz\n            Graphics                      : 1590 MHz\n")
    assert nb.supported_graphics_clocks(sup) == [1590, 1575]
    line = "(EngineCore pid=931) INFO 10-31 12:40:54 [cuda.py:526] Using TRITON_ATTN attention backend out of potential backends: ['TRITON_ATTN', 'FLEX_ATTENTION']."
    assert nb.default_backend(line) == "TRITON_ATTN"


def test_window_stats_counts_only_inside_the_window():
    recs = [{"t_send": 9.0, "token_t": [9.5, 10.5, 11.5], "ok": True, "status": 200, "usage": {"completion_tokens": 3}},
            {"t_send": 10.2, "token_t": [10.6, 10.7, 20.5], "status": 200, "cancelled_at_window_end": True},
            {"t_send": 12.0, "status": 500, "error": "boom"}]
    w = nb.window_stats(recs, 10.0, 20.0)
    assert w["output_tokens_in_window"] == 4                  # 10.5, 11.5, 10.6, 10.7
    assert w["output_tok_s"] == 0.4
    assert w["itl_ms_p50"] is not None and w["itl_ms_max"] == 1000.0   # 10.5->11.5 in, 9.5->10.5 and 10.7->20.5 out
    assert w["requests_sent_in_window"] == 2 and w["requests_cancelled_at_window_end"] == 1
    assert w["errors"] == 1 and w["requests_completed"] == 1
    assert round(w["ttft_ms_max"]) == 400                     # only the request sent at 10.2 (first token 10.6)


def test_timed_client_against_a_fake_stream(tmp_path):
    """timed_client runs ramp + window, then cancels in-flight requests; tokens of cancelled requests are kept."""
    import json as js
    import threading
    import time as tm
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = js.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            try:
                for _ in range(body["max_tokens"]):
                    self.wfile.write(b'data: {"choices":[{"text":"x","finish_reason":null}]}\n\n')
                    self.wfile.flush()
                    tm.sleep(0.02)
                self.wfile.write(b'data: {"choices":[],"usage":{"completion_tokens":%d}}\n\ndata: [DONE]\n\n' % body["max_tokens"])
            except (BrokenPipeError, ConnectionResetError):
                pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    class V:
        value = 0.0
    ready, go, t0v = threading.Event(), threading.Event(), V()
    c = {"api": "openai", "model": "m", "endpoint": "/v1/completions", "max_tokens": 30, "ignore_eos": True, "temperature": 0.0,
         "concurrency": 3, "start_jitter_s": 0.2, "timeout_s": 30, "ramp_s": 0.3, "window_s": 1.5}
    out = tmp_path / "c.json"
    th = threading.Thread(target=nb.timed_client, args=(f"http://127.0.0.1:{srv.server_address[1]}", c, ["p1", "p2"], ready, go, t0v, str(out)))
    th.start()
    assert ready.wait(10)
    t0v.value = tm.time() + 0.1
    go.set()
    th.join(20)
    srv.shutdown()
    res = js.loads(out.read_text())
    recs = res["records"]
    assert abs(res["t_end"] - res["t_load0"] - 1.8) < 1e-6
    assert any(r.get("ok") for r in recs) and any(r.get("cancelled_at_window_end") for r in recs)
    w = nb.window_stats(recs, res["t_load0"] + 0.3, res["t_end"])
    assert w["errors"] == 0 and w["output_tokens_in_window"] > 3 * 1.5 / 0.03   # 3 users at <= 1 token / 20 ms (+ overhead)
    assert max(t for r in recs for t in r["token_t"]) < res["t_end"] + 0.1
