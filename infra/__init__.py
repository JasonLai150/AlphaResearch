"""Infra layer (LOCKED per plan §2.5).

Everything Redis/GCS/Modal lives behind this package. The research-loop layer
(`agent/`) talks only to `infra.store` + `infra.dispatch` + `infra.schemas`,
never to Redis/GCS/Modal directly. That seam is what lets the loop be rewritten
without touching infra.
"""
