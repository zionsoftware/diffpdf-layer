"""Group isolation and conservative font-only comparison requirements."""
from hashlib import sha256
import json
import re

import pytest
from pypdf.generic import ArrayObject, DictionaryObject, NameObject

from conftest import pdf_value, statuses, stream
from test_comparison import result
from pdf_layer_compare.comparator import compare_files
from pdf_layer_compare.model import Status
from pdf_layer_compare.report import from_json, to_csv, to_json, to_text

URI = {"owner": None, "/Subtype": "/Link", "/A": {"/S": "/URI", "/URI": "https://example.invalid/demo"}}
TEXT = "q /OC /L0 BDC BT /F1 12 Tf 1 0 0 1 20 40 Tm (Same text) Tj ET EMC Q"
SHAPE_B = "q /OC /L1 BDC 10 20 30 40 re S EMC Q"


def font(name="/MS-Gothic", *, program=None, mapping=None, cid=False, encoding="/WinAnsiEncoding"):
    attrs = {"/Type": "/Font", "/Subtype": "/Type0" if cid else "/TrueType", "/BaseFont": name}
    if encoding is not None:
        attrs["/Encoding"] = "/Identity-H" if cid else encoding
    if program is not None:
        attrs["/FontDescriptor"] = {"/Type": "/FontDescriptor", "/FontName": name, "/FontFile2": stream(program)}
    if mapping is not None:
        width = 2 if cid else 1
        entries = "\n".join(f"<{code:0{width*2}X}> <{text.encode('utf-16-be').hex()}>" for code, text in mapping.items())
        cmap = f"begincmap\n1 begincodespacerange\n<{'00'*width}> <{'FF'*width}>\nendcodespacerange\n{len(mapping)} beginbfchar\n{entries}\nendbfchar\nendcmap"
        attrs["/ToUnicode"] = stream(cmap)
    if cid:
        attrs["/DescendantFonts"] = [{"/Type": "/Font", "/Subtype": "/CIDFontType2", "/BaseFont": name,
                                       "/CIDSystemInfo": {"/Registry": "Adobe", "/Ordering": "Identity", "/Supplement": 0}}]
    return pdf_value(attrs)


def install(*fonts):
    def mutate(w, groups):
        for key, obj in fonts:
            w.pages[0]["/Resources"]["/Font"][NameObject(key)] = w._add_object(obj)
    return mutate


def group(report, name="担当者"):
    return result(report, "レイヤー: " + name)


def test_unlayered_demo_drawing_and_links_do_not_pollute_layers(make_pdf):
    base = "q 10 20 10 10 re S Q " + TEXT + " " + SHAPE_B
    a = make_pdf(content=base, annotations=[{"/Contents": "注釈"}])
    b = make_pdf(content=base + " q /Artifact << /Subtype /Watermark /Type /Pagination >> BDC 90 90 10 10 re S EMC Q", annotations=[{"/Contents": "注釈"}, URI])
    report = compare_files([a, b])
    assert result(report, "PDF本体").status == Status.MATCH
    assert result(report, "レイヤーなし").status == Status.DIFFERENT
    assert group(report).status == group(report, "確認者").status == Status.MATCH


def test_demo_uri_only_change_is_local(make_pdf):
    a = make_pdf(annotations=[{"/Contents": "A"}])
    b = make_pdf(annotations=[{"/Contents": "A"}, URI])
    report = compare_files([a, b])
    assert result(report, "レイヤーなし").status == Status.DIFFERENT
    assert group(report).status == group(report, "確認者").status == Status.MATCH


@pytest.mark.parametrize("unknown", ["q unknownoperator Q", "q /OC /L0 BDC unknownoperator EMC Q"])
def test_unsupported_isolated_unit_keeps_other_groups(make_pdf, unknown):
    a = make_pdf(content=unknown + " " + SHAPE_B)
    report = compare_files([a, a])
    assert group(report, "確認者").status == Status.MATCH
    assert result(report, "PDF本体").status == Status.MATCH
    expected = group(report) if "/OC" in unknown else result(report, "レイヤーなし")
    assert expected.status == Status.UNKNOWN


def test_javascript_is_never_treated_as_uri_or_executed(make_pdf):
    a = make_pdf(annotations=[{**URI, "/A": {"/S": "/JavaScript", "/JS": "throw 'not executed';"}}, {"/Contents": "B", "owner": 1}])
    report = compare_files([a, a])
    assert result(report, "レイヤーなし").status == Status.UNKNOWN
    assert group(report, "確認者").status == Status.MATCH


def test_add_remove_and_duplicate_names(make_pdf):
    a = make_pdf(names=("A", "B"), annotations=[])
    b = make_pdf(names=("A", "C"), annotations=[])
    report = compare_files([a, b])
    assert group(report, "A").status == Status.MATCH
    assert group(report, "B").status == Status.REMOVED
    assert group(report, "C").status == Status.ADDED
    duplicate = make_pdf(names=("A", "B", "A"), annotations=[])
    report = compare_files([a, duplicate])
    assert group(report, "A").status == Status.UNKNOWN
    assert group(report, "B").status == Status.MATCH
    assert result(report, "レイヤーなし").status == Status.MATCH


def test_visibility_change_only_marks_affected_group(make_pdf):
    def hide(w, g):
        w.root_object["/OCProperties"]["/D"].update(pdf_value({"/OFF": [g[0]]}))
    report = compare_files([make_pdf(), make_pdf(mutate=hide)])
    assert group(report).status == Status.DIFFERENT
    assert group(report, "確認者").status == Status.MATCH


def test_font_family_changes_are_distinct_matches(make_pdf):
    a = make_pdf(content=TEXT + " " + SHAPE_B, mutate=install(("/F1", font())))
    b = make_pdf(content=TEXT + " " + SHAPE_B, mutate=install(("/F1", font("/MS-Mincho"))))
    report = compare_files([a, b])
    row = group(report)
    assert row.status == Status.FONT_ONLY
    assert row.font_changes[0]["before"] == ["MS-Gothic"]
    assert row.font_changes[0]["after"] == ["MS-Mincho"]
    assert group(report, "確認者").status == Status.MATCH
    assert result(report, "レイヤーなし").status == Status.MATCH
    assert group(compare_files([a, a])).status == Status.MATCH


@pytest.mark.parametrize("before,after", [
    ("Same text", "Other text"), ("20 40 Tm", "21 40 Tm"),
    ("12 Tf", "13 Tf"), ("BT /F1", "BT 1 0 0 rg /F1"),
    ("(Same text) Tj", "(Same text) Tj (more) Tj"),
    ("ET EMC", "ET 1 2 3 4 re S EMC"),
])
def test_font_plus_nonfont_change_is_different(make_pdf, before, after):
    a = make_pdf(content=TEXT, mutate=install(("/F1", font())))
    b = make_pdf(content=TEXT.replace(before, after), mutate=install(("/F1", font("/MS-Mincho"))))
    assert group(compare_files([a, b])).status == Status.DIFFERENT


def test_font_and_opacity_change(make_pdf):
    def setup(alpha, name):
        def mutate(w, g):
            install(("/F1", font(name)))(w, g)
            w.pages[0]["/Resources"][NameObject("/ExtGState")] = pdf_value({"/GS": {"/ca": alpha}})
        return mutate
    content = TEXT.replace("BT", "/GS gs BT")
    a = make_pdf(content=content, mutate=setup(1, "/MS-Gothic"))
    b = make_pdf(content=content, mutate=setup(0.5, "/MS-Mincho"))
    assert group(compare_files([a, b])).status == Status.DIFFERENT


def test_subset_and_reference_names_are_storage_details(make_pdf):
    a = make_pdf(content=TEXT, mutate=install(("/F1", font("/ABCDEF+MS-Gothic", program=b"same font bytes"))))
    b = make_pdf(content=TEXT.replace("/F1", "/Another"), junk=True, mutate=install(("/Another", font("/GHIJKL+MS-Gothic", program=b"same font bytes"))))
    assert statuses(compare_files([a, b])) == {Status.MATCH}


def test_embedded_program_change_requires_safe_text(make_pdf):
    a = make_pdf(content=TEXT, mutate=install(("/F1", font(program=b"font A"))))
    b = make_pdf(content=TEXT, mutate=install(("/F1", font(program=b"font B"))))
    assert group(compare_files([a, b])).status == Status.FONT_ONLY
    bad_a = make_pdf(content=TEXT, mutate=install(("/F1", font(program=b"font A", encoding=None))))
    bad_b = make_pdf(content=TEXT, mutate=install(("/F1", font(program=b"font B", encoding=None))))
    assert group(compare_files([bad_a, bad_b])).status == Status.UNKNOWN
    assert group(compare_files([bad_a, bad_a])).status == Status.MATCH


def test_unused_font_and_extgstate_never_affect_groups(make_pdf):
    def unused(name):
        def mutate(w, g):
            install(("/Unused", font(name)))(w, g)
            w.pages[0]["/Resources"][NameObject("/ExtGState")] = pdf_value({"/Unused": {"/ca": 0.1 if name == "/A" else 0.2}})
        return mutate
    a = make_pdf(content=TEXT + " " + SHAPE_B, mutate=unused("/A"))
    b = make_pdf(content=TEXT + " " + SHAPE_B, mutate=unused("/B"))
    assert statuses(compare_files([a, b])) == {Status.MATCH}


@pytest.mark.parametrize("appearance", [False, True])
def test_freetext_and_appearance_font_encoding_change(make_pdf, appearance):
    def setup(name, code):
        def mutate(w, groups):
            obj = font(name, mapping={code: "日"}, cid=True)
            w.root_object[NameObject("/AcroForm")] = pdf_value({"/Fields": [], "/DR": {"/Font": {"/Default": w._add_object(obj)}}})
            annot = w.pages[0]["/Annots"][0].get_object()
            annot.update(pdf_value({"/DA": "/Default 12 Tf 0 g", "/DS": f"font-family:{name[1:]};font-size:12pt;color:#000000", "/RC": f'<body><p style="font-family:{name[1:]};font-size:12pt">日</p></body>'}))
            if appearance:
                ap = stream(f"q BT /Ref 12 Tf 1 0 0 1 2 3 Tm <{code:04X}> Tj ET Q", {"/Subtype": "/Form", "/BBox": [0, 0, 100, 100]})
                ap[NameObject("/Resources")] = pdf_value({"/Font": {"/Ref": w._add_object(obj)}})
                annot[NameObject("/AP")] = pdf_value({"/N": w._add_object(ap)})
        return mutate
    a = make_pdf(annotations=[{"/Contents": "日"}], mutate=setup("/MS-Gothic", 1))
    b = make_pdf(annotations=[{"/Contents": "日"}], mutate=setup("/MS-Mincho", 2))
    assert group(compare_files([a, b])).status == Status.FONT_ONLY


def test_cid_text_changes_and_unknown_mappings(make_pdf):
    content = TEXT.replace("(Same text)", "<0001>")
    a = make_pdf(content=content, mutate=install(("/F1", font(mapping={1: "日"}, cid=True))))
    b = make_pdf(content=content, mutate=install(("/F1", font("/MS-Mincho", mapping={1: "本"}, cid=True))))
    assert group(compare_files([a, b])).status == Status.DIFFERENT
    missing = make_pdf(content=content, mutate=install(("/F1", font("/MS-Mincho", mapping={2: "日"}, cid=True))))
    assert group(compare_files([a, missing])).status == Status.UNKNOWN


def test_multiple_fonts_are_reported(make_pdf):
    content = TEXT.replace("(Same text) Tj", "(One) Tj /F2 12 Tf (Two) Tj")
    a = make_pdf(content=content, mutate=install(("/F1", font("/A")), ("/F2", font("/B"))))
    b = make_pdf(content=content, mutate=install(("/F1", font("/C")), ("/F2", font("/D"))))
    row = group(compare_files([a, b]))
    assert row.status == Status.FONT_ONLY
    assert row.font_changes[0]["before"] == ["A", "B"]
    assert row.font_changes[0]["after"] == ["C", "D"]


def test_unused_acroform_fonts_do_not_pollute_annotations(make_pdf):
    def setup(name):
        return lambda w, g: w.root_object.update(pdf_value({"/AcroForm": {"/Fields": [], "/DR": {"/Font": {"/Unused": font(name)}}}}))
    a = make_pdf(mutate=setup("/A"))
    b = make_pdf(mutate=setup("/B"))
    assert statuses(compare_files([a, b])) == {Status.MATCH}


def test_annotation_multiset_and_order_are_separate(make_pdf):
    specs = [{"/Contents": "A", "/Rect": [0, 0, 10, 10]}, {"/Contents": "B", "/Rect": [50, 50, 60, 60]}]
    a = make_pdf(annotations=specs)
    b = make_pdf(annotations=list(reversed(specs)))
    assert statuses(compare_files([a, b])) == {Status.MATCH}
    duplicate = make_pdf(annotations=[*specs, specs[0]])
    assert group(compare_files([a, duplicate])).status == Status.DIFFERENT


def test_generation_number_change(make_pdf, tmp_path):
    a = make_pdf()
    data = a.read_bytes()
    data = re.sub(rb"(?m)^(\d+) 0 obj", rb"\1 1 obj", data)
    data = re.sub(rb"(\d+) 0 R\b", rb"\1 1 R", data)
    data = data.replace(b" 00000 n", b" 00001 n")
    b = tmp_path / "generation.pdf"
    b.write_bytes(data)
    assert statuses(compare_files([a, b])) == {Status.MATCH}


def test_report_has_no_overall_judgment_and_roundtrips_fonts(make_pdf):
    a = make_pdf(content=TEXT, mutate=install(("/F1", font())))
    b = make_pdf(content=TEXT, mutate=install(("/F1", font("/MS-Mincho"))))
    before = sha256(a.read_bytes()).digest(), sha256(b.read_bytes()).digest()
    report = compare_files([a, b])
    data = json.loads(to_json(report))
    assert data["schema_version"] == 2 and data["reference"] == str(a)
    assert "status" not in data and not hasattr(report, "status")
    assert from_json(to_json(report)) == report
    assert "総合" not in to_text(report) + to_csv(report)
    assert Status.FONT_ONLY.value in to_text(report) and Status.FONT_ONLY.value in to_csv(report)
    assert (sha256(a.read_bytes()).digest(), sha256(b.read_bytes()).digest()) == before


def test_storage_order_and_dictionary_order(make_pdf, tmp_path):
    a = make_pdf()
    data = a.read_bytes()
    objects = list(re.finditer(rb"(?ms)^(\d+) 0 obj\r?\n.*?^endobj\r?\n", data))
    output = bytearray(data[:objects[0].start()])
    offsets = {}
    for obj in reversed(objects):
        offsets[int(obj[1])] = len(output)
        output.extend(obj[0])
    xref = len(output)
    output.extend(f"xref\n0 {max(offsets)+1}\n0000000000 65535 f \n".encode())
    for number in range(1, max(offsets)+1):
        output.extend(f"{offsets[number]:010} 00000 n \n".encode())
    trailer = re.search(rb"(?s)trailer\s*(<<.*?>>)\s*startxref", data)[1]
    output.extend(b"trailer\n" + trailer + f"\nstartxref\n{xref}\n%%EOF\n".encode())
    b = tmp_path / "reordered.pdf"
    b.write_bytes(output)
    assert statuses(compare_files([a, b])) == {Status.MATCH}


def test_inherited_unused_font_does_not_affect_another_group(make_pdf):
    # A sets its own font, B draws geometry. The outer unused font must not
    # become a dependency of either group.
    content = "/Outside 20 Tf " + TEXT + " " + SHAPE_B
    a = make_pdf(content=content, mutate=install(("/Outside", font("/A"))))
    b = make_pdf(content=content, mutate=install(("/Outside", font("/B"))))
    assert statuses(compare_files([a, b])) == {Status.MATCH}


def test_inherited_font_size_still_changes_text(make_pdf):
    content = "/F1 12 Tf q /OC /L0 BDC BT 1 0 0 1 20 40 Tm (X) Tj ET EMC Q"
    a = make_pdf(content=content)
    b = make_pdf(content=content.replace("12 Tf", "13 Tf"))
    assert group(compare_files([a, b])).status == Status.DIFFERENT


def test_default_colors_are_compared_only_when_used(make_pdf):
    content = "q /OC /L0 BDC 1 0 0 rg 1 2 3 4 re f EMC Q " + SHAPE_B
    def colors(gamma):
        return lambda w, g: w.pages[0]["/Resources"].update(pdf_value({"/ColorSpace": {
            "/DefaultRGB": ["/CalRGB", {"/WhitePoint": [1, 1, 1], "/Gamma": [gamma, gamma, gamma]}]
        }}))
    a = make_pdf(content=content, mutate=colors(1))
    b = make_pdf(content=content, mutate=colors(2))
    report = compare_files([a, b])
    assert group(report).status == Status.DIFFERENT
    assert group(report, "確認者").status == Status.MATCH  # DeviceGray stroke
    assert result(report, "PDF本体").status == Status.MATCH


def test_unmodeled_persistent_clipping_is_not_ignored(make_pdf):
    content = "1 2 30 40 re W n " + TEXT
    a = make_pdf(content=content)
    assert group(compare_files([a, a])).status == Status.UNKNOWN


@pytest.mark.parametrize("array_range", [False, True])
def test_bfrange_cmap_and_text_code_changes(make_pdf, array_range):
    def cmap_font(name, start):
        obj = font(name, cid=True)
        destination = "[<65e5> <672c>]" if array_range else "<0041>"
        cmap = f"begincmap 1 begincodespacerange <0000> <FFFF> endcodespacerange 1 beginbfrange <{start:04X}> <{start+1:04X}> {destination} endbfrange endcmap"
        obj[NameObject("/ToUnicode")] = stream(cmap)
        return obj
    a = make_pdf(content=TEXT.replace("(Same text)", "<00010002>"), mutate=install(("/F1", cmap_font("/A", 1))))
    b = make_pdf(content=TEXT.replace("(Same text)", "<00030004>"), mutate=install(("/F1", cmap_font("/B", 3))))
    assert group(compare_files([a, b])).status == Status.FONT_ONLY


def test_font_mapping_duplicates_fail_closed(make_pdf):
    bad = font("/A", cid=True)
    bad[NameObject("/ToUnicode")] = stream("begincmap 1 begincodespacerange <0000> <FFFF> endcodespacerange 2 beginbfchar <0001> <65e5> <0001> <672c> endbfchar endcmap")
    content = TEXT.replace("(Same text)", "<0001>")
    a = make_pdf(content=content, mutate=install(("/F1", font("/B", mapping={1: "日"}, cid=True))))
    b = make_pdf(content=content, mutate=install(("/F1", bad)))
    assert group(compare_files([a, b])).status == Status.UNKNOWN


def test_word_spacing_encoding_rule_is_preserved(make_pdf):
    a = make_pdf(content=TEXT.replace("BT", "BT 5 Tw").replace("(Same text)", "<20>"),
                 mutate=install(("/F1", font("/A", mapping={32: " "}))))
    b = make_pdf(content=TEXT.replace("BT", "BT 5 Tw").replace("(Same text)", "<01>"),
                 mutate=install(("/F1", font("/B", mapping={1: " "}))))
    assert group(compare_files([a, b])).status == Status.DIFFERENT


def test_ligature_cannot_hide_character_spacing_change(make_pdf):
    a = make_pdf(content=TEXT.replace("BT", "BT 2 Tc").replace("(Same text)", "<01>"),
                 mutate=install(("/F1", font("/A", mapping={1: "fi"}))))
    b = make_pdf(content=TEXT.replace("BT", "BT 2 Tc").replace("(Same text)", "<0203>"),
                 mutate=install(("/F1", font("/B", mapping={2: "f", 3: "i"}))))
    assert group(compare_files([a, b])).status == Status.DIFFERENT


def test_appearance_clipping_is_implicitly_isolated(make_pdf):
    def setup(width):
        def mutate(w, groups):
            obj = stream(f"0 0 {width} 100 re W n 1 2 30 40 re S", {"/Subtype": "/Form", "/BBox": [0, 0, 100, 100], "/Resources": {}})
            w.pages[0]["/Annots"][0].get_object()[NameObject("/AP")] = pdf_value({"/N": w._add_object(obj)})
        return mutate
    a, b = make_pdf(mutate=setup(100)), make_pdf(mutate=setup(90))
    assert group(compare_files([a, a])).status == Status.MATCH
    assert group(compare_files([a, b])).status == Status.DIFFERENT


def test_unknown_page_tree_structure_is_not_silently_ignored(make_pdf):
    def mutate(w, groups):
        w.root_object["/Pages"][NameObject("/UnknownInheritedAttribute")] = pdf_value({"/Value": 1})
    a = make_pdf(mutate=mutate)
    assert result(compare_files([a, a]), "PDF本体").status == Status.UNKNOWN


def test_partial_extgstate_updates_retain_prior_opacity(make_pdf):
    def resources(alpha):
        return lambda w, g: w.pages[0]["/Resources"].update(pdf_value({"/ExtGState": {
            "/First": {"/ca": alpha}, "/Second": {"/LW": 2}
        }}))
    content = "/First gs /Second gs " + TEXT
    a = make_pdf(content=content, mutate=resources(1))
    b = make_pdf(content=content, mutate=resources(0.5))
    assert group(compare_files([a, b])).status == Status.DIFFERENT


def test_overridden_shared_extgstate_is_not_a_dependency(make_pdf):
    def resources(alpha):
        return lambda w, g: w.pages[0]["/Resources"].update(pdf_value({"/ExtGState": {
            "/Outside": {"/ca": alpha}, "/Own": {"/ca": 1}
        }}))
    content = "/Outside gs " + TEXT.replace("BT", "/Own gs BT") + " " + SHAPE_B
    a = make_pdf(content=content, mutate=resources(1))
    b = make_pdf(content=content, mutate=resources(0.5))
    # A overrides fill opacity, B only strokes: neither uses the outer ca.
    assert statuses(compare_files([a, b])) == {Status.MATCH}


def test_unreadable_ocg_registry_is_not_an_empty_matching_registry(make_pdf):
    def mutate(w, groups):
        w.root_object[NameObject("/OCProperties")] = pdf_value({"/OCGs": "broken", "/D": {}})
    a = make_pdf(annotations=[], mutate=mutate)
    report = compare_files([a, a])
    assert result(report, "PDF本体").status == Status.UNKNOWN
    assert result(report, "レイヤーなし").status == Status.UNKNOWN


def test_embedded_base14_name_does_not_prove_implicit_encoding(make_pdf):
    first = font("/Helvetica", program=b"custom encoding A", encoding=None)
    second = font("/Helvetica", program=b"custom encoding B", encoding=None)
    first[NameObject("/Subtype")] = second[NameObject("/Subtype")] = NameObject("/Type1")
    a = make_pdf(content=TEXT, mutate=install(("/F1", first)))
    b = make_pdf(content=TEXT, mutate=install(("/F1", second)))
    assert group(compare_files([a, b])).status == Status.UNKNOWN


def test_unknown_font_behavior_is_not_ignored_as_font_only(make_pdf):
    obj = font()
    obj[NameObject("/UnknownBehavior")] = pdf_value({"/Value": 1})
    a = make_pdf(content=TEXT + " " + SHAPE_B, mutate=install(("/F1", obj)))
    report = compare_files([a, a])
    assert group(report).status == Status.UNKNOWN
    assert group(report, "確認者").status == Status.MATCH


def test_missing_freetext_contents_cannot_prove_font_only(make_pdf):
    a = make_pdf(annotations=[{"/DA": "/F1 10 Tf"}], mutate=install(("/F1", font())))
    b = make_pdf(annotations=[{"/DA": "/F1 10 Tf"}], mutate=install(("/F1", font("/MS-Mincho"))))
    assert group(compare_files([a, b])).status == Status.UNKNOWN
