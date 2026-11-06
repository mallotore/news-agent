import json
import subprocess

import pytest

from news_agent import llm as llm_module
from news_agent.llm import ClaudeCli, LlmError

SCHEMA = {"type": "object", "properties": {"entries": {"type": "array"}}}


def completed(stdout, returncode=0, stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


@pytest.fixture
def fake_run(monkeypatch):
    """Patch subprocess.run and the executable lookup; record how the CLI is invoked."""
    calls = []
    result = {"value": completed(json.dumps({"is_error": False, "structured_output": {"entries": []}}))}

    def run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return result["value"]

    monkeypatch.setattr(llm_module.subprocess, "run", run)
    monkeypatch.setattr(llm_module.shutil, "which", lambda name: f"/usr/bin/{name}")
    return calls, result


def test_command_is_stateless_toolless_and_uses_stdin(fake_run, monkeypatch):
    calls, _ = fake_run
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-leak")
    out = ClaudeCli(model="haiku").complete_json(system="SYS", prompt="PROMPT", schema=SCHEMA)

    cmd, kwargs = calls[0]
    assert out == {"entries": []}
    assert cmd[:2] == ["/usr/bin/claude", "-p"]
    assert cmd[cmd.index("--model") + 1] == "haiku"
    assert cmd[cmd.index("--tools") + 1] == ""
    assert cmd[cmd.index("--system-prompt") + 1] == "SYS"
    assert json.loads(cmd[cmd.index("--json-schema") + 1]) == SCHEMA
    assert "--no-session-persistence" in cmd
    assert kwargs["input"] == "PROMPT"
    assert "ANTHROPIC_API_KEY" not in kwargs["env"]  # must bill the subscription, not the API


def test_falls_back_to_json_in_result_text(fake_run):
    _, result = fake_run
    result["value"] = completed(json.dumps({"is_error": False, "result": '```json\n{"entries": [1]}\n```'}))
    assert ClaudeCli(model="haiku").complete_json(system="s", prompt="p", schema=SCHEMA) == {"entries": [1]}


def test_accepts_event_list_output(fake_run):
    _, result = fake_run
    events = [{"type": "system"}, {"type": "result", "is_error": False, "structured_output": {"entries": [2]}}]
    result["value"] = completed(json.dumps(events))
    assert ClaudeCli(model="haiku").complete_json(system="s", prompt="p", schema=SCHEMA) == {"entries": [2]}


def test_timeout_raises_llm_error(monkeypatch):
    def run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    monkeypatch.setattr(llm_module.subprocess, "run", run)
    monkeypatch.setattr(llm_module.shutil, "which", lambda name: name)
    with pytest.raises(LlmError, match="timed out"):
        ClaudeCli(model="haiku", timeout=1).complete_json(system="s", prompt="p", schema=SCHEMA)


@pytest.mark.parametrize(
    "value",
    [
        completed("", returncode=1, stderr="not logged in"),
        completed("not json"),
        completed(json.dumps({"is_error": True, "result": "rate limited"})),
        completed(json.dumps({"is_error": False, "result": "just prose"})),
    ],
)
def test_errors_raise_llm_error(fake_run, value):
    _, result = fake_run
    result["value"] = value
    with pytest.raises(LlmError):
        ClaudeCli(model="haiku").complete_json(system="s", prompt="p", schema=SCHEMA)


def test_missing_cli(monkeypatch):
    monkeypatch.setattr(llm_module.shutil, "which", lambda name: None)
    with pytest.raises(LlmError, match="not found"):
        ClaudeCli(model="haiku").complete_json(system="s", prompt="p", schema=SCHEMA)


def test_failed_call_is_retried_once(fake_run, monkeypatch):
    calls, _ = fake_run
    good = completed(json.dumps({"is_error": False, "structured_output": {"entries": [1]}}))
    outcomes = [completed("", returncode=1, stderr="flaky"), good]
    monkeypatch.setattr(llm_module.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or outcomes.pop(0))
    assert ClaudeCli(model="haiku").complete_json(system="s", prompt="p", schema=SCHEMA) == {"entries": [1]}
    assert len(calls) == 2


def test_persistent_failure_gives_up_after_one_retry(fake_run):
    calls, result = fake_run
    result["value"] = completed("not json")
    with pytest.raises(LlmError):
        ClaudeCli(model="haiku").complete_json(system="s", prompt="p", schema=SCHEMA)
    assert len(calls) == 2


def test_timeout_is_not_retried(monkeypatch):
    attempts = []

    def run(cmd, **kwargs):
        attempts.append(cmd)
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    monkeypatch.setattr(llm_module.subprocess, "run", run)
    monkeypatch.setattr(llm_module.shutil, "which", lambda name: name)
    with pytest.raises(LlmError, match="timed out"):
        ClaudeCli(model="haiku", timeout=1).complete_json(system="s", prompt="p", schema=SCHEMA)
    assert len(attempts) == 1


def test_event_list_without_result_event_is_an_error(fake_run):
    _, result = fake_run
    result["value"] = completed(json.dumps([{"type": "system"}]))
    with pytest.raises(LlmError, match="Unexpected claude output format"):
        ClaudeCli("haiku").complete_json(system="s", prompt="p", schema=SCHEMA)
