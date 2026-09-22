"""Tiny TCP forwarder (stdlib only): expose a 127.0.0.1-only service on another interface.

  python3 tcp-proxy.py --listen 100.122.92.105:3080 --target 127.0.0.1:3081

Used to put dsh web (which refuses to bind anywhere but 127.0.0.1) on the
Tailscale IP. Plain TCP, so HTTP passes through untouched (Host header kept),
which is what dsh's --trusted-host fence needs.
"""
import argparse
import asyncio


async def pump(r, w):
    try:
        while data := await r.read(65536):
            w.write(data)
            await w.drain()
    except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
        pass
    finally:
        try:
            w.close()
        except Exception:
            pass


async def handle(target_host, target_port, cr, cw):
    try:
        tr, tw = await asyncio.open_connection(target_host, target_port)
    except OSError:
        cw.close()
        return
    await asyncio.gather(pump(cr, tw), pump(tr, cw))


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen", required=True)
    ap.add_argument("--target", required=True)
    a = ap.parse_args()
    lh, lp = a.listen.rsplit(":", 1)
    th, tp = a.target.rsplit(":", 1)
    server = await asyncio.start_server(lambda r, w: handle(th, int(tp), r, w), lh, int(lp))
    print(f"proxy {lh}:{lp} -> {th}:{tp}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
