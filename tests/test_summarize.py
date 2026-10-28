import pytest

from news_agent.summarize import SummarizeError, summarize_topic


class FakeLlm:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def complete_json(self, *, system, prompt, schema):
        self.calls.append({"system": system, "prompt": prompt, "schema": schema})
        return self.payload


def run(payload, items, max_items=5):
    llm = FakeLlm(payload)
    entries = summarize_topic(llm, topic_title="AI", items=items, language="es", max_items=max_items)
    return entries, llm


def test_urls_come_from_items_not_from_the_model(make_items):
    payload = {
        "entries": [{"id": 1, "headline": "H", "context": "C", "why_interesting": "W", "url": "https://evil.test"}]
    }
    entries, _ = run(payload, make_items())
    assert entries[0].url == "https://official.example/1"
    assert entries[0].source == "Official Blog"


def test_invalid_and_duplicate_ids_are_ignored_and_max_is_enforced(make_items):
    base = {"headline": "H", "context": "C", "why_interesting": "W"}
    payload = {
        "entries": [{"id": 99, **base}, {"id": 0, **base}, {"id": 0, **base}, {"id": -1, **base}, {"id": 2, **base}]
    }
    entries, _ = run(payload, make_items(), max_items=1)
    assert [e.url for e in entries] == ["https://official.example/0"]


def test_no_items_means_no_llm_call():
    llm = FakeLlm({"entries": []})
    assert summarize_topic(llm, topic_title="AI", items=[], language="es", max_items=5) == []
    assert llm.calls == []


def test_prompt_contains_language_items_and_schema(make_items):
    _, llm = run({"entries": []}, make_items())
    call = llm.calls[0]
    assert "language: es" in call["system"]
    assert "<items>" in call["prompt"] and "[0] Title 0" in call["prompt"]
    assert call["schema"]["required"] == ["entries"]


def test_malformed_payload_raises(make_items):
    with pytest.raises(SummarizeError):
        run({"unexpected": True}, make_items())
