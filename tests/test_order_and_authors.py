"""Business contract: independent object multisets and reference-only /T."""
from hashlib import sha256
import csv
import io
import json

import pytest
from pypdf.generic import ArrayObject, ByteStringObject, IndirectObject, NameObject, NullObject

from conftest import pdf_value, statuses, stream
from test_comparison import result
from test_group_comparison import TEXT, font, install
from pdf_layer_compare.comparator import compare_files
from pdf_layer_compare.model import Status
from pdf_layer_compare.report import author_summary, from_json, row_details, to_csv, to_json, to_text

RECT_A = "q /OC /L0 BDC 1 0 0 RG 2 w 10 20 30 40 re S EMC Q"
RECT_B = "q /OC /L0 BDC 0 1 0 RG 3 w 70 80 15 20 re S EMC Q"


def arow(report):
    return result(report, "レイヤー: 担当者")


@pytest.mark.parametrize("first,second", [
    (RECT_A, RECT_B),
    (RECT_A, "q /OC /L0 BDC 3 w 10 20 m 60 70 l 55 68 l S EMC Q"),
    (RECT_A, RECT_B.replace("/L0", "/L1")),
    (RECT_A, "q 0 0 1 rg 5 5 10 10 re f Q"),
])
def test_independent_objects_can_be_reordered_across_and_within_groups(make_pdf, first, second):
    a = make_pdf(content=first + " " + second)
    b = make_pdf(content=second + " " + first)
    assert statuses(compare_files([a, b])) == {Status.MATCH}


def test_duplicate_drawing_objects_keep_multiplicity(make_pdf):
    a = make_pdf(content=RECT_A + " " + RECT_A + " " + RECT_B)
    b = make_pdf(content=RECT_B + " " + RECT_A)
    report = compare_files([a, b])
    assert arow(report).status == Status.DIFFERENT
    assert result(report, "レイヤー: 確認者").status == Status.MATCH


@pytest.mark.parametrize("wrapper", ["q /OC /L0 BDC {} EMC Q", "/OC /L0 BDC q {} Q EMC", "q {} Q"])
def test_independent_paths_inside_one_saved_interval_can_be_reordered(make_pdf, wrapper):
    first = "1 0 0 RG 2 w 10 20 30 40 re S"
    second = "0 1 0 RG 3 w 70 80 m 90 100 l S"
    a = make_pdf(content=wrapper.format(first + " " + second))
    b = make_pdf(content=wrapper.format(second + " " + first))
    assert statuses(compare_files([a, b])) == {Status.MATCH}


def test_shared_interval_child_state_and_text_order_are_preserved(make_pdf):
    first = "BT /F1 12 Tf (A) Tj (B) Tj ET"
    second = "BT /F1 12 Tf (C) Tj ET"
    pattern = "q /OC /L0 BDC {} EMC Q"
    a = make_pdf(content=pattern.format("1 0 0 rg " + first + " 0 0 1 rg " + second))
    b = make_pdf(content=pattern.format("0 0 1 rg " + second + " 1 0 0 rg " + first))
    assert statuses(compare_files([a, b])) == {Status.MATCH}
    c = make_pdf(content=pattern.format("1 0 0 rg " + second + " 0 0 1 rg " + first))
    assert arow(compare_files([a, c])).status == Status.DIFFERENT
    d = make_pdf(content=pattern.format("0 0 1 rg " + second + " 1 0 0 rg " + first.replace("(A) Tj (B)", "(B) Tj (A)")))
    assert arow(compare_files([a, d])).status == Status.DIFFERENT


@pytest.mark.parametrize("before,after", [
    ("10 20", "11 20"), ("30 40 re", "30 41 re"),
    ("2 w", "4 w"), ("1 0 0 RG", "0 0 1 RG"),
])
def test_nonfont_changes_survive_object_reordering(make_pdf, before, after):
    a = make_pdf(content=RECT_A + " " + RECT_B)
    b = make_pdf(content=RECT_B + " " + RECT_A.replace(before, after))
    assert arow(compare_files([a, b])).status == Status.DIFFERENT


def test_inherited_state_is_bound_to_each_object(make_pdf):
    a = make_pdf(content="1 w " + RECT_A.replace("2 w ", "") + " 4 w " + RECT_B.replace("3 w ", ""))
    b = make_pdf(content="1 w " + RECT_B.replace("3 w ", "") + " 4 w " + RECT_A.replace("2 w ", ""))
    assert arow(compare_files([a, b])).status == Status.DIFFERENT


def test_matrix_application_order_inside_an_object_is_preserved(make_pdf):
    transforms = "2 0 0 2 0 0 cm 1 0 0 1 10 0 cm "
    other_order = "1 0 0 1 10 0 cm 2 0 0 2 0 0 cm "
    a = make_pdf(content=RECT_A.replace("2 w", transforms + "2 w"))
    b = make_pdf(content=RECT_A.replace("2 w", other_order + "2 w"))
    assert arow(compare_files([a, b])).status == Status.DIFFERENT


def test_text_order_inside_an_object_is_preserved(make_pdf):
    a = make_pdf(content=TEXT.replace("(Same text) Tj", "(A) Tj (B) Tj"))
    b = make_pdf(content=TEXT.replace("(Same text) Tj", "(B) Tj (A) Tj"))
    assert arow(compare_files([a, b])).status == Status.DIFFERENT


def test_complex_unseparated_state_is_unknown(make_pdf):
    a = make_pdf(content="10 20 30 40 re W n " + RECT_A)
    assert arow(compare_files([a, a])).status == Status.UNKNOWN


def test_td_implicit_leading_is_not_lost_between_objects(make_pdf):
    content = "BT /F1 12 Tf 0 -10 TD (first) Tj ET q /OC /L0 BDC BT /F1 12 Tf T* (next) Tj ET EMC Q"
    a = make_pdf(content=content)
    b = make_pdf(content=content.replace("-10 TD", "-20 TD"))
    assert arow(compare_files([a, b])).status == Status.DIFFERENT


def test_leading_used_before_local_override_is_retained(make_pdf):
    content = "10 TL q /OC /L0 BDC BT /F1 12 Tf T* 5 TL (next) Tj ET EMC Q"
    a = make_pdf(content=content)
    b = make_pdf(content=content.replace("10 TL", "20 TL"))
    assert arow(compare_files([a, b])).status == Status.DIFFERENT


def test_form_invocations_can_move_but_form_internal_order_is_kept(make_pdf):
    def forms(w, groups):
        resources = w.pages[0]["/Resources"]
        objects = {}
        for key, drawing in (("/A", "0 0 m 10 10 l S 20 20 m 30 30 l S"), ("/B", "10 20 30 40 re S")):
            obj = stream(drawing, {"/Subtype": "/Form", "/BBox": [0, 0, 100, 100], "/Resources": {}})
            objects[key] = w._add_object(obj)
        resources[NameObject("/XObject")] = pdf_value(objects)
    a = make_pdf(content="q /OC /L0 BDC /A Do EMC Q q /OC /L0 BDC /B Do EMC Q", mutate=forms)
    b = make_pdf(content="q /OC /L0 BDC /B Do EMC Q q /OC /L0 BDC /A Do EMC Q", mutate=forms)
    assert statuses(compare_files([a, b])) == {Status.MATCH}
    def changed(w, groups):
        forms(w, groups)
        w.pages[0]["/Resources"]["/XObject"]["/A"].set_data(b"20 20 m 30 30 l S 0 0 m 10 10 l S")
    c = make_pdf(content="q /OC /L0 BDC /B Do EMC Q q /OC /L0 BDC /A Do EMC Q", mutate=changed)
    assert arow(compare_files([b, c])).status == Status.DIFFERENT


def test_order_change_with_font_change_still_reports_font_only(make_pdf):
    a = make_pdf(content=TEXT + " " + RECT_A, mutate=install(("/F1", font("/MS-Gothic"))))
    b = make_pdf(content=RECT_A + " " + TEXT, mutate=install(("/F1", font("/MS-Mincho"))))
    assert arow(compare_files([a, b])).status == Status.FONT_ONLY


def test_author_only_change_is_a_match_and_reference_information(make_pdf):
    a = make_pdf(annotations=[{"/Contents": "日本語の注記", "/T": "userA"}])
    b = make_pdf(annotations=[{"/Contents": "日本語の注記", "/T": "userB"}])
    row = arow(compare_files([a, b]))
    assert row.status == Status.MATCH
    assert row.authors_changed is True
    assert row.reference_authors.counts == {"userA": 1}
    assert row.target_authors.counts == {"userB": 1}
    assert row.reference_authors.complete and row.target_authors.complete
    assert "構成に変更があります" in row_details(row)


def test_authors_are_aggregated_per_pdf_and_group(make_pdf):
    specs = [{"/T": "userA"}, {"/T": "userA"}, {"/T": "userB"}, {"/T": ""}, {},
             {"/T": "userC", "owner": 1}, {"/T": "userD", "owner": None}, {"owner": None}]
    a = make_pdf(annotations=specs)
    report = compare_files([a, a])
    row = arow(report)
    assert row.reference_authors.counts == {"userA": 2, "userB": 1}
    assert row.reference_authors.unset_count == 2
    assert row.authors_changed is False
    assert result(report, "レイヤー: 確認者").reference_authors.counts == {"userC": 1}
    plain = result(report, "レイヤーなし").reference_authors
    assert plain.counts == {"userD": 1} and plain.unset_count == 1
    assert result(report, "PDF本体").reference_authors is None


@pytest.mark.parametrize("author", ["userA", "userB"])
def test_content_difference_is_not_hidden_by_authors(make_pdf, author):
    a = make_pdf(annotations=[{"/Contents": "first", "/T": "userA"}])
    b = make_pdf(annotations=[{"/Contents": "second", "/T": author}])
    row = arow(compare_files([a, b]))
    assert row.status == Status.DIFFERENT
    assert row.target_authors.counts == {author: 1}
    assert row.authors_changed is (author != "userA")


def test_font_and_author_change_are_independent(make_pdf):
    a = make_pdf(annotations=[{"/Contents": "同じ文字", "/DA": "/F1 12 Tf", "/T": "userA"}], mutate=install(("/F1", font())))
    b = make_pdf(annotations=[{"/Contents": "同じ文字", "/DA": "/F1 12 Tf", "/T": "userB"}], mutate=install(("/F1", font("/MS-Mincho"))))
    row = arow(compare_files([a, b]))
    assert row.status == Status.FONT_ONLY and row.font_changes
    assert row.authors_changed is True
    assert row.reference_authors.counts == {"userA": 1} and row.target_authors.counts == {"userB": 1}


def test_duplicate_annotation_author_swap_has_no_invented_correspondence(make_pdf):
    a = make_pdf(annotations=[{"/Contents": "same", "/T": "userA"}, {"/Contents": "same", "/T": "userB"}])
    b = make_pdf(annotations=[{"/Contents": "same", "/T": "userB"}, {"/Contents": "same", "/T": "userA"}])
    row = arow(compare_files([a, b]))
    assert row.status == Status.MATCH and row.authors_changed is False
    assert row.reference_authors.counts == row.target_authors.counts == {"userA": 1, "userB": 1}
    c = make_pdf(annotations=[{"/Contents": "same", "/T": "userC"}, {"/Contents": "same", "/T": "userA"}])
    changed = arow(compare_files([a, c]))
    assert changed.status == Status.MATCH and changed.authors_changed is True
    assert "userB → userC" not in row_details(changed)


@pytest.mark.parametrize("count", [0, 2])
def test_annotation_count_changes_are_content_changes(make_pdf, count):
    a = make_pdf(annotations=[{"/T": "userA", "/Contents": "same"}])
    b = make_pdf(annotations=[{"/T": "userA", "/Contents": "same"}] * count)
    row = arow(compare_files([a, b]))
    assert row.status == Status.DIFFERENT
    assert row.target_authors.counts == ({"userA": count} if count else {})
    assert row.authors_changed is True
    if not count:
        assert author_summary(row.target_authors) == "注釈なし"


@pytest.mark.parametrize("bad", [42, NullObject(), ByteStringObject(b"\x16"), pdf_value({"/Not": "a string"})])
def test_unreadable_author_does_not_taint_content_or_claim_complete_counts(make_pdf, bad):
    a = make_pdf(annotations=[{"/Contents": "same", "/T": "userA"}])
    b = make_pdf(annotations=[{"/Contents": "same", "/T": bad}])
    row = arow(compare_files([a, b]))
    assert row.status == Status.MATCH
    assert row.target_authors.complete is False and row.target_authors.unreadable_count == 1
    assert row.target_authors.unset_count == 0 and row.target_authors.counts == {}
    assert row.authors_changed is None
    assert "集計未完了" in row_details(row) and "注釈なし" not in author_summary(row.target_authors)


def test_broken_lazy_author_reference_warnings_are_metadata_only(make_pdf):
    def bad_author(w, groups):
        w.pages[0]["/Annots"][0].get_object()[NameObject("/T")] = IndirectObject(999999, 0, w)
    a = make_pdf(mutate=bad_author)
    report = compare_files([a, a])
    assert arow(report).status == Status.MATCH
    assert not arow(report).reference_authors.complete
    assert result(report, "レイヤー: 確認者").reference_authors.complete


def test_unreadable_annotation_list_marks_author_counts_incomplete(make_pdf):
    def malformed(w, groups):
        w.pages[0][NameObject("/Annots")] = pdf_value("broken")
    a = make_pdf(mutate=malformed)
    row = arow(compare_files([a, a]))
    assert row.status == Status.UNKNOWN and not row.reference_authors.complete
    assert row.authors_changed is None


def test_unsupported_annotation_content_can_have_complete_author_counts(make_pdf):
    a = make_pdf(annotations=[{"/T": "userA", "/Subtype": "/Unsupported"}])
    row = arow(compare_files([a, a]))
    assert row.status == Status.UNKNOWN
    assert row.reference_authors.complete and row.reference_authors.counts == {"userA": 1}


@pytest.mark.parametrize("key", ["/Contents", "/Subj", "/CustomAuthor"])
def test_only_t_is_treated_as_author_metadata(make_pdf, key):
    a = make_pdf(annotations=[{"/Contents": "same", key: "first", "/T": "userA"}])
    b = make_pdf(annotations=[{"/Contents": "same", key: "second", "/T": "userB"}])
    assert arow(compare_files([a, b])).status == Status.DIFFERENT


def test_save_metadata_stays_excluded_and_author_counts_stay_exact(make_pdf):
    a = make_pdf(annotations=[{"/T": "userA", "/M": "first", "/CreationDate": "first", "/NM": "id1"}])
    b = make_pdf(annotations=[{"/T": "userA", "/M": "second", "/CreationDate": "second", "/NM": "id2"}])
    row = arow(compare_files([a, b]))
    assert row.status == Status.MATCH and row.authors_changed is False
    assert row.target_authors.counts == {"userA": 1}


def test_reports_include_metadata_and_no_composition_or_identity_claim(make_pdf):
    a = make_pdf(annotations=[{"/T": "userA"}])
    b = make_pdf(annotations=[{"/T": "userB"}])
    before = [sha256(p.read_bytes()).digest() for p in (a, b)]
    report = compare_files([a, b])
    data = json.loads(to_json(report))
    assert data["schema_version"] == 3
    row = next(r for r in data["results"] if r["component"] == "レイヤー: 担当者")
    assert row["status"] == "一致" and row["authors_changed"] is True
    assert row["reference_authors"]["counts"] == {"userA": 1}
    assert from_json(to_json(report)) == report
    for output in (to_json(report), to_text(report), to_csv(report)):
        assert "合成順序" not in output
        assert "userA" in output and "userB" in output
    rows = list(csv.reader(io.StringIO(to_csv(report))))
    assert all(len(r) == 8 for r in rows)
    assert "注釈の作成者名（PDF記録値）" in to_text(report)
    assert [sha256(p.read_bytes()).digest() for p in (a, b)] == before


def test_schema2_load_is_explicitly_incomplete_and_requires_recomparison(make_pdf):
    a = make_pdf()
    data = json.loads(to_json(compare_files([a, a])))
    data["schema_version"] = 2
    for row in data["results"]:
        for key in ("reference_authors", "target_authors", "authors_changed"):
            row.pop(key)
    data["results"].append({"left": str(a), "right": str(a), "component": "合成順序", "status": "不一致", "detail": "old", "font_changes": []})
    old = from_json(json.dumps(data, ensure_ascii=False))
    assert statuses(old) == {Status.UNKNOWN}
    assert not arow(old).reference_authors.complete and arow(old).authors_changed is None
    assert "合成順序" not in to_json(old) + to_text(old) + to_csv(old)
    assert "再比較" in to_text(old)


def test_schema3_rejects_truncated_author_counts(make_pdf):
    a = make_pdf()
    data = json.loads(to_json(compare_files([a, a])))
    data["results"][1]["reference_authors"] = {"complete": True}
    with pytest.raises(ValueError, match="不完全"):
        from_json(json.dumps(data))


@pytest.mark.parametrize("change", ["missing", "false_complete", "false_change"])
def test_schema3_rejects_unreliable_author_metadata(make_pdf, change):
    a = make_pdf(annotations=[{"/T": "userA"}])
    data = json.loads(to_json(compare_files([a, a])))
    row = next(r for r in data["results"] if r["component"] == "レイヤー: 担当者")
    if change == "missing":
        row.pop("reference_authors")
    elif change == "false_complete":
        row["reference_authors"]["unreadable_count"] = 1
    else:
        row["authors_changed"] = True
    with pytest.raises(ValueError):
        from_json(json.dumps(data))


def test_partial_author_counts_keep_known_names_and_other_group_complete(make_pdf):
    a = make_pdf(pages=2, annotations=[{"/T": "userA"}, {"/T": 42}, {"/T": "userB", "owner": 1}])
    report = compare_files([a, a])
    info = arow(report).reference_authors
    assert info.counts == {"userA": 2} and info.unreadable_count == 2 and not info.complete
    assert "取得できた範囲" in author_summary(info)
    other = result(report, "レイヤー: 確認者").reference_authors
    assert other.complete and other.counts == {"userB": 2}


def test_unknown_membership_cannot_produce_complete_author_lists(make_pdf):
    a = make_pdf(annotations=[{"owner": None, "/T": "userA", "/OC": pdf_value({"/Type": "/OCMD"})}])
    report = compare_files([a, a])
    assert all(not r.reference_authors.complete and r.authors_changed is None for r in report.results if r.component != "PDF本体")


def test_duplicate_layer_name_only_makes_its_author_list_ambiguous(make_pdf):
    a = make_pdf(names=("担当者", "担当者", "確認者"), annotations=[{"/T": "userA"}, {"/T": "userB", "owner": 2}])
    report = compare_files([a, a])
    assert not arow(report).reference_authors.complete
    assert result(report, "レイヤー: 確認者").reference_authors.complete
    assert result(report, "レイヤー: 確認者").reference_authors.counts == {"userB": 1}


def test_absent_layer_and_unreadable_file_are_explicit(make_pdf, tmp_path):
    a = make_pdf(names=("担当者",), annotations=[{"/T": "userA"}])
    b = make_pdf(names=("担当者", "確認者"), annotations=[{"/T": "userB", "owner": 1}])
    row = result(compare_files([a, b]), "レイヤー: 確認者")
    assert row.status == Status.ADDED
    assert row.reference_authors.complete and row.reference_authors.group_present is False
    assert row.target_authors.counts == {"userB": 1}
    assert row.authors_changed is True
    row = result(compare_files([b, a]), "レイヤー: 確認者")
    assert row.status == Status.REMOVED and row.target_authors.group_present is False
    row = arow(compare_files([a, tmp_path / "missing.pdf"]))
    assert row.status == Status.UNKNOWN and row.authors_changed is None
    assert not row.target_authors.complete and row.target_authors.group_present is None


def test_author_names_are_literal_and_csv_quotes_control_characters(make_pdf):
    names = ["userA", "usera", " userA ", "=user,\nA"]
    a = make_pdf(annotations=[{"/T": name} for name in names])
    report = compare_files([a, a])
    assert arow(report).reference_authors.counts == dict.fromkeys(names, 1)
    parsed = list(csv.reader(io.StringIO(to_csv(report))))
    assert all(len(row) == 8 for row in parsed)
    assert '=user,\\nA' in parsed[3][5]
