from conftest import statuses
import csv
import gc
import io
import os
import shutil
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
    assert list(csv.reader(io.StringIO(to_csv(report))))[0][0] == "役割"
    for suffix in (".txt", ".csv", ".json"):
        path = tmp_path / ("report" + suffix)
        save_report(report, path)
        assert "不一致" in path.read_text(encoding="utf-8-sig")


@pytest.mark.parametrize("value", ["=evil", "+evil", "-evil", "@evil", "   =evil"])
def test_csv_formula_escape(value):
    report = Report([value, "b"], [Result(value, "b", value, Status.DIFFERENT, value)])
    rows = list(csv.reader(io.StringIO(to_csv(report))))
    assert rows[-1][0].startswith("'")
    assert rows[-1][4].startswith("'")


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


@pytest.mark.parametrize("changed, code", [(False, 0), (True, 0)])
def test_cli(make_pdf, runtime_app, changed, code):
    a, b = make_pdf(), make_pdf(text="Changed" if changed else "Base")
    run = subprocess.run([sys.executable, str(runtime_app / "main.py"), "--json", str(a), str(b)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert run.returncode == code, run.stderr
    assert (Status.DIFFERENT if changed else Status.MATCH) in statuses(from_json(run.stdout))


def test_cli_error_exit(runtime_app):
    run = subprocess.run([sys.executable, str(runtime_app / "main.py"), "--json"], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert run.returncode == 2
    assert from_json(run.stdout).errors


@pytest.fixture
def gui(runtime_app, monkeypatch):
    gc.collect()  # Dispose of previous Tcl interpreters on Tk's owning thread.
    import tkinter as tk
    from pdf_layer_compare.gui import Application
    monkeypatch.setattr("pdf_layer_compare.gui.PROJECT", runtime_app)
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk の画面セッションが利用できません: {exc}")
    root.withdraw()
    app = Application(root)
    yield root, app
    if not app.closed:
        app.close()
    gc.collect()


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
    assert Status.DIFFERENT in statuses(app.report)
    assert len(app.tree.get_children()) == 6
    app.tree.selection_set("2")
    app.show_detail()
    assert "不一致" in app.detail.get("1.0", "end")
    approval = app.files[0]
    app.role_vars["承認"].set(approval)
    assert app.reference_label.cget("text") == f"基準PDF (承認): {approval}"
    assert app.report is None
    app.role_vars["承認"].set("")
    assert app.reference_label.cget("text") == f"基準PDF (確認): {app.files[-1]}"


def test_gui_cancel(make_pdf, gui):
    root, app = gui
    app.add_files([make_pdf(), make_pdf()])
    app.start()
    app.cancel()
    root.update()
    assert app.process is None
    assert app.report is None
    assert "中止" in app.status.get()


def test_gui_preserves_all_group_statuses_and_saved_results(gui, tmp_path, make_pdf):
    _, app = gui
    content = "q /OC /L0 BDC 1 1 2 2 re S EMC Q q /OC /L1 BDC 3 3 2 2 re S EMC Q q /OC /L2 BDC 4 4 2 2 re S EMC Q"
    a = make_pdf(names=("担当", "確認", "審査", "承認"), content=content)
    b = make_pdf(names=("担当", "確認", "審査", "承認"), content=content.replace("3 3", "9 9").replace("4 4 2 2 re S", "unknownoperator"))
    report = compare_files([a, b])
    app.render_report(report)
    observed = {app.tree.item(i, "values")[1] for i in app.tree.get_children()}
    assert set(Status).issubset(observed)
    app.tree.selection_set(str(3 + report.layer_names.index("審査")))
    app.show_detail()
    assert "検証不能" in app.detail.get("1.0", "end")
    for extension in ("json", "csv", "txt"):
        path = tmp_path / ("groups." + extension)
        save_report(report, path)
        assert "検証不能" in path.read_text(encoding="utf-8-sig")
    assert from_json((tmp_path / "groups.json").read_text(encoding="utf-8")) == report


def test_gui_details_keep_author_changes_separate_from_content(gui, make_pdf, tmp_path):
    _, app = gui
    a = make_pdf(annotations=[{"/Contents": "same", "/T": "userA"}])
    b = make_pdf(annotations=[{"/Contents": "same", "/T": "userB"}])
    report = compare_files([a, b])
    app.render_report(report)
    index = 3 + report.layer_names.index("担当者")
    app.tree.selection_set(str(index))
    app.show_detail()
    detail = app.detail.get("1.0", "end")
    assert app.tree.item(str(index), "values")[1] == "一致"
    assert "userA" in detail and "userB" in detail and "1件" in detail
    assert "注釈の作成者名（PDF記録値）" in detail and "構成に変更があります" in detail
    assert "合成順序" not in detail
    for extension in ("json", "txt", "csv"):
        path = tmp_path / ("authors." + extension)
        save_report(report, path)
        output = path.read_text(encoding="utf-8-sig")
        assert "userA" in output and "userB" in output and "合成順序" not in output


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


def test_gui_requires_both_mandatory_roles(make_pdf, gui, monkeypatch):
    _, app = gui
    errors = []
    monkeypatch.setattr("pdf_layer_compare.gui.messagebox.showerror", lambda *a, **kw: errors.append(a))
    app.role_vars["確認"].set(str(make_pdf()))
    app.start()
    assert errors and app.process is None and app.report is None


def test_gui_pdf_save_uses_cmp_default(make_pdf, gui, tmp_path, monkeypatch):
    pytest.importorskip("reportlab")
    _, app = gui
    app.render_report(compare_files([make_pdf(names=("担当", "確認"))] * 2))
    app.output_format.set("PDF")
    options = {}
    def destination(**kwargs):
        options.update(kwargs)
        return str(tmp_path / "cmp.pdf")
    monkeypatch.setattr("pdf_layer_compare.gui.filedialog.asksaveasfilename", destination)
    app.save()
    assert options["initialfile"] == "cmp.pdf" and options["defaultextension"] == ".pdf"
    assert (tmp_path / "cmp.pdf").read_bytes().startswith(b"%PDF-")


def test_offline_source_bundle(make_pdf, tmp_path):
    destination = tmp_path / "offline source"
    build = subprocess.run([sys.executable, str(ROOT / "tools" / "prepare_offline.py"), str(destination)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert build.returncode == 0, build.stderr
    assert not (destination / "setup.bat").exists()
    allowed = {".py", ".txt", ".md", ".bat", ".toml", ".typed", ".json", ""}
    assert all(p.suffix in allowed for p in destination.rglob("*") if p.is_file())
    assert list((destination / "vendor").glob("pypdf-LICENSE*"))
    a = make_pdf()
    # -S excludes site-packages: the installed pypdf/pytest cannot help.
    run = subprocess.run([sys.executable, "-S", str(destination / "main.py"), "--json", str(a), str(a)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert run.returncode == 0, run.stderr
    assert statuses(from_json(run.stdout)) == {Status.MATCH}
    assert not list(destination.rglob("*.pyc"))

    # The installed base interpreter and source files suffice. -S disables
    # installed site-packages; startup must not create a venv or install anything.
    env = {**os.environ, "DIFFPDF_PYTHON": sys._base_executable}
    check = subprocess.run(["cmd", "/d", "/c", "start.bat --check"], cwd=destination, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert check.returncode == 0, check.stderr + check.stdout
    assert "環境確認 OK" in check.stdout
    assert sys._base_executable in check.stdout
    assert not (destination / ".venv").exists()
    start = subprocess.run(f'cmd /d /c start.bat --json "{a}" "{a}"', cwd=destination, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert start.returncode == 0, start.stderr + start.stdout
    assert statuses(from_json(start.stdout)) == {Status.MATCH}
    failed = subprocess.run('cmd /d /c start.bat --json "missing.pdf" "missing.pdf"', cwd=destination, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert failed.returncode == 2
    assert Status.UNKNOWN in statuses(from_json(failed.stdout))


def test_runtime_missing_manual_source(runtime_app, tmp_path):
    destination = tmp_path / "manual source"
    shutil.copytree(runtime_app, destination, ignore=shutil.ignore_patterns("vendor"))
    env = {**os.environ, "DIFFPDF_PYTHON": sys._base_executable}
    # Even if pypdf exists in the development venv, the manual source copy is
    # required and the user must receive actionable placement instructions.
    run = subprocess.run([sys.executable, str(destination / "main.py"), "--json"], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert run.returncode == 2
    report = from_json(run.stdout)
    assert "フォルダー全体" in report.errors[0]
    assert str(destination / "vendor" / "pypdf") in report.errors[0]
    check = subprocess.run(["cmd", "/d", "/c", "start.bat --check"], cwd=destination, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert check.returncode == 2
    assert "ソースが見つかりません" in check.stderr
    assert "README.md" in check.stderr
    assert not (destination / ".venv").exists()


def test_runtime_incomplete_manual_source(runtime_app, tmp_path):
    destination = tmp_path / "incomplete source"
    shutil.copytree(runtime_app, destination, ignore=shutil.ignore_patterns("vendor"))
    package = destination / "vendor" / "pypdf"
    package.mkdir(parents=True)
    shutil.copyfile(runtime_app / "vendor" / "pypdf" / "__init__.py", package / "__init__.py")
    run = subprocess.run([sys._base_executable, "-S", str(destination / "main.py"), "--check"], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert run.returncode == 2
    assert "読み込みに失敗" in run.stderr
    assert "サブフォルダーもすべて必要" in run.stderr


def test_runtime_wrong_manual_source_version(runtime_app, tmp_path):
    destination = tmp_path / "wrong version"
    shutil.copytree(runtime_app, destination, ignore=shutil.ignore_patterns("vendor"))
    package = destination / "vendor" / "pypdf"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("__version__ = '0.0.0'\n", encoding="utf-8")
    run = subprocess.run([sys._base_executable, "-S", str(destination / "main.py"), "--check"], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert run.returncode == 2
    assert "6.20.1" in run.stderr and "0.0.0" in run.stderr


def test_start_ignores_project_venv(runtime_app, tmp_path, make_pdf):
    destination = tmp_path / "with old venv"
    shutil.copytree(runtime_app, destination)
    obsolete = destination / ".venv" / "Scripts"
    obsolete.mkdir(parents=True)
    (obsolete / "python.exe").write_bytes(b"not an executable")
    a = make_pdf()
    run = subprocess.run(f'cmd /d /c start.bat --json "{a}" "{a}"', cwd=destination, env={**os.environ, "DIFFPDF_PYTHON": sys._base_executable}, capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert run.returncode == 0, run.stderr
    assert statuses(from_json(run.stdout)) == {Status.MATCH}


def test_invalid_python_override_is_reported(runtime_app):
    run = subprocess.run(["cmd", "/d", "/c", "start.bat --check"], cwd=runtime_app, env={**os.environ, "DIFFPDF_PYTHON": str(runtime_app / "no-python.exe")}, capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert run.returncode == 2
    assert "DIFFPDF_PYTHON" in run.stdout
    assert not (runtime_app / ".venv").exists()


def test_gui_on_base_python(runtime_app, make_pdf):
    code = """
from pathlib import Path
import sys, time
root_path = Path(sys.argv[1])
sys.dont_write_bytecode = True
sys.path[:0] = [str(root_path / 'src'), str(root_path / 'vendor')]
assert sys.prefix == sys.base_prefix
import tkinter as tk
from pdf_layer_compare.gui import Application
from pdf_layer_compare.model import Status
root = tk.Tk()
root.withdraw()
app = Application(root, sys.argv[2:])
try:
    app.start()
    deadline = time.monotonic() + 20
    while app.process and time.monotonic() < deadline:
        root.update()
        time.sleep(0.02)
    assert app.report is not None, app.detail.get('1.0', 'end')
    assert app.report.results and all(r.status == Status.MATCH for r in app.report.results)
finally:
    app.close()
"""
    a = make_pdf()
    run = subprocess.run([sys._base_executable, "-B", "-S", "-c", code, str(runtime_app), str(a), str(a)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert run.returncode == 0, run.stderr
