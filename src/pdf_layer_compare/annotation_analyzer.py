"""Compare annotation multisets, with separate overlapping-paint order."""
import re
import xml.etree.ElementTree as ET

from pypdf.generic import ArrayObject, ByteStringObject, DecodedStreamObject, DictionaryObject, FloatObject, NameObject, NumberObject, StreamObject, TextStringObject

from .base_analyzer import DrawingAnalyzer, validate_resource
from .model import Content, Unsupported, combine
from .normalize import Canonicalizer, array, content_operations, dictionary, resolve

SUPPORTED = {"/Text", "/FreeText", "/Line", "/Square", "/Circle", "/Polygon", "/PolyLine", "/Highlight", "/Underline", "/Squiggly", "/StrikeOut", "/Caret", "/Stamp", "/Ink", "/Redact", "/Watermark", "/Link"}
VOLATILE = {"/M", "/CreationDate", "/NM"}


def coordinates(value, label, count=None):
    values = array(value, label)
    if (count is not None and len(values) != count) or any(not isinstance(resolve(v), (NumberObject, FloatObject)) for v in values):
        raise Unsupported(f"{label}: 座標の個数または型が不正")
    return values


def css(value):
    """Only font-family is optional. Size, style, colour, spacing stay exact."""
    fields, neutral, fonts = [], [], []
    for field in str(value).split(";"):
        if not field.strip():
            continue
        key, sep, val = field.partition(":")
        if not sep or not re.fullmatch(r"[a-zA-Z-]+", key.strip()):
            return Content(str(value), str(value))
        key, val = key.strip().lower(), val.strip()
        fields.append((key, val))
        neutral.append((key, "<font-family>" if key == "font-family" else val))
        if key == "font-family":
            fonts.append((val, "css:" + val))
    return Content(tuple(fields), tuple(neutral), tuple(fonts))


def rich_text(value):
    try:
        root = ET.fromstring(str(value))
    except ET.ParseError:
        return Content(str(value), str(value))

    def node(element, depth=0):
        if depth > 50:
            raise Unsupported("RichText の深度超過")
        attrs = []
        for key, val in sorted(element.attrib.items()):
            attrs.append(combine(key, [css(val) if key == "style" else Content(val, val)]))
        return combine(element.tag, [Content((element.text, element.tail), (element.text, element.tail)),
                                     combine("attrs", attrs), combine("children", [node(c, depth+1) for c in element])])
    return node(root)


def appearance(value, reader, ocg, active=frozenset(), depth=0):
    value = resolve(value)
    if id(value) in active or depth > 50:
        raise Unsupported("外観状態の循環または深度超過")
    active = active | {id(value)}
    if isinstance(value, StreamObject):
        if "/OC" in value:
            raise Unsupported("外観ストリーム内部の OCG 条件は未対応")
        return DrawingAnalyzer(reader, ocg).form(value)
    value = dictionary(value, "AP または外観状態")
    return combine("AP", [combine(str(k), [appearance(v, reader, ocg, active, depth+1)]) for k, v in sorted(value.items())])


def default_appearance(value, page, reader, ocg):
    # AcroForm DR is the default-appearance namespace. Page resources are a
    # fallback only when the requested name is absent there.
    fonts = DictionaryObject(dictionary(dictionary(page.get("/Resources", DictionaryObject())).get("/Font", DictionaryObject())))
    form = dictionary(reader.root_object.get("/AcroForm", DictionaryObject()))
    fonts.update(dictionary(dictionary(form.get("/DR", DictionaryObject())).get("/Font", DictionaryObject())))
    resources = DictionaryObject({NameObject("/Font"): fonts})
    stream = DecodedStreamObject()
    stream.set_data(bytes(value) if isinstance(value, ByteStringObject) else str(value).encode("ascii", errors="strict"))
    analyzer = DrawingAnalyzer(reader, ocg)
    values = []
    for args, raw in content_operations(stream, reader):
        op = raw.decode("ascii")
        if op not in {"Tf", "g", "rg", "k", "G", "RG", "K", "Tc", "Tw", "Tz", "TL", "Tr", "Ts"}:
            raise Unsupported(f"DA の未対応命令: {op}")
        values.append(analyzer.operation(args, op, resources)[0])
        if op == "Tf" and args[1] <= 0:
            values.append(Content((), (), font_errors=("DA の自動フォントサイズでは配置を安全に比較できません",)))
    return combine("DA", values)


def annotation_content(annot, page, reader, ocg):
    if "/Type" in annot and annot["/Type"] != "/Annot":
        raise Unsupported("注釈 Type が不正")
    subtype = annot.get("/Subtype")
    if subtype not in SUPPORTED:
        raise Unsupported(f"未対応の注釈種類 {subtype}")
    coordinates(annot.get("/Rect"), "注釈 Rect", 4)
    if subtype == "/Line":
        coordinates(annot.get("/L"), "Line L", 4)
    if subtype in {"/Polygon", "/PolyLine"}:
        values = coordinates(annot.get("/Vertices"), "Vertices")
        if len(values) < 4 or len(values) % 2:
            raise Unsupported("Vertices が不正")
    if subtype == "/Ink":
        for path in array(annot.get("/InkList"), "InkList"):
            values = coordinates(path, "Ink path")
            if len(values) < 2 or len(values) % 2:
                raise Unsupported("Ink path が不正")
    if "/P" in annot and annot.raw_get("/P") != page.indirect_reference:
        raise Unsupported("注釈の所属ページ参照が不正")
    if any(k in annot for k in ("/Popup", "/Parent", "/IRT", "/AA", "/Dest", "/RichMediaContent")):
        raise Unsupported("関連注釈または動的アクションは未対応")
    if "/A" in annot:
        action = dictionary(annot["/A"], "注釈 Action")
        if subtype != "/Link" or action.get("/S") != "/URI" or set(action) - {"/Type", "/S", "/URI", "/IsMap"}:
            raise Unsupported("URI Link 以外の注釈アクションは未対応 (実行しません)")
        if not isinstance(resolve(action.get("/URI")), (TextStringObject, ByteStringObject)):
            raise Unsupported("URI 文字列が不正")
    normal = Canonicalizer(ocg)
    data = DictionaryObject({k: v for k, v in annot.items() if k not in VOLATILE | {"/P", "/OC", "/AP", "/DA", "/RC", "/DS"}})
    validate_resource(data, reader, ocg)
    value = normal.value(data)
    values = [Content(value, value)]
    if "/AP" in annot:
        values.append(appearance(annot.raw_get("/AP"), reader, ocg))
    if "/DA" in annot:
        values.append(default_appearance(resolve(annot["/DA"]), page, reader, ocg))
    if "/RC" in annot:
        values.append(combine("RC", [rich_text(annot["/RC"])]))
    if "/DS" in annot:
        values.append(combine("DS", [css(annot["/DS"])]))
    if subtype == "/FreeText" and "/AP" not in annot and "/RC" not in annot and not isinstance(resolve(annot.get("/Contents")), TextStringObject):
        values.append(Content((), (), font_errors=("FreeText の文字内容を安全に復元できません",)))
    return combine("annotation", values)


def analyze_annotations(page, reader, ocg, form_error=""):
    groups = {n: [] for n in (None, *ocg.names)}
    errors = {n: [] for n in groups}
    ordered = []
    for index, ref in enumerate(array(page.get("/Annots", ArrayObject()), "Annots"), 1):
        affected = set(groups)
        try:
            annot = dictionary(ref, f"注釈 {index}")
            owner = ocg.owner(annot.raw_get("/OC")) if "/OC" in annot else None
            affected = {owner}
            if form_error and annot.get("/Subtype") in {"/FreeText", "/Widget"}:
                raise Unsupported(form_error)
            value = annotation_content(annot, page, reader, ocg)
            groups[owner].append(value)
            rect = tuple(float(v) for v in annot["/Rect"])
            ordered.append((owner, rect, value))
        except Exception as exc:
            for name in affected:
                errors[name].append(f"注釈 {index}: {exc}")
    # Storage order alone is irrelevant; order of intersecting annotations can
    # change painting. Compare that separately, including duplicate counts.
    overlap = []
    if len(ordered) > 2000:
        order_errors = ["注釈の重なり検査上限 (2000) 超過"]
    else:
        order_errors = [e for values in errors.values() for e in values]
        for i, (owner, a, value) in enumerate(ordered):
            for other, b, next_value in ordered[i+1:]:
                if max(min(a[0], a[2]), min(b[0], b[2])) < min(max(a[0], a[2]), max(b[0], b[2])) and max(min(a[1], a[3]), min(b[1], b[3])) < min(max(a[1], a[3]), max(b[1], b[3])):
                    overlap.append(combine((owner, other), [value, next_value]))
    return groups, errors, combine("overlap-order", overlap, unordered=True), order_errors
