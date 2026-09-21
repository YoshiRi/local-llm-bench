"""Persistent HTTP front for SemIf's MLX backend (stdlib only).

Loads the model once and serves typed decisions:
  GET  /health
  POST /decide          SemIf-native row: {id, state, question, options:[{id,description}]}
  POST /v1/systemone    Jev / open-jev "System One" contract:
                        {state, questions:{qid:{type: choice|noul|score, instructions, criteria}}}
                        choice: criteria = {option_id: description} or [option_id, ...]
                        noul:   yes/no question, criteria optional
                        score:  criteria = {"min": 1, "max": 5} (integer scale)

Run with SemIf's venv:
  semif/.venv/bin/python semif-server.py --port 8090 [--bits 4] [--host 127.0.0.1]
"""
import argparse
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, "semif/src")
from semif_phase1 import mlx_backend  # noqa: E402

MODEL = "Qwen/Qwen3.5-4B"
REVISION = "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a"
STATE = {}
LOCK = threading.Lock()


def decide(row):
    with LOCK:
        return mlx_backend.score(STATE["model"], STATE["tokenizer"], row, STATE["metadata"])


def systemone(body):
    state = body.get("state", "")
    if not isinstance(state, str):
        state = json.dumps(state, ensure_ascii=False)
    answers, usage = {}, {"input_tokens": 0, "output_tokens": 0}
    for qid, q in body.get("questions", {}).items():
        qtype = q.get("type", "choice")
        crit = q.get("criteria")
        if qtype == "noul":
            options = [{"id": "yes", "description": "はい（該当する）。"}, {"id": "no", "description": "いいえ（該当しない）。"}]
        elif qtype == "score":
            lo, hi = int((crit or {}).get("min", 1)), int((crit or {}).get("max", 5))
            options = [{"id": str(i), "description": f"{i}（{lo}が最低、{hi}が最高）"} for i in range(lo, hi + 1)]
        elif isinstance(crit, dict):
            options = [{"id": k, "description": str(v)} for k, v in crit.items()]
        else:
            options = [{"id": str(k), "description": str(k)} for k in (crit or [])]
        r = decide({"id": qid, "state": state, "question": q.get("instructions", ""), "options": options})
        probs = dict(zip(r["option_ids"], r["probabilities"]))
        best = max(probs, key=probs.get)
        ans = {"probabilities": probs, "confidence": probs[best], "forward_seconds": r["forward_seconds"]}
        if qtype == "noul":
            ans["noul"] = best == "yes"
        elif qtype == "score":
            ans["score"] = int(best)
            ans["expected_score"] = sum(int(k) * v for k, v in probs.items())
        else:
            ans["choice"] = best
        answers[qid] = ans
        usage["input_tokens"] += r["input_tokens"]
    return {"model": f"semif/{MODEL}@{REVISION[:8]}", "answers": answers, "usage": usage}


class H(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            return self._send(200, {"ok": True, "model": MODEL, "bits": STATE.get("bits")})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or b"{}"))
            t = time.perf_counter()
            if self.path == "/decide":
                out = decide(body)
            elif self.path == "/v1/systemone":
                out = systemone(body)
            else:
                return self._send(404, {"error": "not found"})
            out["wall_seconds"] = round(time.perf_counter() - t, 4)
            self._send(200, out)
        except Exception as e:  # surface as JSON, keep serving
            self._send(400, {"error": f"{type(e).__name__}: {e}"})

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--bits", type=int, default=4)
    a = ap.parse_args()
    t = time.perf_counter()
    model, tok, meta = mlx_backend.load_model(MODEL, REVISION, a.bits)
    STATE.update(model=model, tokenizer=tok, metadata=meta, bits=a.bits)
    print(f"loaded {MODEL} bits={a.bits} in {time.perf_counter() - t:.1f}s; serving http://{a.host}:{a.port}", flush=True)
    ThreadingHTTPServer((a.host, a.port), H).serve_forever()


if __name__ == "__main__":
    main()
