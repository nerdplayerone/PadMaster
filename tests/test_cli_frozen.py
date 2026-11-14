import builtins
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from padlab import cli  # noqa: E402
import padlab.logger  # noqa: E402


def test_frozen_exe_without_console_input_does_not_crash(monkeypatch, tmp_path):
    """Regression: the .exe asked 'Press Enter' and crashed with EOFError when stdin was closed."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(padlab.logger, "run", lambda *a, **k: str(tmp_path / "x.csv.gz"))
    monkeypatch.setattr(cli, "make_report", lambda *a, **k: "x_report.html")

    def no_input(*a):
        raise EOFError

    monkeypatch.setattr(builtins, "input", no_input)
    assert cli.main(["log", "--no-open"]) == 0
