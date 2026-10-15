"""Optional local evidence: never copy these PDFs into the repository."""
from hashlib import sha256
import json
from pathlib import Path

import pytest

from conftest import statuses
from test_comparison import result
from pdf_layer_compare.comparator import compare_files
from pdf_layer_compare.model import Status

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
