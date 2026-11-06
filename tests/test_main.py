import runpy

import pytest

from news_agent import cli


def test_python_m_entry_point_exits_with_main_status(monkeypatch):
    monkeypatch.setattr(cli, "main", lambda *a, **kw: 7)
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("news_agent.__main__", run_name="__main__")
    assert exc.value.code == 7
