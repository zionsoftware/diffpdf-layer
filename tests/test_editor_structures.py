from conftest import statuses
"""Synthetic regressions for structures observed in Editor 11.1 output.

The user's PDFs and native Editor output are deliberately kept out of Git.
"""
import pytest

from conftest import pdf_value
from test_comparison import result
from pdf_layer_compare.comparator import compare_files
from pdf_layer_compare.model import Status, Unsupported
from pdf_layer_compare.normalize import Canonicalizer


def test_empty_transition_is_default(make_pdf):
    a = make_pdf()
    b = make_pdf(mutate=lambda w, g: w.pages[0].update(pdf_value({"/Trans": {}})))
    assert statuses(compare_files([a, b])) == {Status.MATCH}


def test_transition_parameters_retained(make_pdf):
    a = make_pdf()
    b = make_pdf(mutate=lambda w, g: w.pages[0].update(pdf_value({"/Trans": {"/S": "/Dissolve", "/D": 2}})))
    assert result(compare_files([a, b]), "PDF本体").status == Status.DIFFERENT


def editor_state(state="/ON"):
    def mutate(w, groups):
        groups[0].get_object().update(pdf_value({"/Usage": {
            f"/{event}": {f"/{event}State": state}
            for event in ("View", "Print", "Export")
        }}))
        w.root_object["/OCProperties"]["/D"].update(pdf_value({"/AS": [
            {"/Event": f"/{event}", "/Category": [f"/{event}"], "/OCGs": groups}
            for event in ("View", "Print", "Export")
        ]}))
    return mutate


def test_editor_usage_and_auto_state(make_pdf):
    a = make_pdf(mutate=editor_state())
    b = make_pdf(mutate=editor_state("/OFF"))
    assert statuses(compare_files([a, a])) == {Status.MATCH}
    report = compare_files([a, b])
    assert result(report, "レイヤーなし").status == Status.MATCH
    assert result(report, "レイヤー: 担当者").status == Status.DIFFERENT


@pytest.mark.parametrize("entry", [
    {"/Event": "/View", "/Category": ["/Zoom"]},
    {"/Event": "/Other", "/Category": ["/View"]},
    {"/Event": "/View", "/Category": [], "/OCGs": []},
    {"/Event": "/View", "/Category": ["/View"], "/Unknown": 1},
])
def test_unsupported_auto_state(make_pdf, entry):
    a = make_pdf(mutate=lambda w, g: w.root_object["/OCProperties"]["/D"].update(pdf_value({"/AS": [entry]})))
    assert Status.UNKNOWN in statuses(compare_files([a, a]))


@pytest.mark.parametrize("tag,attribute", [
    ("Artifact", "/Subtype /Watermark /Type /Pagination"),
    ("Span", "/ActualText (Japanese text)"),
])
def test_marked_properties_preserved(make_pdf, tag, attribute):
    content = f"q /{tag} << {attribute} >> BDC BT /F1 12 Tf (X) Tj ET EMC Q"
    a = make_pdf(content=content)
    b = make_pdf(content=content.replace("Watermark", "Header").replace("Japanese text", "Changed text"))
    assert statuses(compare_files([a, a])) == {Status.MATCH}
    assert result(compare_files([a, b]), "レイヤーなし").status == Status.DIFFERENT


def test_named_marked_properties(make_pdf):
    def prop(text):
        return lambda w, g: w.pages[0]["/Resources"]["/Properties"].update(pdf_value({"/P0": {"/ActualText": text}}))
    content = "q /Span /P0 BDC BT /F1 12 Tf (X) Tj ET EMC Q"
    a = make_pdf(content=content, mutate=prop("A"))
    b = make_pdf(content=content, mutate=prop("B"))
    assert statuses(compare_files([a, a])) == {Status.MATCH}
    assert result(compare_files([a, b]), "レイヤーなし").status == Status.DIFFERENT


def test_empty_form_annotation_fonts(make_pdf):
    def font(name):
        return lambda w, g: w.root_object.update(pdf_value({"/AcroForm": {
            "/Fields": [], "/DR": {"/Font": {"/F0": {"/Type": "/Font", "/Subtype": "/Type1", "/BaseFont": name}}}
        }}))
    a = make_pdf(mutate=font("/Helvetica"), annotations=[{"/Contents": "同じ文字", "/DA": "/F0 10 Tf"}])
    b = make_pdf(mutate=font("/Courier"), annotations=[{"/Contents": "同じ文字", "/DA": "/F0 10 Tf"}])
    assert statuses(compare_files([a, a])) == {Status.MATCH}
    report = compare_files([a, b])
    assert result(report, "レイヤーなし").status == Status.MATCH
    assert result(report, "レイヤー: 担当者").status == Status.DIFFERENT


@pytest.mark.parametrize("form", [
    {"/Fields": [{"/FT": "/Tx", "/T": "field"}]},
    {"/Fields": [], "/NeedAppearances": True},
    {"/Fields": [], "/XFA": "unsupported"},
    {"/Fields": [], "/DR": 42},
])
def test_interactive_or_unsupported_forms(make_pdf, form):
    a = make_pdf(mutate=lambda w, g: w.root_object.update(pdf_value({"/AcroForm": form})))
    assert Status.UNKNOWN in statuses(compare_files([a, a]))


def test_shared_resource_cache_does_not_mask_cycles():
    normal = Canonicalizer()
    shared = pdf_value({"/Value": 1})
    normal.value(shared)
    # Active ancestry must be checked even for a previously cached object.
    with pytest.raises(Unsupported, match="循環"):
        normal.value(shared, active=frozenset({id(shared)}))


def test_uri_demo_links_are_structurally_compared(make_pdf):
    a = make_pdf(annotations=[{"owner": None, "/Subtype": "/Link", "/A": {"/S": "/URI", "/URI": "https://example.invalid/"}}])
    assert statuses(compare_files([a, a])) == {Status.MATCH}
