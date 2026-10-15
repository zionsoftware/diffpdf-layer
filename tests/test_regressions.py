import pytest
from pypdf.generic import ArrayObject, FloatObject, IndirectObject, NameObject

from pdf_layer_compare.comparator import compare_files
from pdf_layer_compare.model import Status
from pdf_layer_compare.normalize import Canonicalizer
from conftest import pdf_value, stream
from test_comparison import result


def test_float_normalization_preserves_precision():
    assert Canonicalizer().value(FloatObject("0.1234567890123")) != Canonicalizer().value(FloatObject("0.1234567890124"))


def test_content_small_coordinate_change(make_pdf):
    a = make_pdf(content="q 0.1234567890123 0 m 20 20 l S Q")
    b = make_pdf(content="q 0.1234567890124 0 m 20 20 l S Q")
    assert result(compare_files([a, b]), "ベースPDF").status == Status.DIFFERENT


@pytest.mark.parametrize("content", [
    "q 0.12345678901234567 0 m 20 20 l S Q",
    "q /Bad w Q", "q /Pattern cs Q", "q 7 Tf Q", "q 42 Tj Q",
    "q /OC BMC 10 20 30 40 re S EMC Q", "q 1 2 RG Q",
    "q BI /W 1 /H 1 /BPC 8 /CS /G ID x EI Q",
    "q /Missing Do Q",
])
def test_unsupported_or_malformed_ops(make_pdf, content):
    a = make_pdf(content=content)
    assert compare_files([a, a]).status == Status.UNKNOWN


@pytest.mark.parametrize("kwargs", [
    {"/ON": "bad"}, {"/ON": [] , "/OFF": ["bad"]},
    {"/Order": [42]}, {"/BaseState": "/Unchanged"},
    {"/AS": []}, {"/Intent": "bad"}, {"/ListMode": "/Unknown"},
    {"/RBGroups": [42]},
])
def test_malformed_ocg_config(make_pdf, kwargs):
    a = make_pdf(mutate=lambda w, g: w.root_object["/OCProperties"]["/D"].update(pdf_value(kwargs)))
    report = compare_files([a, a])
    assert report.errors
    assert not report.results


def test_conditional_usage_is_explicitly_unknown(make_pdf):
    a = make_pdf(mutate=lambda w, g: g[0].get_object().update(pdf_value({"/Usage": {"/Language": {"/Lang": "ja-JP"}}})))
    assert compare_files([a, a]).status == Status.UNKNOWN


def test_on_off_conflict(make_pdf):
    def mutate(w, groups):
        w.root_object["/OCProperties"]["/D"].update(pdf_value({"/ON": [groups[0]], "/OFF": [groups[0]]}))
    a = make_pdf(mutate=mutate)
    assert compare_files([a, a]).errors


def test_form_cycle(make_pdf):
    def mutate(w, groups):
        form = stream("q /Self Do Q", {"/Type": "/XObject", "/Subtype": "/Form", "/BBox": [0, 0, 100, 100]})
        ref = w._add_object(form)
        form[NameObject("/Resources")] = pdf_value({"/XObject": {"/Self": ref}})
        w.pages[0]["/Resources"][NameObject("/XObject")] = pdf_value({"/Fm": ref})
    a = make_pdf(content="q /Fm Do Q", mutate=mutate)
    report = compare_files([a, a])
    assert report.status == Status.UNKNOWN
    assert "循環" in report.results[0].detail


def test_generic_resource_cycle(make_pdf):
    def mutate(w, groups):
        resource = pdf_value({"/Type": "/ExtGState"})
        ref = w._add_object(resource)
        resource[NameObject("/Cycle")] = ref
        w.pages[0]["/Resources"][NameObject("/ExtGState")] = pdf_value({"/GS": ref})
    a = make_pdf(content="q /GS gs 10 20 30 40 re S Q", mutate=mutate, annotations=[])
    assert compare_files([a, a]).status == Status.UNKNOWN


def test_appearance_cycle(make_pdf):
    def mutate(w, groups):
        ap = pdf_value({})
        ref = w._add_object(ap)
        ap[NameObject("/N")] = ref
        w.pages[0]["/Annots"][0].get_object()[NameObject("/AP")] = ref
    a = make_pdf(mutate=mutate)
    assert compare_files([a, a]).status == Status.UNKNOWN


def test_encryption(make_pdf):
    a = make_pdf(mutate=lambda w, g: w.encrypt(""))
    assert compare_files([a, a]).errors


def test_image_bytes_change(make_pdf):
    def image(data):
        def mutate(w, groups):
            obj = stream(data, {"/Type": "/XObject", "/Subtype": "/Image", "/Width": 1, "/Height": 1, "/ColorSpace": "/DeviceRGB", "/BitsPerComponent": 8})
            w.pages[0]["/Resources"][NameObject("/XObject")] = pdf_value({"/Im": w._add_object(obj)})
        return mutate
    a = make_pdf(content="q /Im Do Q", mutate=image(b"\xff\x00\x00"))
    b = make_pdf(content="q /Im Do Q", mutate=image(b"\x00\xff\x00"))
    assert result(compare_files([a, b]), "ベースPDF").status == Status.DIFFERENT


def test_font_resource_changes(make_pdf):
    def mutate(w, groups):
        w.pages[0]["/Resources"]["/Font"]["/F1"].update(pdf_value({"/BaseFont": "/Courier"}))
    assert result(compare_files([make_pdf(), make_pdf(mutate=mutate)]), "ベースPDF").status == Status.DIFFERENT


def test_unused_page_font_for_default_appearance(make_pdf):
    def mutate(w, groups):
        w.pages[0]["/Resources"]["/Font"]["/F1"].update(pdf_value({"/BaseFont": "/Courier"}))
    a = make_pdf(content="", annotations=[{"/DA": "/F1 10 Tf"}])
    b = make_pdf(content="", annotations=[{"/DA": "/F1 10 Tf"}], mutate=mutate)
    assert result(compare_files([a, b]), "レイヤー: 担当者").status == Status.DIFFERENT


def test_volatile_annotation_metadata_ignored(make_pdf):
    a = make_pdf(annotations=[{"/M": "D:20260101000000", "/NM": "first", "/Contents": "日本語"}])
    b = make_pdf(annotations=[{"/M": "D:20261015000000", "/NM": "second", "/Contents": "日本語"}])
    assert compare_files([a, b]).status == Status.MATCH


def test_layer_annotation_order(make_pdf):
    a = make_pdf(annotations=[{"/Contents": "A"}, {"/Contents": "B"}])
    b = make_pdf(annotations=[{"/Contents": "B"}, {"/Contents": "A"}])
    assert result(compare_files([a, b]), "レイヤー: 担当者").status == Status.DIFFERENT


def test_cross_layer_annotation_order(make_pdf):
    a = make_pdf(annotations=[{"/Contents": "A"}, {"/Contents": "B", "owner": 1}])
    b = make_pdf(annotations=[{"/Contents": "B", "owner": 1}, {"/Contents": "A"}])
    report = compare_files([a, b])
    assert result(report, "合成順序").status == Status.DIFFERENT


def test_no_ocg_base_only(make_pdf):
    def mutate(w, groups):
        del w.root_object[NameObject("/OCProperties")]
        del w.pages[0]["/Resources"][NameObject("/Properties")]
    a = make_pdf(annotations=[], mutate=mutate)
    assert compare_files([a, a]).status == Status.MATCH


def test_oc_image_layer(make_pdf):
    def mutate(w, groups):
        obj = stream(b"\xff\x00\x00", {"/Type": "/XObject", "/Subtype": "/Image", "/Width": 1, "/Height": 1, "/ColorSpace": "/DeviceRGB", "/BitsPerComponent": 8})
        obj[NameObject("/OC")] = groups[0]
        w.pages[0]["/Resources"][NameObject("/XObject")] = pdf_value({"/Im": w._add_object(obj)})
    a = make_pdf(content="q /Im Do Q", mutate=mutate, annotations=[])
    assert compare_files([a, a]).status == Status.MATCH


def test_broken_indirect_oc_reference(make_pdf):
    def mutate(w, groups):
        w.pages[0]["/Annots"][0].get_object()[NameObject("/OC")] = IndirectObject(999999, 0, w)
    a = make_pdf(mutate=mutate)
    assert compare_files([a, a]).status == Status.UNKNOWN


def test_unicode_not_collapsed(make_pdf):
    a = make_pdf(annotations=[{"/Contents": "\u00e9"}])
    b = make_pdf(annotations=[{"/Contents": "e\u0301"}])
    assert result(compare_files([a, b]), "レイヤー: 担当者").status == Status.DIFFERENT


@pytest.mark.parametrize("owner", [True, False])
def test_form_content_change(make_pdf, owner):
    def form(width):
        def mutate(w, groups):
            obj = stream(f"q {width} w 10 20 30 40 re S Q", {"/Type": "/XObject", "/Subtype": "/Form", "/BBox": [0, 0, 100, 100], "/Resources": {}})
            if owner:
                obj[NameObject("/OC")] = groups[0]
            w.pages[0]["/Resources"][NameObject("/XObject")] = pdf_value({"/Fm": w._add_object(obj)})
        return mutate
    a = make_pdf(content="q /Fm Do Q", mutate=form(1), annotations=[])
    b = make_pdf(content="q /Fm Do Q", mutate=form(2), annotations=[])
    report = compare_files([a, b])
    assert result(report, "レイヤー: 担当者" if owner else "ベースPDF").status == Status.DIFFERENT
    if owner:
        assert result(report, "ベースPDF").status == Status.MATCH
