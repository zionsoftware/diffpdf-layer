"""Private, unmodified Editor 11.1 output from the resumed native session.

The PDF fixtures stay outside Git. These tests never generate or rewrite PDFs.
"""
from collections import Counter
import csv
from hashlib import sha256
from io import BytesIO, StringIO

import pytest
from pypdf import PdfReader
from pypdf.generic import ContentStream

from pdf_layer_compare.comparator import compare_files
from pdf_layer_compare.model import BODY, UNLAYERED, Status, layer_key
from pdf_layer_compare.report import (
    AUTHOR_LABEL, author_summary, from_json, row_details, to_csv, to_json, to_text,
)
from test_xchange_integration import samples

SESSION = "resume-20261016-181412"
A, B, EXTRA = (layer_key(name) for name in ("検証者A", "検証者B", "追加検証"))
M, D, F = Status.MATCH, Status.DIFFERENT, Status.DIFFERENT


def native_paths(*names):
    return samples(*(f"{SESSION}/{name}" for name in names))


def annotations(reader):
    return [a.get_object() for page in reader.pages for a in page.get("/Annots", [])]


def direct_authors(path):
    reader = PdfReader(path, strict=True)
    groups = {UNLAYERED: (Counter(), 0)}
    for ref in reader.root_object["/OCProperties"]["/OCGs"]:
        groups[layer_key(str(ref.get_object()["/Name"]))] = (Counter(), 0)
    for annot in annotations(reader):
        group = layer_key(str(annot["/OC"]["/Name"])) if "/OC" in annot else UNLAYERED
        counts, unset = groups[group]
        author = str(annot.get("/T", ""))
        if author:
            counts[author] += 1
        else:
            groups[group] = counts, unset + 1
    return groups


# Expectations follow the actual saved attributes, not just the UI command:
# D1 changes explicit text placement; later licensed features add DEMO/Links.
@pytest.mark.parametrize("before,after,unlayered,a,b,extra,changed", [
    ("baseline-a.pdf", "b-author.pdf", M, F, M, None, {A}),
    ("b-author.pdf", "c-text.pdf", M, D, M, None, set()),
    ("c-text.pdf", "d-font.pdf", M, D, M, None, set()),
    ("d-font.pdf", "g-unlayered.pdf", D, M, M, None, {UNLAYERED}),
    ("d-font.pdf", "e-add.pdf", M, D, M, None, {A}),
    ("e-add.pdf", "f-order.pdf", M, M, M, None, set()),
    ("f-order.pdf", "baseline-ab.pdf", M, D, D, None, {A, B}),
    ("baseline-ab.pdf", "g-b-move.pdf", M, M, D, None, set()),
    ("g-b-move.pdf", "g-a-move.pdf", M, D, M, None, set()),
    ("g-a-move.pdf", "e-resize.pdf", M, D, M, None, set()),
    ("e-resize.pdf", "e-width.pdf", M, D, M, None, set()),
    ("e-width.pdf", "b-shape-author.pdf", M, M, M, None, {A}),
    ("b-shape-author.pdf", "e-color.pdf", M, D, M, None, set()),
    ("e-color.pdf", "e-delete.pdf", M, D, M, None, {A}),
    ("e-delete.pdf", "g-added.pdf", D, M, M, Status.DIFFERENT, {UNLAYERED}),
    ("g-added.pdf", "g-removed.pdf", D, M, M, Status.DIFFERENT, {UNLAYERED}),
    ("g-removed.pdf", "d-font-mincho.pdf", D, F, M, None, {UNLAYERED}),
    ("d-font-mincho.pdf", "h-optimized.pdf", D, M, M, None, {UNLAYERED}),
    ("h-normal-before.pdf", "h-normal.pdf", M, M, M, None, {B}),
])
def test_resumed_native_case_and_outputs(before, after, unlayered, a, b, extra, changed):
    paths = native_paths(before, after)
    hashes = [sha256(path.read_bytes()).digest() for path in paths]
    report = compare_files(paths)
    assert not report.errors
    expected = {BODY: M, UNLAYERED: unlayered, A: a, B: b}
    if extra is not None:
        expected[EXTRA] = extra
    assert {row.component: row.status for row in report.results} == expected
    direct = [direct_authors(path) for path in paths]
    csv_text = to_csv(report)
    detail_csv = csv_text[csv_text.index("比較元PDF,"):]
    csv_rows = {row["対象"]: row for row in csv.DictReader(StringIO(detail_csv))}
    text = to_text(report)
    assert from_json(to_json(report)) == report
    assert "合成順序" not in text + to_json(report) + to_csv(report)
    for row in report.results:
        assert csv_rows[row.component]["内容判定"] == row.status
        # GUI and TXT use this same detail formatter.
        assert row_details(row) in text
        if row.component == A and (before, after) in {("baseline-a.pdf", "b-author.pdf"), ("g-removed.pdf", "d-font-mincho.pdf")}:
            assert row.font_changes
        if row.component == BODY:
            continue
        assert row.authors_changed is (row.component in changed)
        for side, info, raw in zip(("比較元PDF", "比較先PDF"),
                                  (row.reference_authors, row.target_authors), direct):
            counts, unset = raw.get(row.component, (Counter(), 0))
            assert info.complete and not info.errors and info.unreadable_count == 0
            assert info.group_present is (row.component in raw)
            assert info.counts == counts and info.unset_count == unset
            assert csv_rows[row.component][side + " " + AUTHOR_LABEL] == author_summary(info)
    assert [sha256(path.read_bytes()).digest() for path in paths] == hashes


def serialized(value):
    stream = BytesIO()
    value.write_to_stream(stream)
    return stream.getvalue()


def test_native_overlapping_order_really_changes_without_content_change():
    left, right = [PdfReader(path, strict=True) for path in native_paths("e-add.pdf", "f-order.pdf")]
    aa, bb = annotations(left), annotations(right)
    ids_a, ids_b = ([a["/NM"] for a in values] for values in (aa, bb))
    assert len(set(ids_a)) == len(ids_a)
    assert ids_a != ids_b and Counter(ids_a) == Counter(ids_b)
    lookup = {a["/NM"]: a for a in aa}
    squares = [a for a in aa if a.get("/Subtype") == "/Square"]
    assert len(squares) == 2 and squares[0]["/Rect"] == squares[1]["/Rect"]
    for b in bb:
        a = lookup[b["/NM"]]
        assert set(a) == set(b)
        for key in set(a) - {"/AP", "/M"}:
            assert serialized(a.raw_get(key)) == serialized(b.raw_get(key))
        if "/AP" in a:
            assert a["/AP"]["/N"].get_data() == b["/AP"]["/N"].get_data()
    assert [p.get_contents().get_data() for p in left.pages] == [p.get_contents().get_data() for p in right.pages]


def test_native_square_author_edit_changes_only_author_and_save_date():
    readers = [PdfReader(path, strict=True) for path in native_paths("e-width.pdf", "b-shape-author.pdf")]
    changed = []
    for a, b in zip(*(annotations(reader) for reader in readers)):
        assert set(a) == set(b)
        keys = {k for k in a if serialized(a.raw_get(k)) != serialized(b.raw_get(k))}
        if keys:
            changed.append(keys)
        if "/AP" in a:
            assert a["/AP"]["/N"].get_data() == b["/AP"]["/N"].get_data()
    assert changed == [{"/T", "/M"}]


def free_text(reader):
    return next(a for a in annotations(reader) if a.get("/Subtype") == "/FreeText")


def test_native_text_author_save_also_resubsets_font_resources():
    readers = [PdfReader(path, strict=True) for path in native_paths("baseline-a.pdf", "b-author.pdf")]
    aa, bb = [free_text(reader) for reader in readers]
    assert aa["/T"] != bb["/T"]
    assert aa["/Contents"] == bb["/Contents"] and aa["/Rect"] == bb["/Rect"]
    assert aa["/AP"]["/N"].get_data() == bb["/AP"]["/N"].get_data()
    fonts = [a["/AP"]["/N"]["/Resources"]["/Font"] for a in (aa, bb)]
    assert fonts[0]["/F1"]["/FirstChar"] == 32
    assert fonts[1]["/F1"]["/FirstChar"] == 65
    assert fonts[0]["/F0"]["/BaseFont"] != fonts[1]["/F0"]["/BaseFont"]


def test_native_font_edit_can_also_change_explicit_text_placement():
    readers = [PdfReader(path, strict=True) for path in native_paths("c-text.pdf", "d-font.pdf")]
    aa, bb = [free_text(reader) for reader in readers]
    assert aa["/Contents"] == bb["/Contents"] and aa["/Rect"] == bb["/Rect"]
    assert "/RC" in aa and "/RC" not in bb
    offsets = [[tuple(args) for args, op in ContentStream(a["/AP"]["/N"], r).operations if op == b"Td"]
               for a, r in zip((aa, bb), readers)]
    assert offsets[0][2] == (11.388, 0) and offsets[1][2] == (12, 0)
    assert offsets[0][:2] == offsets[1][:2]


def test_native_normal_save_is_not_mislabeled_as_incremental():
    before, after = native_paths("h-normal-before.pdf", "h-normal.pdf")
    # Ctrl+S rewrote this file. No claim of native incremental-save coverage.
    assert not after.read_bytes().startswith(before.read_bytes())
    assert "/Prev" not in PdfReader(after, strict=True).trailer
