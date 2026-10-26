"""Acceptance cases for role selection, preservation rules, and audit output."""
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from pypdf import PdfReader

from pdf_layer_compare.business import summarize
from pdf_layer_compare.comparator import compare_files
from pdf_layer_compare.model import BODY, UNLAYERED, ROLES, BusinessStatus, Result, Status, layer_key
from pdf_layer_compare.report import from_json, matrix_headers, matrix_rows, save_report, to_json, to_text


@pytest.mark.parametrize("roles,reference,count", [
    (("担当", "確認"), "確認", 1),
    (("担当", "確認", "審査"), "審査", 3),
    (("担当", "確認", "承認"), "承認", 3),
    (ROLES, "承認", 6),
])
def test_optional_roles_and_reference(make_pdf, roles, reference, count, monkeypatch):
    import pdf_layer_compare.comparator as module
    calls = []
    original = module.open_document
    def track(path):
        calls.append(path)
        return original(path)
    monkeypatch.setattr(module, "open_document", track)
    inputs = {role: make_pdf(names=ROLES) for role in reversed(roles)}
    report = compare_files(inputs)
    assert report.roles == list(roles)
    assert report.reference == str(inputs[reference])
    assert len(report.pairs) == count and len(calls) == len(roles)
    assert all(p.overall == Status.MATCH and p.business == BusinessStatus.PASS for p in report.pairs)
    assert matrix_headers(report)[-1] == reference + "〈基準〉"
    assert from_json(to_json(report)) == report


@pytest.mark.parametrize("inputs", [{}, {"確認": "a.pdf"}, {"担当": "a.pdf"},
                                    {"担当": "a", "確認": "b", "誤字": "c"}])
def test_required_roles(inputs):
    assert compare_files(inputs).errors


# The expected protected roles are explicit, independent of the implementation.
PAIRS = [("担当", "確認", {"担当"}), ("担当", "審査", {"担当"}),
         ("担当", "承認", {"担当"}), ("確認", "審査", {"担当", "確認"}),
         ("確認", "承認", {"担当", "確認"}), ("審査", "承認", {"担当", "確認", "審査"})]


@pytest.mark.parametrize("left,right,protected", PAIRS)
@pytest.mark.parametrize("component", [BODY, UNLAYERED, "担当", "確認", "審査", "承認", "図面"])
@pytest.mark.parametrize("state", [Status.DIFFERENT, Status.UNKNOWN])
def test_business_matrix(left, right, protected, component, state):
    names = [BODY, UNLAYERED, *(layer_key(n) for n in (*ROLES, "図面"))]
    changed = component if component in {BODY, UNLAYERED} else layer_key(component)
    rows = [Result("a", "b", name, state if name == changed else Status.MATCH) for name in names]
    summary = summarize("a", "b", left, right, rows)
    required = component in protected or component in {BODY, UNLAYERED, "図面"}
    expected = (BusinessStatus.FAIL if state == Status.DIFFERENT else BusinessStatus.UNKNOWN) if required else BusinessStatus.PASS
    assert summary.business == expected
    assert summary.overall == state


def test_fail_precedes_unknown_and_missing_required():
    rows = [Result("a", "b", BODY, Status.DIFFERENT), Result("a", "b", UNLAYERED, Status.UNKNOWN)]
    summary = summarize("a", "b", "担当", "確認", rows)
    assert summary.business == BusinessStatus.FAIL
    assert any("担当" in reason for reason in summary.reasons)
    rows[0].status = Status.MATCH
    assert summarize("a", "b", "担当", "確認", rows).business == BusinessStatus.UNKNOWN


def test_workflow_changes_all_pairs_and_audit_information(make_pdf):
    files = []
    for stage in range(4):
        specs = [{"owner": 0, "/Contents": "保持"}]
        specs += [{"owner": index, "/Contents": f"工程{index}"} for index in range(1, stage + 1)]
        files.append(make_pdf(names=ROLES, annotations=specs))
    before = [p.read_bytes() for p in files]
    report = compare_files(files)
    assert all(p.overall == Status.DIFFERENT and p.business == BusinessStatus.PASS for p in report.pairs)
    for path, data, info in zip(files, before, report.file_info):
        digest = sha256(data).hexdigest()
        assert info.path == str(path.resolve())
        assert info.sha256 == digest and info.short_hash == digest[:6] + "-" + digest[6:12]
        assert info.size_bytes == len(data)
        assert datetime.fromisoformat(info.modified_at).timestamp() == pytest.approx(path.stat().st_mtime)
        assert datetime.fromisoformat(info.modified_at).tzinfo is not None
        assert path.read_bytes() == data
    table = matrix_rows(report)
    assert table[0][1:4] == [Status.DIFFERENT] * 3
    assert next(row for row in table if row[0] == "確認")[1:4] == [Status.DIFFERENT, Status.MATCH, Status.MATCH]
    assert next(row for row in table if row[0] == "審査")[1:4] == [Status.DIFFERENT, Status.DIFFERENT, Status.MATCH]
    assert next(row for row in table if row[0] == "業務判定")[1:4] == [BusinessStatus.PASS] * 3
    assert all(info.short_hash in to_text(report) for info in report.file_info)


def test_missing_duplicate_and_extra_layers(make_pdf):
    a = make_pdf(names=ROLES)
    b = make_pdf(names=("担当", "確認", "審査", "承認", "追加"))
    report = compare_files({"担当": b, "確認": a})
    assert report.extra_names == ["追加"]
    assert report.pairs[0].business == BusinessStatus.FAIL
    assert matrix_rows(report)[-1][-1] == "該当なし"
    missing = make_pdf(names=("確認", "審査", "承認"))
    assert compare_files([missing, missing]).pairs[0].business == BusinessStatus.UNKNOWN
    assert compare_files([a, missing]).pairs[0].business == BusinessStatus.FAIL
    duplicate = make_pdf(names=(*ROLES, "担当"))
    assert compare_files([a, duplicate]).pairs[0].business == BusinessStatus.UNKNOWN


def test_identical_paths_keep_distinct_role_pairs(make_pdf):
    path = make_pdf(names=ROLES)
    report = compare_files([path] * 4)
    assert len(report.pairs) == 6
    assert all(p.business == BusinessStatus.PASS for p in report.pairs)
    assert from_json(to_json(report)) == report


def test_unparseable_file_retains_hash(make_pdf, tmp_path):
    bad = tmp_path / "broken.pdf"
    bad.write_bytes(b"not a pdf")
    report = compare_files([make_pdf(names=ROLES), bad])
    assert report.file_info[1].sha256 == sha256(bad.read_bytes()).hexdigest()
    assert report.pairs[0].business == BusinessStatus.UNKNOWN


def test_unknown_registry_is_not_displayed_as_both_absent(make_pdf, tmp_path):
    bad = tmp_path / "broken.pdf"
    bad.write_bytes(b"not a pdf")
    report = compare_files([make_pdf(names=(*ROLES, "追加")), make_pdf(names=ROLES), bad])
    extra = next(row for row in matrix_rows(report) if row[0] == "追加（基準PDF外）")
    assert extra[1:3] == [Status.UNKNOWN, Status.UNKNOWN]


def test_file_changed_during_read_is_unverifiable(make_pdf, monkeypatch):
    import pdf_layer_compare.pdf_parser as parser
    a = make_pdf(names=ROLES)
    original = parser.os.fstat
    count = 0
    def changed(fd):
        nonlocal count
        value = original(fd)
        count += 1
        if count == 2:
            from types import SimpleNamespace
            return SimpleNamespace(st_dev=value.st_dev, st_ino=value.st_ino, st_size=value.st_size + 1, st_mtime_ns=value.st_mtime_ns)
        return value
    monkeypatch.setattr(parser.os, "fstat", changed)
    report = compare_files([a, a])
    assert report.pairs[0].business == BusinessStatus.UNKNOWN
    assert "読み込み中" in report.file_info[0].error
    assert not report.file_info[0].sha256


@pytest.mark.parametrize("change", ["decision", "hash", "reference", "missing_pair", "duplicate_row"])
def test_schema4_validates_audit_and_decisions(make_pdf, change):
    report = compare_files([make_pdf(names=ROLES), make_pdf(names=ROLES)])
    data = json.loads(to_json(report))
    if change == "decision":
        data["pairs"][0]["business"] = "FAIL"
    elif change == "hash":
        data["file_info"][0]["sha256"] = "bad"
    elif change == "reference":
        data["reference"] = data["files"][0]
    elif change == "missing_pair":
        data["pairs"] = []
    else:
        data["results"].append(data["results"][0])
    with pytest.raises(ValueError):
        from_json(json.dumps(data))


def test_legacy_schema3_requires_recomparison(make_pdf):
    a, b = make_pdf(), make_pdf()
    data = json.loads(to_json(compare_files([a, b])))
    data.update(schema_version=3, reference=str(a), targets=[str(b)])
    for key in ("roles", "file_info", "pairs", "layer_names", "extra_names"):
        data.pop(key)
    data["results"][0]["status"] = "一致（フォントのみ変更）"
    old = from_json(json.dumps(data))
    assert not old.pairs and all(row.status == Status.UNKNOWN for row in old.results)
    assert "再比較" in to_text(old)


def test_role_cli_can_skip_review(make_pdf, runtime_app, tmp_path):
    files = [make_pdf(names=ROLES) for _ in range(3)]
    output = tmp_path / "cmp.txt"
    run = subprocess.run([sys.executable, str(runtime_app / "main.py"), "--json", "--responsible", str(files[0]),
                          "--confirmation", str(files[1]), "--approval", str(files[2]), "--output", str(output)],
                         capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert run.returncode == 0, run.stderr
    report = from_json(run.stdout)
    assert report.roles == ["担当", "確認", "承認"]
    assert "PASS" in output.read_text(encoding="utf-8")


def test_missing_pdf_dependencies_are_a_save_error(make_pdf, runtime_app, tmp_path):
    pdf = make_pdf(names=ROLES)
    output = tmp_path / "cmp.pdf"
    output.write_bytes(b"previous output")
    run = subprocess.run([sys._base_executable, "-B", "-S", str(runtime_app / "main.py"), "--json", str(pdf), str(pdf),
                          "--output", str(output)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert run.returncode == 2, run.stderr
    report = from_json(run.stdout)
    assert report.pairs[0].business == BusinessStatus.PASS
    assert any("ReportLab" in error for error in report.errors)
    assert output.read_bytes() == b"previous output"


def test_pdf_output_japanese_and_multiple_pages(make_pdf, tmp_path):
    pytest.importorskip("reportlab")
    names = (*ROLES, *[f"追加レイヤー {i:02d} 日本語 < & >" for i in range(50)])
    report = compare_files([make_pdf(names=names), make_pdf(names=names)])
    path = tmp_path / "cmp.pdf"
    save_report(report, path)
    reader = PdfReader(path)
    assert len(reader.pages) >= 3
    text = "\n".join(page.extract_text() for page in reader.pages)
    assert "PDFレイヤー比較結果" in text and "PASS" in text
    assert report.file_info[0].short_hash in text
    assert report.file_info[0].modified_at in text
    assert report.files[0] in text.replace("\n", "")
    assert names[-1] in text
    # Every main table continuation repeats its headings.
    matrix_pages = [page for page in reader.pages if "追加レイヤー" in page.extract_text() and "詳細:" not in page.extract_text()]
    assert any("確認〈基準〉" in page.extract_text() for page in matrix_pages)
    descriptors = [font.get_object().get("/FontDescriptor") for page in reader.pages for font in page["/Resources"]["/Font"].values()]
    assert any(desc and "/FontFile2" in desc.get_object() for desc in descriptors)


def test_pdf_font_error_leaves_existing_output_intact(make_pdf, tmp_path, monkeypatch):
    pytest.importorskip("reportlab")
    monkeypatch.setenv("DIFFPDF_REPORT_FONT", str(tmp_path / "missing.ttf"))
    path = tmp_path / "cmp.pdf"
    path.write_bytes(b"previous output")
    with pytest.raises(ValueError, match="フォント"):
        save_report(compare_files([make_pdf(names=ROLES)] * 2), path)
    assert path.read_bytes() == b"previous output"


def test_pdf_offline_bundle_on_base_python(make_pdf, tmp_path):
    pytest.importorskip("reportlab")
    root = Path(__file__).resolve().parents[1]
    bundle = tmp_path / "pdf runtime"
    run = subprocess.run([sys.executable, str(root / "tools" / "prepare_offline.py"), str(bundle), "--with-pdf"],
                         capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert run.returncode == 0, run.stderr
    pdf = make_pdf(names=ROLES)
    output = tmp_path / "cmp.pdf"
    run = subprocess.run([sys._base_executable, "-B", "-S", str(bundle / "main.py"), "--json", str(pdf), str(pdf),
                          "--output", str(output)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert run.returncode == 0, run.stderr + run.stdout
    report = from_json(run.stdout)
    assert report.pairs[0].business == BusinessStatus.PASS
    assert "PASS" in "".join(p.extract_text() for p in PdfReader(output).pages)
    assert list((bundle / "vendor").glob("reportlab-*.dist-info/licenses/*"))
    assert not list(bundle.rglob("*.pyc"))
