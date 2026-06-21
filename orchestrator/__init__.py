"""Orchestrator service: the FastAPI API (sessions + SSE) and the depth-0 worker.

Depth-0 `run_agent` runs here (Cloud Run); depth >= 1 runs in Modal. Both publish
to the same per-session Redis Stream, so the SSE endpoint is a pure tailer.
"""
