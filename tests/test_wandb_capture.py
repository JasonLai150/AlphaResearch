"""Sub-agent wandb run identity + Browserbase smart-capture tool.

Asserts the determinism that keeps N concurrent sub-agents from screenshotting each
other's runs: the run URL is a pure function of the job id. The browser/agent layers
are monkeypatched — no network."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "agent" / "sub-agent" / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import capture_wandb  # noqa: E402
import wandb_run  # noqa: E402


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("ALPHA_JOB_ID", "j_abc123")
    monkeypatch.setenv("ALPHA_SESSION_ID", "s_xyz")
    monkeypatch.setenv("WANDB_ENTITY", "neosigma")
    monkeypatch.setenv("ALPHA_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("ALPHA_DISPATCH_DIR", str(tmp_path / "disp"))
    monkeypatch.delenv("WANDB_PROJECT", raising=False)
    monkeypatch.delenv("WANDB_RUN_URL", raising=False)
    (tmp_path / "ws").mkdir()
    return tmp_path


# ---- deterministic run identity (the multi-sub-agent correctness guarantee) ----

def test_run_identity_deterministic(env):
    ident = wandb_run.run_identity()
    assert ident["run_id"] == "j_abc123"
    assert ident["project"] == "alpha-s_xyz"
    assert ident["url"] == "https://wandb.ai/neosigma/alpha-s_xyz/runs/j_abc123"


def test_run_identity_unique_per_job(env, monkeypatch):
    u1 = wandb_run.run_identity()["url"]
    monkeypatch.setenv("ALPHA_JOB_ID", "j_def456")
    u2 = wandb_run.run_identity()["url"]
    assert u1 != u2
    assert u1.endswith("/runs/j_abc123") and u2.endswith("/runs/j_def456")


def test_run_identity_no_entity_no_url(env, monkeypatch):
    monkeypatch.delenv("WANDB_ENTITY", raising=False)
    monkeypatch.delenv("ALPHA_WANDB_ENTITY", raising=False)
    assert wandb_run.run_identity()["url"] == ""


def test_init_wandb_pins_id_and_writes_url(env, monkeypatch):
    captured = {}
    fake_run = types.SimpleNamespace(url="https://wandb.ai/neosigma/alpha-s_xyz/runs/j_abc123")
    fake_wandb = types.ModuleType("wandb")
    fake_wandb.init = lambda **kw: (captured.update(kw) or fake_run)
    monkeypatch.setitem(sys.modules, "wandb", fake_wandb)

    run = wandb_run.init_wandb(config={"lr": 1e-3})
    assert run is fake_run
    assert captured["id"] == "j_abc123"          # pinned to job id -> deterministic URL
    assert captured["entity"] == "neosigma"
    assert captured["project"] == "alpha-s_xyz"
    assert captured["config"] == {"lr": 1e-3}
    assert wandb_run.run_url_path().read_text().strip() == fake_run.url


# ---- URL resolution precedence (cli > env > trainer file > convention) ----

def test_resolve_run_url_precedence(env, monkeypatch):
    assert capture_wandb.resolve_run_url("http://explicit") == "http://explicit"

    monkeypatch.setenv("WANDB_RUN_URL", "http://envurl")
    assert capture_wandb.resolve_run_url(None) == "http://envurl"
    monkeypatch.delenv("WANDB_RUN_URL")

    wandb_run.run_url_path().write_text("http://fileurl\n")
    assert capture_wandb.resolve_run_url(None) == "http://fileurl"

    wandb_run.run_url_path().unlink()
    assert capture_wandb.resolve_run_url(None).endswith("/runs/j_abc123")


def test_artifacts_dir(env):
    d = capture_wandb.artifacts_dir()
    assert d.name == "j_abc123" and d.parent.name == "artifacts" and d.exists()


# ---- main() orchestration (browser + smart agent mocked) ----

def test_main_writes_png_record_and_summary(env, monkeypatch, capsys):
    monkeypatch.setenv("BROWSERBASE_API_KEY", "k")
    monkeypatch.setenv("BROWSERBASE_CONTEXT_ID", "ctx")

    def fake_shot(api, ctx, url, out, wait_ms):
        Path(out).write_bytes(b"PNGDATA")
        return url  # landed == run url -> logged in

    monkeypatch.setattr(capture_wandb, "_playwright_screenshot", fake_shot)
    monkeypatch.setattr(capture_wandb, "_stagehand_analyze",
                        lambda *a, **k: {"metrics": {"final_metric": "0.82"}})

    rc = capture_wandb.main([])
    assert rc == 0
    rec = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert rec["run_url"].endswith("/runs/j_abc123")
    assert rec["logged_in"] is True
    png = capture_wandb.artifacts_dir() / "wandb_run.png"
    assert png.exists() and png.read_bytes() == b"PNGDATA"
    assert (capture_wandb.artifacts_dir() / "wandb_summary.json").exists()


def test_main_login_redirect_exits_4(env, monkeypatch):
    monkeypatch.setenv("BROWSERBASE_API_KEY", "k")
    monkeypatch.setenv("BROWSERBASE_CONTEXT_ID", "ctx")
    monkeypatch.setattr(capture_wandb, "_playwright_screenshot",
                        lambda *a, **k: "https://wandb.ai/login")
    rc = capture_wandb.main(["--no-smart"])
    assert rc == 4


def test_main_no_creds_exits_3(env, monkeypatch):
    monkeypatch.delenv("BROWSERBASE_API_KEY", raising=False)
    monkeypatch.delenv("BROWSERBASE_CONTEXT_ID", raising=False)
    assert capture_wandb.main([]) == 3


def test_main_no_smart_skips_stagehand(env, monkeypatch):
    monkeypatch.setenv("BROWSERBASE_API_KEY", "k")
    monkeypatch.setenv("BROWSERBASE_CONTEXT_ID", "ctx")
    monkeypatch.setattr(capture_wandb, "_playwright_screenshot",
                        lambda api, ctx, url, out, wait_ms: (Path(out).write_bytes(b"P"), url)[1])

    def _boom(*a, **k):
        raise AssertionError("stagehand must not run with --no-smart")

    monkeypatch.setattr(capture_wandb, "_stagehand_analyze", _boom)
    assert capture_wandb.main(["--no-smart"]) == 0
