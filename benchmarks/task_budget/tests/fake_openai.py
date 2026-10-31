"""Tiny fake OpenAI-compatible streaming server (stdlib only) for the task_budget tests; mimics vLLM 0.31.0 usage chunks."""
import json, sys, threading, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

STATE = {"running": 0, "gen": 0, "prompt": 0}
LOCK = threading.Lock()


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path == "/health":
            return self._json({})
        if self.path == "/metrics":
            t = (f"# TYPE vllm:num_requests_running gauge\nvllm:num_requests_running{{model_name=\"m\"}} {STATE['running']}\n"
                 f"vllm:num_requests_waiting{{model_name=\"m\"}} 0\nvllm:kv_cache_usage_perc{{model_name=\"m\"}} 0.1\n"
                 f"vllm:generation_tokens_total{{model_name=\"m\"}} {STATE['gen']}\nvllm:prompt_tokens_total{{model_name=\"m\"}} {STATE['prompt']}\n"
                 f"vllm:num_preemptions_total{{model_name=\"m\"}} 0\n").encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(t)))
            self.end_headers()
            self.wfile.write(t)
            return
        self._json({}, 404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/tokenize":
            text = body.get("prompt") or ""
            return self._json({"count": len(text.split()), "tokens": []})
        chat = self.path == "/v1/chat/completions"
        prompt = " ".join(m["content"] for m in body["messages"]) if chat else body["prompt"]
        n_prompt = len(prompt.split())
        reply = STATE.get("reply_fn", lambda p, mt: ["tok"] * mt)(prompt, body["max_tokens"])
        if not body.get("stream"):
            text = " ".join(reply)
            msg = {"message": {"role": "assistant", "content": text}} if chat else {"text": text}
            return self._json({"choices": [{"index": 0, "finish_reason": "stop", **msg}],
                               "usage": {"prompt_tokens": n_prompt, "completion_tokens": len(reply), "total_tokens": n_prompt + len(reply)}})
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        def send(obj):
            data = ("data: " + (obj if isinstance(obj, str) else json.dumps(obj)) + "\n\n").encode()
            self.wfile.write(f"{len(data):x}\r\n".encode() + data + b"\r\n")
            self.wfile.flush()
        with LOCK:
            STATE["running"] += 1
            STATE["prompt"] += n_prompt
        sent = 0
        try:
            time.sleep(0.02)
            for i, piece in enumerate(reply):
                last = i == len(reply) - 1
                fr = ("length" if len(reply) >= body["max_tokens"] else "stop") if last else None
                ch = {"index": 0, "delta": {"content": piece + " "}, "finish_reason": fr} if chat else {"index": 0, "text": piece + " ", "finish_reason": fr}
                sent += 1
                chunk = {"choices": [ch]}
                if (body.get("stream_options") or {}).get("continuous_usage_stats"):
                    chunk["usage"] = {"prompt_tokens": n_prompt, "completion_tokens": sent, "total_tokens": n_prompt + sent}
                send(chunk)
                with LOCK:
                    STATE["gen"] += 1
                time.sleep(STATE.get("token_sleep_s", 0.005))
            if (body.get("stream_options") or {}).get("include_usage"):
                send({"choices": [], "usage": {"prompt_tokens": n_prompt, "completion_tokens": sent, "total_tokens": n_prompt + sent}})
            send("[DONE]")
            self.wfile.write(b"0\r\n\r\n")
        except (BrokenPipeError, ConnectionResetError):
            STATE["aborted"] = STATE.get("aborted", 0) + 1
        finally:
            with LOCK:
                STATE["running"] -= 1


def serve(port):
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


if __name__ == "__main__":
    serve(int(sys.argv[1]))
    while True:
        time.sleep(3600)
