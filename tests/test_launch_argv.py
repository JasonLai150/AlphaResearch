"""launch._build_argv must invoke claude in streaming print mode so the relay
can tail assistant text. Pure argv assertion — no subprocess, no claude binary.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent" / "main-agent"))
import launch  # noqa: E402


def test_build_argv_uses_streaming_print_mode():
    argv = launch._build_argv("do the thing", "claude-sonnet-4-6")
    assert argv[0] == "claude"
    # Print mode with the prompt, the model, and streaming JSON deltas.
    assert "-p" in argv and "do the thing" in argv
    assert argv[argv.index("--model") + 1] == "claude-sonnet-4-6"
    assert "--output-format" in argv
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    assert "--verbose" in argv            # required with -p + stream-json
    assert "--include-partial-messages" in argv  # token-level deltas
    assert "--dangerously-skip-permissions" in argv
