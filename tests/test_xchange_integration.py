"""Optional local evidence: never copy these PDFs into the repository."""
from hashlib import sha256
import json
from pathlib import Path

import pytest
from pypdf import PdfReader

from conftest import statuses
from test_comparison import result
from pdf_layer_compare.comparator import compare_files
from pdf_layer_compare.model import BODY, UNLAYERED, Status, layer_key
from pdf_layer_compare.report import from_json, to_csv, to_json, to_text

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "output" / "xchange-validation"


def samples(*names):
    paths = [SAMPLES / name for name in names]
    if not all(p.is_file() for p in paths):
        pytest.skip("ローカルの PDF-XChange 実出力は Git に含めません")
    return paths


@pytest.mark.parametrize("name", ["mixed_1up_8pt.pdf", "mixed_2up_8pt.pdf", "one-layers.pdf", "one-annotations-a.pdf", "one-annotations-b.pdf", "two-unassigned.pdf"])
def test_native_self_comparison_all_groups_match(name):
    a, = samples(name)
    assert statuses(compare_files([a, a])) == {Status.MATCH}


@pytest.mark.parametrize("before,after", [("mixed_1up_8pt.pdf", "one-resaved.pdf"), ("mixed_2up_8pt.pdf", "two-resaved.pdf")])
def test_native_unchanged_save(before, after):
    assert statuses(compare_files(samples(before, after))) == {Status.MATCH}


def test_unmodified_native_demo_and_japanese_edit_are_independent():
    paths = samples("one-annotations-a.pdf", "one-annotations-b.pdf")
    hashes = [sha256(p.read_bytes()).digest() for p in paths]
    report = compare_files(paths)
    assert result(report, "PDF本体").status == Status.MATCH
    assert result(report, "レイヤーなし").status == Status.DIFFERENT
    assert result(report, "レイヤー: 検証者A").status == Status.DIFFERENT
    assert result(report, "レイヤー: 検証者B").status == Status.MATCH
    assert [sha256(p.read_bytes()).digest() for p in paths] == hashes


def test_native_unassigned_annotation_is_an_ordinary_group():
    report = compare_files(samples("two-resaved.pdf", "two-unassigned.pdf"))
    assert result(report, "PDF本体").status == Status.MATCH
    assert result(report, "レイヤーなし").status == Status.DIFFERENT


@pytest.mark.parametrize("name", ["one-annotations-a.pdf", "one-annotations-b.pdf", "two-unassigned.pdf"])
def test_native_recorded_authors_match_direct_annotation_counts(name):
    path, = samples(name)
    before = sha256(path.read_bytes()).digest()
    reader = PdfReader(path, strict=True)
    expected = {UNLAYERED: ({}, 0)}
    for group in reader.root_object.get("/OCProperties", {}).get("/OCGs", []):
        expected[layer_key(str(group.get_object()["/Name"]))] = ({}, 0)
    for page in reader.pages:
        for ref in page.get("/Annots", []):
            annot = ref.get_object()
            key = layer_key(str(annot["/OC"]["/Name"])) if "/OC" in annot else UNLAYERED
            counts, unset = expected[key]
            name = str(annot.get("/T", ""))
            if name:
                counts[name] = counts.get(name, 0) + 1
            else:
                expected[key] = counts, unset + 1
    report = compare_files([path, path])
    for row in report.results:
        if row.component == BODY:
            continue
        counts, unset = expected[row.component]
        assert row.reference_authors.counts == counts
        assert row.reference_authors.unset_count == unset
        assert row.reference_authors.complete and row.target_authors.complete
        assert row.authors_changed is False
    assert from_json(to_json(report)) == report
    assert "合成順序" not in to_json(report) + to_text(report) + to_csv(report)
    assert sha256(path.read_bytes()).digest() == before


def test_derived_samples_are_checked_separately():
    report = compare_files(samples("one-annotations-a-no-demo-links.pdf", "one-annotations-b-no-demo-links.pdf"))
    assert result(report, "PDF本体").status == Status.MATCH
    assert result(report, "レイヤーなし").status == Status.DIFFERENT
    assert result(report, "レイヤー: 検証者A").status == Status.DIFFERENT
    assert result(report, "レイヤー: 検証者B").status == Status.MATCH


def test_original_hashes_unchanged():
    manifest, = samples("original-hashes.json")
    for item in json.loads(manifest.read_text(encoding="utf-8-sig")):
        assert sha256((ROOT / item["file"]).read_bytes()).hexdigest() == item["sha256"]
