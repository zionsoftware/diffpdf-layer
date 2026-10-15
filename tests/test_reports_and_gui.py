import csv
import io
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from pdf_layer_compare.comparator import compare_files
from pdf_layer_compare.model import Report, Result, Status
from pdf_layer_compare.report import from_json, save_report, to_csv, to_json, to_text

ROOT = Path(__file__).resolve().parents[1]


def test_report_roundtrip_and_exports(make_pdf, tmp_path):
    report = compare_files([make_pdf(), make_pdf(text="Changed")])
    assert from_json(to_json(report)) == report
    assert "不一致" in to_text(report)
    assert list(csv.reader(io.StringIO(to_csv(report))))[0][0] == "左ファイル"
    for suffix in (".txt", ".csv", ".json"):
        path = tmp_path / ("report" + suffix)
        save_report(report, path)
        assert "不一致" in path.read_text(encoding="utf-8-sig")


@pytest.mark.parametrize("value", ["=evil", "+evil", "-evil", "@evil", "   =evil"])
def test_csv_formula_escape(value):
    report = Report([value, "b"], [Result(value, "b", value, Status.DIFFERENT, value)], configuration_ok=True)
    rows = list(csv.reader(io.StringIO(to_csv(report))))
    assert rows[-1][0].startswith("'")
    assert rows[-1][-1].startswith("'")


def test_source_overwrite_prohibited(make_pdf):
    a = make_pdf()
    before = a.read_bytes()
    with pytest.raises(ValueError):
        save_report(compare_files([a, a]), a)
    assert a.read_bytes() == before


def test_hardlink_overwrite_prohibited(make_pdf, tmp_path):
    a = make_pdf()
    alias = tmp_path / "report.txt"
    try:
        os.link(a, alias)
    except OSError as exc:
        pytest.skip(f"ハードリンク作成不可: {exc}")
    with pytest.raises(ValueError):
        save_report(compare_files([a, a]), alias)


@pytest.mark.parametrize("changed, code", [(False, 0), (True, 1)])
def test_cli(make_pdf, changed, code):
    a, b = make_pdf(), make_pdf(text="Changed" if changed else "Base")
    run = subprocess.run([sys.executable, str(ROOT / "main.py"), "--json", str(a), str(b)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert run.returncode == code, run.stderr
    assert from_json(run.stdout).status == (Status.DIFFERENT if changed else Status.MATCH)


def test_cli_error_exit():
    run = subprocess.run([sys.executable, str(ROOT / "main.py"), "--json"], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert run.returncode == 2
    assert from_json(run.stdout).errors


@pytest.fixture
def gui():
    import tkinter as tk
    from pdf_layer_compare.gui import Application
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk の画面セッションが利用できません: {exc}")
    root.withdraw()
    app = Application(root)
    yield root, app
    if not app.closed:
        app.close()


def test_gui_subprocess_and_details(make_pdf, gui):
    root, app = gui
    app.add_files([make_pdf(), make_pdf(text="Changed")])
    app.start()
    assert app.process is not None
    deadline = time.monotonic() + 20
    while app.process and time.monotonic() < deadline:
        root.update()
        time.sleep(0.02)
    assert app.report is not None, app.detail.get("1.0", "end")
    assert app.report.status == Status.DIFFERENT
    assert len(app.tree.get_children()) == 4
    app.tree.selection_set("0")
    app.show_detail()
    assert "不一致" in app.detail.get("1.0", "end")
    app.file_list.selection_set(1)
    old = list(app.files)
    app.move(-1)
    assert app.files == list(reversed(old))
    assert app.report is None


def test_gui_cancel(make_pdf, gui):
    root, app = gui
    app.add_files([make_pdf(), make_pdf()])
    app.start()
    app.cancel()
    root.update()
    assert app.process is None
    assert app.report is None
    assert "中止" in app.status.get()


def test_gui_timeout_never_success(make_pdf, gui, monkeypatch):
    import pdf_layer_compare.gui as module
    monkeypatch.setattr(module, "TIMEOUT", 0.000001)
    root, app = gui
    app.add_files([make_pdf(), make_pdf()])
    app.start()
    deadline = time.monotonic() + 10
    while app.process and time.monotonic() < deadline:
        root.update()
        time.sleep(0.02)
    assert app.process is None
    assert app.report is None
    assert "検証不能" in app.status.get()


def test_offline_source_bundle(make_pdf, tmp_path):
    destination = tmp_path / "offline source"
    build = subprocess.run([sys.executable, str(ROOT / "tools" / "prepare_offline.py"), str(destination)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert build.returncode == 0, build.stderr
    allowed = {".py", ".txt", ".md", ".bat", ".toml", ".typed", ".json", ""}
    assert all(p.suffix in allowed for p in destination.rglob("*") if p.is_file())
    assert list((destination / "vendor").glob("pypdf-LICENSE*"))
    a = make_pdf()
    # -S excludes site-packages: the installed pypdf/pytest cannot help.
    run = subprocess.run([sys.executable, "-S", str(destination / "main.py"), "--json", str(a), str(a)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert run.returncode == 0, run.stderr
    assert from_json(run.stdout).status == Status.MATCH
    assert not list(destination.rglob("*.pyc"))

    # Prove setup/start also work with a new, empty venv, no pip or packages.
    venv = subprocess.run([sys._base_executable, "-m", "venv", "--without-pip", str(destination / ".venv")], capture_output=True, text=True, timeout=30)
    assert venv.returncode == 0, venv.stderr
    setup = subprocess.run(["cmd", "/d", "/c", "setup.bat"], cwd=destination, input="\n", capture_output=True, text=True, timeout=30)
    assert setup.returncode == 0, setup.stderr + setup.stdout
    assert "No network access" in setup.stdout
    start = subprocess.run(f'cmd /d /c start.bat --json "{a}" "{a}"', cwd=destination, capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert start.returncode == 0, start.stderr + start.stdout
    assert from_json(start.stdout).status == Status.MATCH
    failed = subprocess.run('cmd /d /c start.bat --json "missing.pdf" "missing.pdf"', cwd=destination, capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert failed.returncode == 2
    assert from_json(failed.stdout).status == Status.UNKNOWN
