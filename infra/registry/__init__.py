"""Prebaked experiment registry (plan §7 scope decision).

P0: the agent selects an env + trainer and chooses params; it does not author
novel simulation code. `experiment.py` exposes a fast in-process STUB (used by
DISPATCH_BACKEND=local) and a real prebaked trainer entrypoint (run in the Modal
image, which carries envpool/mujoco/minigrid/torch).
"""
