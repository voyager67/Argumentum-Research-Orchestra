import pytest

from argumentum.sandbox_worker import build_bwrap_command


def test_sandbox_refuses_execution_when_bwrap_is_missing(tmp_path, monkeypatch):
    code = tmp_path / "main.py"
    code.write_text("print('x')")
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setattr("argumentum.sandbox_worker.shutil.which", lambda _: None)
    with pytest.raises(RuntimeError, match="refusing unsafe execution"):
        build_bwrap_command(code, work)
