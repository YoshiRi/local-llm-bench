#!/usr/bin/env python3
"""HTTP transport and the truncation rule, shared by every suite.

Kept in one place so doceval and ctxeval cannot drift apart on what counts as a
truncated reply. Depends only on the standard library, so another suite can
load it by path without dragging in that suite's own modules.

The caller passes an argparse-style object carrying api, upstream, model,
temperature, max_tokens, timeout and (for the ollama api) num_ctx.
"""
import json
import sys
import time
import urllib.request


def post(url, body, headers, timeout):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", **headers})
    start = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        payload = json.loads(r.read().decode("utf-8"))
    return payload, time.monotonic() - start


TRUNCATION_REASONS = {"length", "max_tokens", "max_output_tokens"}


def was_truncated(usage, max_tokens):
    """True when the ceiling cut the reply off. A truncated result says nothing
    about the model, so it is reported apart from an ordinary failure."""
    reason = (usage.get("finish_reason") or "").lower()
    if reason in TRUNCATION_REASONS:
        return True
    out = usage.get("output")
    return isinstance(out, int) and isinstance(max_tokens, int) and out >= max_tokens


def ask(a, prompt):
    """Return (text, usage, seconds). Raises on transport failure."""
    base = a.upstream.rstrip("/")
    if a.api == "openai":
        body = {"model": a.model, "stream": False, "temperature": a.temperature,
                "max_tokens": a.max_tokens,
                "messages": [{"role": "user", "content": prompt}]}
        data, secs = post(f"{base}/v1/chat/completions", body, {}, a.timeout)
        choice = data["choices"][0]
        text = choice["message"]["content"]
        u = data.get("usage") or {}
        usage = {"input": u.get("prompt_tokens"), "output": u.get("completion_tokens"),
                 "finish_reason": choice.get("finish_reason")}
    elif a.api == "ollama":
        opts = {"temperature": a.temperature, "num_predict": a.max_tokens}
        if a.num_ctx:
            opts["num_ctx"] = a.num_ctx
        body = {"model": a.model, "stream": False, "options": opts,
                "messages": [{"role": "user", "content": prompt}]}
        data, secs = post(f"{base}/api/chat", body, {}, a.timeout)
        text = data["message"]["content"]
        usage = {"input": data.get("prompt_eval_count"), "output": data.get("eval_count"),
                 "finish_reason": data.get("done_reason")}
    elif a.api == "anthropic":
        body = {"model": a.model, "max_tokens": a.max_tokens,
                "temperature": a.temperature,
                "messages": [{"role": "user", "content": prompt}]}
        data, secs = post(f"{base}/v1/messages", body,
                          {"anthropic-version": "2023-06-01", "x-api-key": "local"},
                          a.timeout)
        text = "".join(b.get("text", "") for b in data.get("content", []))
        u = data.get("usage") or {}
        usage = {"input": u.get("input_tokens"), "output": u.get("output_tokens"),
                 "finish_reason": data.get("stop_reason")}
    else:
        sys.exit(f"unsupported api: {a.api}")
    usage["truncated"] = was_truncated(usage, a.max_tokens)
    return text, usage, secs
