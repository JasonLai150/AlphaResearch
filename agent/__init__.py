"""Research-loop layer (SWAPPABLE per plan §2.5).

The self-similar agent runtime: one `run_agent(job_id)` runs at every depth.
Talks to infra only through `infra.store` + `infra.dispatch`.
"""
