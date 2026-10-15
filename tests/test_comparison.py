from conftest import statuses
from hashlib import sha256

import pytest
from pypdf.generic import ArrayObject, DictionaryObject, NameObject

from pdf_layer_compare.comparator import compare_files
from pdf_layer_compare.model import Status
from conftest import pdf_value, stream


def result(report, component):
    rows = [r for r in report.results if r.component == component]
    assert rows, report.errors
    return rows[0]


def test_identical_and_sources_unchanged(make_pdf):
    a = make_pdf()
    digest = sha256(a.read_bytes()).digest()
    report = compare_files([a, a])
    assert statuses(report) == {Status.MATCH}, report
    assert sha256(a.read_bytes()).digest() == digest


def test_object_numbers_and_compression(make_pdf):
    a = make_pdf()
    b = make_pdf(junk=True, compressed=True)
    assert a.read_bytes() != b.read_bytes()
    report = compare_files([a, b])
    assert statuses(report) == {Status.MATCH}, report


@pytest.mark.parametrize("names", [("担当者", "審査者"), ("担当者",), ("担当者", "担当者")])
def test_layer_name_changes_do_not_stop_other_groups(make_pdf, names):
    report = compare_files([make_pdf(), make_pdf(names=names)])
    assert result(report, "PDF本体").status == Status.MATCH
    assert result(report, "レイヤーなし").status == Status.MATCH
    if names == ("担当者", "担当者"):
        assert result(report, "レイヤー: 担当者").status == Status.UNKNOWN
    else:
        assert result(report, "レイヤー: 確認者").status == Status.REMOVED


@pytest.mark.parametrize("change", [
    {"/Contents": "日本語の注釈!"},
    {"/Contents": "日本語の注釈\u200b"},
    {"/Rect": [10, 20, 91, 60]},
    {"/Subtype": "/Line", "/L": [10, 20, 40, 50], "/LE": ["/None", "/ClosedArrow"]},
    {"/C": [0, 1, 0]},
    {"/BS": {"/W": 2}},
    {"/CA": 0.5},
    {"/F": 36},
    {"/RC": "<body>changed</body>"},
    {"/DA": "/F1 10 Tf 0 g"},
])
def test_annotation_attribute_changes(make_pdf, change):
    a = make_pdf()
    b = make_pdf(annotations=[{"/Contents": "日本語の注釈", **change}])
    report = compare_files([a, b])
    assert result(report, "レイヤー: 担当者").status == Status.DIFFERENT, report
    assert result(report, "レイヤーなし").status == Status.MATCH
    assert result(report, "レイヤー: 確認者").status == Status.MATCH


def test_arrow_shape(make_pdf):
    common = {"/Subtype": "/Line", "/L": [10, 20, 40, 50]}
    a = make_pdf(annotations=[{**common, "/LE": ["/None", "/OpenArrow"]}])
    b = make_pdf(annotations=[{**common, "/LE": ["/None", "/ClosedArrow"]}])
    assert result(compare_files([a, b]), "レイヤー: 担当者").status == Status.DIFFERENT


@pytest.mark.parametrize("annotations", [[], [{"/Contents": "日本語の注釈"}, {"/Contents": "追加"}]])
def test_annotation_add_delete(make_pdf, annotations):
    report = compare_files([make_pdf(), make_pdf(annotations=annotations)])
    assert result(report, "レイヤー: 担当者").status == Status.DIFFERENT


def test_annotation_moved_layer(make_pdf):
    report = compare_files([make_pdf(), make_pdf(annotations=[{"/Contents": "日本語の注釈", "owner": 1}])])
    assert result(report, "レイヤー: 担当者").status == Status.DIFFERENT
    assert result(report, "レイヤー: 確認者").status == Status.DIFFERENT


@pytest.mark.parametrize("kwargs", [
    {"text": "Changed"},
    {"content": "q 10 20 30 40 re S Q"},
    {"pages": 2},
    {"mutate": lambda w, g: w.pages[0].update(pdf_value({"/Rotate": 90}))},
    {"mutate": lambda w, g: w.pages[0].update(pdf_value({"/MediaBox": [0, 0, 601, 800]}))},
])
def test_base_changes(make_pdf, kwargs):
    report = compare_files([make_pdf(), make_pdf(**kwargs)])
    component = "PDF本体" if "pages" in kwargs or "mutate" in kwargs else "レイヤーなし"
    assert result(report, component).status == Status.DIFFERENT, report


def test_unassigned_annotation(make_pdf):
    a = make_pdf(annotations=[{"owner": None}])
    report = compare_files([a, a])
    assert result(report, "レイヤーなし").status == Status.MATCH


def test_unregistered_ocg(make_pdf):
    def mutate(w, groups):
        unknown = w._add_object(pdf_value({"/Type": "/OCG", "/Name": "unknown"}))
        w.pages[0]["/Annots"][0].get_object()[NameObject("/OC")] = unknown
    a = make_pdf(mutate=mutate)
    assert Status.UNKNOWN in statuses(compare_files([a, a]))


def test_ocmd(make_pdf):
    def mutate(w, groups):
        w.pages[0]["/Annots"][0].get_object()[NameObject("/OC")] = w._add_object(pdf_value({"/Type": "/OCMD", "/OCGs": groups, "/P": "/AnyOn"}))
    a = make_pdf(mutate=mutate)
    assert "OCMD" in result(compare_files([a, a]), "レイヤー: 担当者").detail


def test_corrupt_pdf(make_pdf, tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.7\nnot a pdf")
    report = compare_files([make_pdf(), bad])
    assert Status.UNKNOWN in statuses(report)
    assert report.errors


LAYER = "q /OC /L0 BDC 1 0 0 RG 10 20 30 40 re S EMC Q"


def test_marked_content_and_flattening(make_pdf):
    a = make_pdf(content=LAYER, annotations=[])
    b = make_pdf(content=LAYER.replace("30 40", "31 40"), annotations=[])
    report = compare_files([a, b])
    assert result(report, "レイヤー: 担当者").status == Status.DIFFERENT, report
    assert result(report, "レイヤーなし").status == Status.MATCH
    flattened = make_pdf(content="q 1 0 0 RG 10 20 30 40 re S Q", annotations=[])
    report = compare_files([a, flattened])
    assert result(report, "レイヤーなし").status == Status.DIFFERENT
    assert result(report, "レイヤー: 担当者").status == Status.DIFFERENT


def test_bdc_outside_q(make_pdf):
    a = make_pdf(content="/OC /L0 BDC q 10 20 30 40 re S Q EMC")
    assert statuses(compare_files([a, a])) == {Status.MATCH}


@pytest.mark.parametrize("content", [
    "/OC /L0 BDC 10 20 30 40 re S EMC",
    "q /OC /L0 BDC 10 20 30 40 re S EMC 50 50 10 10 re S Q",
    "q /OC /L0 BDC /OC /L1 BDC 10 20 30 40 re S EMC EMC Q",
    "q /OC /L0 BDC 10 20 30 40 re EMC S Q",
    "10 20 m q /OC /L0 BDC 20 20 l S EMC Q",
    "q unknownoperator Q", "q 1 w", "EMC", "BT BT ET ET", "q 10 20 re S Q",
    "q /Span 42 BDC BT /F1 12 Tf (X) Tj ET EMC Q",
])
def test_unsafe_content_unknown(make_pdf, content):
    a = make_pdf(content=content)
    report = compare_files([a, a])
    assert Status.UNKNOWN in statuses(report), report


def test_form_oc(make_pdf):
    def mutate(w, groups):
        form = stream("q 10 20 30 40 re S Q", {"/Type": "/XObject", "/Subtype": "/Form", "/BBox": [0, 0, 100, 100], "/Resources": {}})
        form[NameObject("/OC")] = groups[0]
        w.pages[0]["/Resources"][NameObject("/XObject")] = pdf_value({"/Fm": w._add_object(form)})
    a = make_pdf(content="q /Fm Do Q", mutate=mutate)
    assert statuses(compare_files([a, a])) == {Status.MATCH}


def test_form_inner_oc_unknown(make_pdf):
    def mutate(w, groups):
        form = stream(LAYER, {"/Type": "/XObject", "/Subtype": "/Form", "/BBox": [0, 0, 100, 100]})
        form[NameObject("/Resources")] = w.pages[0]["/Resources"]
        w.pages[0]["/Resources"][NameObject("/XObject")] = pdf_value({"/Fm": w._add_object(form)})
    a = make_pdf(content="q /Fm Do Q", mutate=mutate)
    assert Status.UNKNOWN in statuses(compare_files([a, a]))


def test_appearance_changes(make_pdf):
    def with_ap(width):
        def mutate(w, groups):
            ap = stream(f"q {width} w 0 0 20 20 re S Q", {"/Subtype": "/Form", "/BBox": [0, 0, 30, 30], "/Resources": {}})
            w.pages[0]["/Annots"][0].get_object()[NameObject("/AP")] = pdf_value({"/N": w._add_object(ap)})
        return mutate
    report = compare_files([make_pdf(mutate=with_ap(1)), make_pdf(mutate=with_ap(2))])
    assert result(report, "レイヤー: 担当者").status == Status.DIFFERENT, report


def test_visibility_state(make_pdf):
    def mutate(w, groups):
        w.root_object["/OCProperties"]["/D"][NameObject("/OFF")] = ArrayObject([groups[0]])
    report = compare_files([make_pdf(), make_pdf(mutate=mutate)])
    assert result(report, "レイヤー: 担当者").status == Status.DIFFERENT
    assert result(report, "レイヤーなし").status == Status.MATCH


@pytest.mark.parametrize("count, pairs", [(2, 1), (3, 2), (4, 3)])
def test_reference_comparison_order(make_pdf, count, pairs):
    files = [make_pdf() for _ in range(count)]
    report = compare_files(files)
    assert statuses(report) == {Status.MATCH}
    observed = list(dict.fromkeys((r.left, r.right) for r in report.results))
    assert observed == [(str(files[0]), str(p)) for p in files[1:]]
    assert len(observed) == pairs


@pytest.mark.parametrize("count", [0, 1, 5])
def test_input_count(make_pdf, count):
    assert compare_files([make_pdf() for _ in range(count)]).errors


@pytest.mark.parametrize("attribute", ["/AcroForm", "/OpenAction", "/Names", "/StructTreeRoot"])
def test_unknown_catalog_structure(make_pdf, attribute):
    a = make_pdf(mutate=lambda w, g: w.root_object.update(pdf_value({attribute: {}})))
    assert Status.UNKNOWN in statuses(compare_files([a, a]))


def test_unaffected_pair_continues(make_pdf):
    report = compare_files([make_pdf(), make_pdf(), make_pdf(content="unsupported")])
    assert report.results[0].status == Status.MATCH
    assert any(r.status == Status.UNKNOWN for r in report.results)
