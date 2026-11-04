"""LLM backend: runs the local Claude Code CLI in headless mode (`claude -p`).

It uses whatever account the CLI is logged in with (e.g. a Claude Pro subscription),
so no API key or API credits are needed.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from typing import Any

# If these are set, Claude Code would bill the API instead of the subscription.
_STRIPPED_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
RETRY_DELAY = 2.0  # seconds before the single retry of a failed call
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$")


class LlmError(Exception):
    """Raised when the Claude CLI is missing, fails, or returns unusable output."""


class LlmTimeout(LlmError):
    """The CLI exceeded its time limit; not retried, since a retry could take just as long."""


class ClaudeCli:
    def __init__(self, model: str, executable: str = "claude", timeout: int = 300) -> None:
        self.model = model
        self.executable = executable
        self.timeout = timeout

    def complete_json(self, *, system: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        """Run one stateless, tool-less request and return the JSON object the model produced.

        A failed exit or unusable output is retried once; a missing CLI or a timeout is not.
        """
        path = shutil.which(self.executable)
        if path is None:
            raise LlmError(f"'{self.executable}' not found. Install Claude Code and run `claude` once to log in.")
        try:
            return self._run(path, system, prompt, schema)
        except LlmTimeout:
            raise
        except LlmError:
            time.sleep(RETRY_DELAY)
            return self._run(path, system, prompt, schema)

    def _run(self, path: str, system: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:

        cmd = [
            path,
            "-p",
            "--model",
            self.model,
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(schema),
            "--system-prompt",
            system,
            "--tools",
            "",  # pure text task: no file, shell or web access
            "--disable-slash-commands",
            "--strict-mcp-config",  # no MCP servers
            "--no-session-persistence",
        ]
        env = {k: v for k, v in os.environ.items() if k not in _STRIPPED_ENV}
        try:
            proc = subprocess.run(
                cmd,
                input=prompt,  # via stdin: no argument-length limits, no shell involved
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=self.timeout,
                cwd=tempfile.gettempdir(),  # avoid picking up a project CLAUDE.md
                env=env,
            )
        except subprocess.TimeoutExpired:
            raise LlmTimeout(f"claude timed out after {self.timeout}s") from None

        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()[:500]
            raise LlmError(f"claude exited with code {proc.returncode}: {detail}")
        return _parse_output(proc.stdout)


def _parse_output(stdout: str) -> dict[str, Any]:
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError:
        raise LlmError(f"Unexpected claude output: {stdout[:200]!r}") from None

    if isinstance(envelope, list):  # some versions emit a list of events
        envelope = next((e for e in reversed(envelope) if isinstance(e, dict) and e.get("type") == "result"), None)
    if not isinstance(envelope, dict):
        raise LlmError("Unexpected claude output format")
    if envelope.get("is_error"):
        raise LlmError(f"claude reported an error: {str(envelope.get('result'))[:500]}")

    structured = envelope.get("structured_output")
    if isinstance(structured, dict):
        return structured

    text = envelope.get("result")  # fallback: the model answered with JSON as plain text
    if isinstance(text, str):
        try:
            parsed = json.loads(_FENCE_RE.sub("", text.strip()))
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            return parsed
    raise LlmError("The model did not return the expected JSON")
