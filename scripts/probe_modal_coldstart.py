#!/usr/bin/env python3
# ruff: noqa: E501  — throwaway diagnostic; usage examples + result lines read better unwrapped.
"""TEMP probe — measure whether sub-agent cold-start latency drops to ~0 once the
Modal container is warm / restored from snapshot. Safe to delete after use.

It defines a throwaway Modal app whose function mirrors `sub_agent`'s resourcing
(same image + cpu/memory/enable_memory_snapshot/scaledown_window) but does trivial
work, so the call latency reflects container start, not the agent. It then calls it
repeatedly and prints the per-call wall-clock: the FIRST call pays cold start (boot +
snapshot create); later calls reuse the warm container (or restore a snapshot) and
should drop toward network-latency (~0s of cold start).

Run from the repo root:
    uv run modal run scripts/probe_modal_coldstart.py                 # 6 rapid calls (warm-reuse demo)
    uv run modal run scripts/probe_modal_coldstart.py --n 4 --spread 330   # wait > scaledown_window
                                                                       #   between calls to force NEW
                                                                       #   containers (tests snapshot restore)
    PROBE_LIGHT=1 uv run modal run scripts/probe_modal_coldstart.py    # tiny image (Modal machinery only,
                                                                       #   skips building the heavy sub image)

Notes:
- The rapid mode shows WARM REUSE going to ~0 (same container, scaledown_window keeps
  it alive). To isolate SNAPSHOT-restore cold start, use --spread > 300 so the container
  scales to 0 between calls and each call boots a fresh (snapshot-restored) container.
- First-ever run may build the sub-agent image (minutes); subsequent runs reuse the cache.
"""
from __future__ import annotations

import os
import time
import uuid

import modal

# Mirror the sub_agent image unless PROBE_LIGHT=1 (then a tiny image to test only the
# warm/snapshot machinery without building the heavy RL image).
if os.environ.get("PROBE_LIGHT") == "1":
    _image = modal.Image.debian_slim(python_version="3.11")
else:
    _image = modal.Image.from_dockerfile(
        "deploy/sub-agent.Dockerfile", context_dir=".", force_build=False,
    ).entrypoint([])

app = modal.App("coldstart-probe")

# Set once when the container PROCESS starts. A reused warm container reports a growing
# age + stable boot_id; a freshly booted/restored one reports a tiny age.
_BOOT = time.monotonic()
_BOOT_ID = uuid.uuid4().hex[:8]


@app.function(
    image=_image,
    cpu=8.0,
    memory=8192,
    enable_memory_snapshot=True,
    scaledown_window=300,
    timeout=120,
)
def probe() -> dict:
    return {"container_age_s": round(time.monotonic() - _BOOT, 3),
            "boot_id": _BOOT_ID, "pid": os.getpid()}


@app.local_entrypoint()
def main(n: int = 6, spread: float = 2.0):
    print(f"== cold-start probe: {n} calls, {spread}s between "
          f"({'LIGHT image' if os.environ.get('PROBE_LIGHT') == '1' else 'sub-agent image'}) ==")
    walls, seen_boots = [], {}
    for i in range(int(n)):
        t0 = time.monotonic()
        r = probe.remote()
        dt = time.monotonic() - t0
        walls.append(dt)
        reused = r["boot_id"] in seen_boots
        seen_boots[r["boot_id"]] = seen_boots.get(r["boot_id"], 0) + 1
        tag = "WARM-REUSE" if reused else ("cold/new container" if i else "FIRST (cold + snapshot create)")
        print(f"  call {i}: wall={dt:6.2f}s  container_age={r['container_age_s']:6.2f}s  "
              f"boot={r['boot_id']}  [{tag}]")
        if i < int(n) - 1:
            time.sleep(float(spread))

    first, rest = walls[0], walls[1:]
    print("\n== summary ==")
    print(f"  first call (cold)      : {first:.2f}s")
    if rest:
        print(f"  subsequent calls       : min={min(rest):.2f}s  max={max(rest):.2f}s  "
              f"avg={sum(rest)/len(rest):.2f}s")
        print(f"  cold-start eliminated  : {first - min(rest):.2f}s faster once warm/restored "
              f"({'~0 cold start ✅' if min(rest) < 1.0 else 'still >1s — check snapshot/logs'})")
    print(f"  distinct containers used: {len(seen_boots)}  (1 ⇒ pure warm reuse; >1 ⇒ saw fresh boots)")
