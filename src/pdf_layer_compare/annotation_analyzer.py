from pypdf.generic import ArrayObject, DictionaryObject, FloatObject, NumberObject, StreamObject

from .base_analyzer import DrawingAnalyzer, validate_resource
from .model import Unsupported
from .normalize import Canonicalizer, array, content_operations, dictionary, resolve


SUPPORTED = {"/Text", "/FreeText", "/Line", "/Square", "/Circle", "/Polygon", "/PolyLine", "/Highlight", "/Underline", "/Squiggly", "/StrikeOut", "/Caret", "/Stamp", "/Ink", "/Redact", "/Watermark"}
VOLATILE = {"/M", "/CreationDate", "/NM"}


def coordinates(value, label, count=None):
    values = array(value, label)
    if (count is not None and len(values) != count) or any(not isinstance(resolve(v), (NumberObject, FloatObject)) for v in values):
        raise Unsupported(f"{label}: 座標の個数または型が不正")
    return values


def appearance(value, reader, ocg, active=frozenset(), depth=0):
    value = resolve(value)
    if id(value) in active or depth > 50:
        raise Unsupported("外観状態の循環または深度超過")
    active = active | {id(value)}
    if isinstance(value, StreamObject):
        if "/OC" in value:
            raise Unsupported("外観ストリーム内部の OCG 条件は未対応")
        resources = dictionary(value.get("/Resources", DictionaryObject()))
        base, _, _ = DrawingAnalyzer(reader, ocg).partition(content_operations(value, reader), resources, allow_layers=False)
        attrs = DictionaryObject({k: v for k, v in value.items() if k not in {"/Length", "/Filter", "/DecodeParms", "/Resources"}})
        validate_resource(attrs, reader, ocg)
        validate_resource(resources, reader, ocg)
        return (Canonicalizer(ocg).value(attrs), Canonicalizer(ocg).value(resources), base)
    value = dictionary(value, "AP または外観状態")
    return tuple((str(k), appearance(v, reader, ocg, active, depth + 1)) for k, v in sorted(value.items()))


def analyze_annotations(page, reader, ocg, page_number):
    layers = {n: [] for n in ocg.names}
    order = []
    for index, ref in enumerate(array(page.get("/Annots", ArrayObject()), "Annots"), 1):
        annot = dictionary(ref, f"注釈 {index}")
        if "/Type" in annot and annot["/Type"] != "/Annot":
            raise Unsupported(f"注釈 {index}: Type が不正")
        if annot.get("/Subtype") not in SUPPORTED:
            raise Unsupported(f"注釈 {index}: 未対応の種類 {annot.get('/Subtype')}")
        if "/OC" not in annot:
            raise Unsupported(f"注釈 {index}: レイヤー未所属の注釈")
        owner = ocg.owner(annot.raw_get("/OC"))
        if "/Rect" not in annot or len(array(annot["/Rect"], "注釈 Rect")) != 4:
            raise Unsupported(f"注釈 {index}: Rect が不正")
        coordinates(annot["/Rect"], "注釈 Rect", 4)
        if annot["/Subtype"] == "/Line":
            coordinates(annot.get("/L"), "Line L", 4)
        if annot["/Subtype"] in {"/Polygon", "/PolyLine"}:
            values = coordinates(annot.get("/Vertices"), "Vertices")
            if len(values) < 4 or len(values) % 2:
                raise Unsupported("Vertices が不正")
        if annot["/Subtype"] == "/Ink":
            for path in array(annot.get("/InkList"), "InkList"):
                values = coordinates(path, "Ink path")
                if len(values) < 2 or len(values) % 2:
                    raise Unsupported("Ink path が不正")
        if "/P" in annot and annot.raw_get("/P") != page.indirect_reference:
            raise Unsupported(f"注釈 {index}: 所属ページ参照が不正")
        if any(k in annot for k in ("/Popup", "/Parent", "/IRT", "/A", "/AA", "/RichMediaContent")):
            raise Unsupported(f"注釈 {index}: 関連注釈またはアクションは未対応")
        ap = appearance(annot.raw_get("/AP"), reader, ocg) if "/AP" in annot else None
        data = DictionaryObject({k: v for k, v in annot.items() if k not in VOLATILE | {"/P", "/OC", "/AP"}})
        validate_resource(data, reader, ocg)
        # Default appearance and rich text may use page resources even when no
        # AP exists. Retain the complete resource graph conservatively here.
        resources = page.get("/Resources", DictionaryObject())
        resources = Canonicalizer(ocg).value(resources)
        defaults = Canonicalizer(ocg).value(reader.root_object.get("/AcroForm", DictionaryObject()))
        layers[owner].append((page_number, Canonicalizer(ocg).value(data), ap, resources, defaults))
        order.append(owner)
    return layers, order
