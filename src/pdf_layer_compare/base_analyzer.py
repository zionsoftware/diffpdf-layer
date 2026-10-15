"""Partition only isolated optional-content drawing units.

q/Q saves graphics state but NOT the current path; path/text balance and ownership
are checked independently. A mixed base/layer unit is deliberately unsupported.
"""
from contextvars import ContextVar

from pypdf.generic import ArrayObject, ByteStringObject, DictionaryObject, FloatObject, NameObject, NumberObject, StreamObject, TextStringObject

from .model import Unsupported
from .normalize import Canonicalizer, array, content_operations, dictionary, resolve

# Standard PDF operators; compatibility sections, inline images and Type3 are
# outside this version's supported subset. Operand counts are validated.
COUNTS = {
    **dict.fromkeys("q Q h S s f F f* B B* b b* n W W* BT ET T* EMC".split(), 0),
    **dict.fromkeys("w J j M ri i gs g G CS cs sh Do Tc Tw Tz TL Tr Ts Tj TJ ' BMC MP".split(), 1),
    **dict.fromkeys("m l Td TD Tf d BDC DP".split(), 2),
    **dict.fromkeys("RG rg \"".split(), 3),
    **dict.fromkeys("re K k v y".split(), 4),
    **dict.fromkeys("cm c Tm".split(), 6),
}
GEOMETRY = set("m l c v y h re W W* S s f F f* B B* b b* n BT ET Tc Tw Tz TL Tf Tr Ts Td TD Tm T* Tj TJ ' \" sh Do".split())
PATH_START = {"m", "l", "c", "v", "y", "h", "re", "W", "W*"}
PATH_END = {"S", "s", "f", "F", "f*", "B", "B*", "b", "b*", "n"}
TEXT = set("Tc Tw Tz TL Tf Tr Ts Td TD Tm T* Tj TJ ' \"".split())
NUMERIC = set("w J j M i g G RG rg K k m l c v y re cm Tc Tw Tz TL Tr Ts Td TD Tm SC sc SCN scn".split())
FORM_STACK = ContextVar("pdf_form_stack", default=frozenset())


def validate_resource(obj, reader, ocg, active=frozenset(), depth=0):
    """Do not silently bury optional content inside a resource graph."""
    if depth > 50:
        raise Unsupported("リソース参照深度の上限超過")
    obj = resolve(obj)
    if isinstance(obj, (DictionaryObject, ArrayObject)):
        if id(obj) in active:
            raise Unsupported("循環するリソース")
        cache = getattr(reader, "_layer_compare_validated_resources", None)
        if cache is None:
            cache = reader._layer_compare_validated_resources = {}
        if id(obj) in cache:
            return
        active = active | {id(obj)}
    if isinstance(obj, DictionaryObject):
        if "/OC" in obj or obj.get("/Type") in {"/OCG", "/OCMD"}:
            raise Unsupported("リソース内部の追加 OCG 条件は未対応")
        if obj.get("/Subtype") in {"/Type3", "/PS"} or "/PatternType" in obj:
            raise Unsupported("Type3 / PostScript / パターンは未対応")
        if isinstance(obj, StreamObject) and obj.get("/Subtype") == "/Form":
            stack = FORM_STACK.get()
            if id(obj) in stack or len(stack) > 30:
                raise Unsupported("Form XObject の循環または深度超過")
            token = FORM_STACK.set(stack | {id(obj)})
            try:
                ops = content_operations(obj, reader)
                # Fully validate Form contents, not only its raw stream bytes.
                DrawingAnalyzer(reader, ocg).partition(ops, dictionary(obj.get("/Resources", DictionaryObject())), allow_layers=False)
            finally:
                FORM_STACK.reset(token)
        for value in obj.values():
            validate_resource(value, reader, ocg, active, depth + 1)
    elif isinstance(obj, ArrayObject):
        for value in obj:
            validate_resource(value, reader, ocg, active, depth + 1)
    if isinstance(obj, (DictionaryObject, ArrayObject)):
        cache[id(obj)] = obj


class DrawingAnalyzer:
    def __init__(self, reader, ocg):
        self.reader = reader
        self.ocg = ocg
        self.normal = Canonicalizer(ocg)

    def resource(self, resources, category, name):
        values = dictionary(resources.get(category, DictionaryObject()), category)
        if not isinstance(name, NameObject) or name not in values:
            raise Unsupported(f"リソース参照が不正: {category} {name}")
        return resolve(values.raw_get(name))

    def operation(self, args, op, resources):
        if op not in COUNTS and op not in {"SC", "sc", "SCN", "scn"}:
            raise Unsupported(f"未対応の描画命令: {op}")
        if op in COUNTS and len(args) != COUNTS[op]:
            raise Unsupported(f"描画命令 {op}: 引数の個数が不正")
        args = list(args)
        numeric = lambda x: isinstance(x, (NumberObject, FloatObject))
        string = lambda x: isinstance(x, (ByteStringObject, TextStringObject))
        if op in NUMERIC and (not args or any(not numeric(a) for a in args)):
            raise Unsupported(f"{op}: 数値以外の引数")
        if op == "d" and (not isinstance(args[0], ArrayObject) or any(not numeric(a) for a in args[0]) or not numeric(args[1])):
            raise Unsupported("d: 破線の指定が不正")
        if op in {"Do", "gs", "sh", "ri", "CS", "cs"} and not isinstance(args[0], NameObject):
            raise Unsupported(f"{op}: 名前以外の引数")
        if op == "Tf" and (not isinstance(args[0], NameObject) or not numeric(args[1])):
            raise Unsupported("Tf: フォントの指定が不正")
        if op in {"Tj", "'"} and not string(args[0]):
            raise Unsupported(f"{op}: 文字列以外の引数")
        if op == '"' and (not numeric(args[0]) or not numeric(args[1]) or not string(args[2])):
            raise Unsupported("テキスト命令の引数が不正")
        if op == "TJ" and (not isinstance(args[0], ArrayObject) or any(not numeric(a) and not string(a) for a in args[0])):
            raise Unsupported("TJ: テキスト配列が不正")
        if op in {"CS", "cs"} and args[0] == "/Pattern":
            raise Unsupported("パターン色空間は未対応")
        owner = None
        ref = None
        category = {"Do": "/XObject", "Tf": "/Font", "gs": "/ExtGState", "sh": "/Shading"}.get(op)
        if op in {"SCN", "scn"} and any(isinstance(v, NameObject) for v in args):
            raise Unsupported("パターン色は未対応")
        if op in {"CS", "cs"} and args[0] not in {"/DeviceGray", "/DeviceRGB", "/DeviceCMYK", "/Pattern"}:
            category = "/ColorSpace"
        if category:
            ref = self.resource(resources, category, args[0])
            if op == "Do":
                ref = dictionary(ref, "XObject")
                if not isinstance(ref, StreamObject) or ref.get("/Subtype") not in {"/Form", "/Image"}:
                    raise Unsupported("未対応または不正な XObject")
                if "/OC" in ref:
                    owner = self.ocg.owner(ref.raw_get("/OC"))
                # Keep stream data, but remove only its already-validated outer OC.
                if owner:
                    from copy import copy
                    ref = copy(ref)
                    del ref[NameObject("/OC")]
            validate_resource(ref, self.reader, self.ocg)
            args[0] = ref
        return (op, self.normal.value(args)), owner

    def partition(self, ops, resources, allow_layers=True):
        # First find top-level balanced units. Only q...Q or BDC q...Q EMC
        # blocks may be removed from the base. Other layer content is unknown.
        units, current, qdepth, mcdepth, text, path = [], [], 0, 0, False, False
        for args, raw in ops:
            op = raw.decode("ascii")
            current.append((args, op))
            if op == "q":
                qdepth += 1
            elif op == "Q":
                qdepth -= 1
                if qdepth < 0:
                    raise Unsupported("対応しない Q")
            if op in {"BDC", "BMC"}:
                mcdepth += 1
            elif op == "EMC":
                mcdepth -= 1
                if mcdepth < 0:
                    raise Unsupported("対応しない EMC")
            if op == "BT":
                if text or path:
                    raise Unsupported("不正なテキスト開始または未完了パス")
                text = True
            elif op == "ET":
                if not text:
                    raise Unsupported("対応しない ET")
                text = False
            elif op in {"Tj", "TJ", "'", '"', "Td", "TD", "Tm", "T*"} and not text:
                raise Unsupported("BT/ET 外のテキスト描画")
            if op in PATH_START:
                path = True
            elif op in PATH_END:
                path = False
            if qdepth == 0 and mcdepth == 0 and not text and not path:
                units.append(current)
                current = []
        if qdepth or mcdepth or text or path or current:
            raise Unsupported("閉じていない描画状態・marked content・テキスト・パス")

        base, layers, composition = [], {n: [] for n in self.ocg.names}, []
        prefix = []
        for unit in units:
            stack, owners, normalized = [], set(), []
            geometry_owners = set()
            for args, op in unit:
                if op in {"BDC", "BMC", "DP", "MP"}:
                    if op in COUNTS and len(args) != COUNTS[op]:
                        raise Unsupported(f"{op}: 引数不正")
                    if op in {"DP", "MP"}:
                        raise Unsupported("marked-content point は未対応")
                    if not isinstance(args[0], NameObject) or (op == "BMC" and args[0] == "/OC"):
                        raise Unsupported("marked content のタグまたは OC 属性が不正")
                    owner = stack[-1] if stack else None
                    marked_value = self.normal.value(args)
                    if op == "BDC":
                        prop = args[1]
                        if isinstance(prop, NameObject):
                            prop = self.resource(resources, "/Properties", prop)
                        if str(args[0]) == "/OC":
                            new_owner = self.ocg.owner(prop)
                            if owner and owner != new_owner:
                                raise Unsupported("異なる OCG の入れ子")
                            owner = new_owner
                            owners.add(owner)
                            marked_value = owner
                        else:
                            prop = dictionary(prop, "marked-content 属性")
                            validate_resource(prop, self.reader, self.ocg)
                            # Preserve semantic text and artifact attributes;
                            # neither changes the enclosing OCG membership.
                            marked_value = (str(args[0]), self.normal.value(prop))
                    stack.append(owner)
                    normalized.append((op, marked_value))
                    continue
                if op == "EMC":
                    if not stack:
                        raise Unsupported("対応しない EMC")
                    stack.pop()
                    normalized.append((op, ()))
                    continue
                value, xowner = self.operation(args, op, resources)
                owner = stack[-1] if stack else None
                if xowner:
                    if owner and owner != xowner:
                        raise Unsupported("marked content と XObject の異なる OCG 条件")
                    owner = xowner
                    owners.add(owner)
                if owner:
                    owners.add(owner)
                if op in GEOMETRY:
                    geometry_owners.add(owner)
                normalized.append(value)
            if owners:
                if not allow_layers:
                    raise Unsupported("Form 内部の OCG / marked content は未対応")
                if len(owners) != 1 or geometry_owners - owners:
                    raise Unsupported("同一描画区間にベース本文または複数レイヤーが混在")
                if not (unit[0][1] == "q" and unit[-1][1] == "Q"):
                    if not (len(unit) >= 4 and unit[0][1] == "BDC" and unit[1][1] == "q" and unit[-2][1] == "Q" and unit[-1][1] == "EMC"):
                        raise Unsupported("OCG 描画の q/Q による独立した状態保存がありません")
                owner = next(iter(owners))
                layers[owner].append((tuple(prefix), tuple(normalized)))
                composition.append(("layer", owner))
            else:
                base.extend(normalized)
                prefix.extend(normalized)
                # Record base/layer interleaving, including non-painting units
                # conservatively, to avoid accepting changed overlap order.
                composition.append(("base",))
        return tuple(base), layers, composition


PAGE_KEYS = {"/Type", "/Parent", "/Resources", "/Contents", "/Annots", "/MediaBox", "/CropBox", "/BleedBox", "/TrimBox", "/ArtBox", "/Rotate", "/UserUnit", "/Group", "/Metadata", "/StructParents", "/Tabs", "/Trans"}


def analyze_page(page, reader, ocg):
    extra = set(page) - PAGE_KEYS
    if extra:
        raise Unsupported(f"未対応のページ属性: {', '.join(sorted(extra))}")
    resources = dictionary(page.get("/Resources", DictionaryObject()), "ページ Resources")
    analyzer = DrawingAnalyzer(reader, ocg)
    if "/Contents" in page:
        base, layers, composition = analyzer.partition(content_operations(page.raw_get("/Contents"), reader), resources)
    else:
        base, layers, composition = (), {n: [] for n in ocg.names}, []
    attrs = DictionaryObject({k: v for k, v in page.items() if k not in {"/Parent", "/Resources", "/Contents", "/Annots", "/Metadata", "/StructParents"}})
    if "/Trans" in attrs:
        transition = dictionary(attrs["/Trans"], "ページ Trans")
        # An empty transition dictionary means the default replacement (no
        # animation). Editors may remove it when resaving. Preserve all actual
        # transition parameters so presentation behaviour changes are detected.
        if not transition:
            del attrs[NameObject("/Trans")]
    # Default colour spaces apply even without explicit CS/cs operands.
    colors = dictionary(resources.get("/ColorSpace", DictionaryObject()))
    defaults = DictionaryObject({k: v for k, v in colors.items() if k in {"/DefaultGray", "/DefaultRGB", "/DefaultCMYK"}})
    validate_resource(defaults, reader, ocg)
    validate_resource(attrs, reader, ocg)
    normal = Canonicalizer(ocg)
    common = normal.value(defaults)
    for name in layers:
        layers[name] = [(common, value) for value in layers[name]]
    return (normal.value(attrs), common, base), layers, composition
