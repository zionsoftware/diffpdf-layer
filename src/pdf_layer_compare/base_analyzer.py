"""Partition only isolated optional-content drawing units.

q/Q saves graphics state but NOT the current path; path/text balance and ownership
are checked independently. A mixed base/layer unit is deliberately unsupported.
"""
from contextvars import ContextVar

from pypdf.generic import ArrayObject, ByteStringObject, DictionaryObject, FloatObject, NameObject, NumberObject, StreamObject, TextStringObject

from .fonts import Font, text_value
from .model import Content, Unsupported, combine
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
PAINTING = set("S s f F f* B B* b b* Tj TJ ' \" sh Do".split())
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
            DrawingAnalyzer(reader, ocg).form(obj)
        for value in obj.values():
            validate_resource(value, reader, ocg, active, depth + 1)
    elif isinstance(obj, ArrayObject):
        for value in obj:
            validate_resource(value, reader, ocg, active, depth + 1)
    if isinstance(obj, (DictionaryObject, ArrayObject)):
        cache[id(obj)] = obj


class DrawingAnalyzer:
    def __init__(self, reader, ocg, font=None, font_size=None, colors=("/DeviceGray", "/DeviceGray"), render_mode=0, word_space=0):
        self.reader = reader
        self.ocg = ocg
        self.normal = Canonicalizer(ocg)
        self.font = font
        self.font_size = font_size
        self.fill_space, self.stroke_space = colors
        self.render_mode = render_mode
        self.word_space = word_space
        self.font_stack = []

    def graphics_text_state(self):
        return (self.font, self.font_size, self.fill_space, self.stroke_space, self.render_mode, self.word_space)

    def restore_state(self, value):
        self.font, self.font_size, self.fill_space, self.stroke_space, self.render_mode, self.word_space = value

    def default_colors(self, resources, spaces):
        colors = dictionary(resources.get("/ColorSpace", DictionaryObject()), "ColorSpace")
        defaults = {k: v for k, v in colors.items() if k in {"/DefaultGray", "/DefaultRGB", "/DefaultCMYK"}}
        used = {}
        if defaults:
            for space in spaces:
                space = resolve(space)
                if isinstance(space, str) and space not in {"/DeviceGray", "/DeviceRGB", "/DeviceCMYK"}:
                    space = self.resource(resources, "/ColorSpace", NameObject(space))
                if isinstance(space, ArrayObject):
                    if space[0] in {"/CalGray", "/CalRGB", "/Lab"}:
                        continue
                    if space[0] == "/Indexed":
                        space = resolve(space[1])
                    else:
                        raise Unsupported("既定色空間と複合色空間の依存関係は未対応")
                key = {"/DeviceGray": "/DefaultGray", "/DeviceRGB": "/DefaultRGB", "/DeviceCMYK": "/DefaultCMYK"}.get(str(space))
                if key in defaults:
                    used[NameObject(key)] = defaults[key]
                elif key is None:
                    raise Unsupported("既定色空間の依存関係を確定できません")
        obj = DictionaryObject(used)
        validate_resource(obj, self.reader, self.ocg)
        return self.scalar(obj)

    def scalar(self, value):
        value = self.normal.value(value)
        return Content(value, value)

    def font_resource(self, obj):
        validate_resource(obj, self.reader, self.ocg)
        cache = getattr(self.reader, "_layer_compare_fonts", None)
        if cache is None:
            cache = self.reader._layer_compare_fonts = {}
        obj = dictionary(obj, "Font")
        if id(obj) not in cache:
            cache[id(obj)] = Font(obj, self.normal)
        return cache[id(obj)]

    def state_updates(self, args, op, resources):
        aliases = {"w": "/LW", "J": "/LC", "j": "/LJ", "M": "/ML", "d": "/D", "ri": "/RI", "i": "/FL"}
        if op == "gs":
            obj = dictionary(self.resource(resources, "/ExtGState", args[0]))
            return {"graphic:" + str(k): self.scalar(v) for k, v in obj.items() if k != "/Type"}
        if op in aliases:
            return {"graphic:" + aliases[op]: self.scalar(args if op == "d" else args[0])}
        if op in {"g", "G", "rg", "RG", "k", "K", "CS", "cs"}:
            side = "fill" if op in {"g", "rg", "k", "cs"} else "stroke"
            space = {"g": "/DeviceGray", "G": "/DeviceGray", "rg": "/DeviceRGB", "RG": "/DeviceRGB", "k": "/DeviceCMYK", "K": "/DeviceCMYK"}.get(op)
            value = self.scalar(NameObject(space)) if space else self.operation_state_value(args, op, resources)
            initial = Content(("initial", value.exact), ("initial", value.semantic))
            return {f"color:{side}-space": value, f"color:{side}-value": initial if op in {"CS", "cs"} else self.scalar(args)}
        if op in {"sc", "SC", "scn", "SCN"}:
            return {"color:" + ("fill" if op.islower() else "stroke") + "-value": self.scalar(args)}
        if op in {"cm", "Tc", "Tw", "Tz", "TL", "Tr", "Ts"}:
            return {"op:" + op: self.operation_state_value(args, op, resources)}
        if op == '"':
            return {"op:Tw": self.scalar(args[0]), "op:Tc": self.scalar(args[1])}
        return {}

    def operation_state_value(self, args, op, resources):
        if op in {"CS", "cs"} and args[0] not in {"/DeviceGray", "/DeviceRGB", "/DeviceCMYK"}:
            return self.scalar(self.resource(resources, "/ColorSpace", args[0]))
        return self.scalar(args)

    def inherited_is_used(self, key, op):
        text = op in {"Tj", "TJ", "'", '"'}
        stroke = op in {"S", "s", "B", "B*", "b", "b*", "Do"} or text and self.render_mode in {1, 2, 5, 6}
        fill = op in {"f", "F", "f*", "B", "B*", "b", "b*", "Do", "sh"} or text and self.render_mode in {0, 2, 4, 6}
        if key.startswith("color:fill"):
            return fill
        if key.startswith("color:stroke"):
            return stroke
        if key in {"graphic:/LW", "graphic:/LC", "graphic:/LJ", "graphic:/ML", "graphic:/D", "graphic:/CA", "op:G", "op:RG", "op:K", "op:CS", "op:SC", "op:SCN"}:
            return stroke
        if key in {"graphic:/ca", "op:g", "op:rg", "op:k", "op:cs", "op:sc", "op:scn"}:
            return fill
        if key in {"op:Tc", "op:Tw", "op:Tz", "op:TL", "op:Tr", "op:Ts"}:
            return text or op == "Do"
        return True

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
        if op == "q":
            self.font_stack.append(self.graphics_text_state())
        elif op == "Q":
            if not self.font_stack:
                raise Unsupported("対応しない Q")
            self.restore_state(self.font_stack.pop())
        if op in {"g", "rg", "k", "cs"}:
            self.fill_space = {"g": "/DeviceGray", "rg": "/DeviceRGB", "k": "/DeviceCMYK"}.get(op, args[0])
        if op in {"G", "RG", "K", "CS"}:
            self.stroke_space = {"G": "/DeviceGray", "RG": "/DeviceRGB", "K": "/DeviceCMYK"}.get(op, args[0])
        if op == "Tr":
            if args[0] not in range(8):
                raise Unsupported("Tr が不正")
            self.render_mode = int(args[0])
        if op == "Tw":
            self.word_space = args[0]
        elif op == '"':
            self.word_space = args[0]
        if op in {"Tj", "TJ", "'", '"'}:
            if self.font is None:
                raise Unsupported("文字描画の有効な Tf がありません")
            spaces = []
            if self.render_mode in {0, 2, 4, 6}:
                spaces.append(self.fill_space)
            if self.render_mode in {1, 2, 5, 6}:
                spaces.append(self.stroke_space)
            values = [self.font.value(), self.scalar(self.font_size), self.default_colors(resources, spaces)]
            for value in args:
                if isinstance(value, ArrayObject):
                    values.append(combine("TJ-items", [text_value(v, self.font, self.normal, self.word_space) if string(v) else self.scalar(v) for v in value]))
                elif string(value):
                    values.append(text_value(value, self.font, self.normal, self.word_space))
                else:
                    values.append(self.scalar(value))
            return combine(op, values), None
        owner = None
        category = {"Do": "/XObject", "Tf": "/Font", "gs": "/ExtGState", "sh": "/Shading"}.get(op)
        if op in {"SCN", "scn"} and any(isinstance(v, NameObject) for v in args):
            raise Unsupported("パターン色は未対応")
        if op in {"CS", "cs"} and args[0] not in {"/DeviceGray", "/DeviceRGB", "/DeviceCMYK", "/Pattern"}:
            category = "/ColorSpace"
        if category:
            ref = self.resource(resources, category, args[0])
            if op == "Tf":
                self.font = self.font_resource(ref)
                self.font_size = args[1]
                return combine(op, [self.font.value(), self.scalar(args[1])]), None
            if op == "Do":
                ref = dictionary(ref, "XObject")
                if not isinstance(ref, StreamObject) or ref.get("/Subtype") not in {"/Form", "/Image"}:
                    raise Unsupported("未対応または不正な XObject")
                if "/OC" in ref:
                    owner = self.ocg.owner(ref.raw_get("/OC"))
                if ref.get("/Subtype") == "/Form":
                    return combine(op, [self.form(ref)]), owner
                if owner:
                    from copy import copy
                    ref = copy(ref)
                    del ref[NameObject("/OC")]
            if op == "gs" and "/Font" in dictionary(ref):
                raise Unsupported("ExtGState の Font による文字状態は未対応")
            validate_resource(ref, self.reader, self.ocg)
            args[0] = ref
        values = [self.scalar(args)]
        spaces = []
        if op in {"S", "s", "B", "B*", "b", "b*"}:
            spaces.append(self.stroke_space)
        if op in {"f", "F", "f*", "B", "B*", "b", "b*"}:
            spaces.append(self.fill_space)
        if op in {"Do", "sh"} and isinstance(args[0], DictionaryObject) and "/ColorSpace" in args[0]:
            spaces.append(args[0]["/ColorSpace"])
        if spaces:
            values.append(self.default_colors(resources, spaces))
        return combine(op, values), owner

    def form(self, obj):
        stack = FORM_STACK.get()
        if id(obj) in stack or len(stack) > 30:
            raise Unsupported("Form XObject の循環または深度超過")
        token = FORM_STACK.set(stack | {id(obj)})
        try:
            attrs = DictionaryObject({k: v for k, v in obj.items() if k not in {"/Length", "/Filter", "/DecodeParms", "/Resources", "/OC"}})
            validate_resource(attrs, self.reader, self.ocg)
            resources = dictionary(obj.get("/Resources", DictionaryObject()), "Form Resources")
            # A Form (also an annotation AP) has an implicit graphics-state
            # save/restore. Keep its entire ordered stream together so its
            # initial clipping path and all later drawing retain dependencies.
            ops = [([], b"q"), *content_operations(obj, self.reader), ([], b"Q")]
            children, _, _ = DrawingAnalyzer(self.reader, self.ocg, self.font, self.font_size,
                                             (self.fill_space, self.stroke_space), self.render_mode, self.word_space).partition(ops, resources, allow_layers=False)
            return combine("Form", [self.scalar(attrs), combine("content", children[None])])
        finally:
            FORM_STACK.reset(token)

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
                if args and args[0] == "/OC" and (op != "BDC" or len(args) != 2):
                    raise Unsupported("OC の所属属性が不正で影響グループを確定できません")
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

        groups = {n: [] for n in (None, *self.ocg.names)}
        errors = {n: [] for n in groups}
        composition, inherited = [], {}
        for unit in units:
            isolated = (unit[0][1] == "q" and unit[-1][1] == "Q") or (len(unit) >= 4 and unit[0][1] == "BDC" and unit[1][1] == "q" and unit[-2][1] == "Q" and unit[-1][1] == "EMC")
            affected = set(groups)
            old_state, old_stack = self.graphics_text_state(), list(self.font_stack)
            try:
                affected = self.unit_owners(unit, resources)
                if len(affected) != 1:
                    raise Unsupported("同一描画区間に複数グループが混在")
                owner = next(iter(affected))
                if owner is not None and not allow_layers:
                    raise Unsupported("Form 内部の OCG / marked content は未対応")
                if owner is not None and not isolated:
                    raise Unsupported("OCG 描画の q/Q による独立した状態保存がありません")
                if not isolated and any(op in {"W", "W*"} for _, op in unit):
                    raise Unsupported("q/Q 外のクリッピングによるグループ間依存は未対応")
                if not isolated and (self.render_mode >= 4 or any(op == "Tr" and args and isinstance(args[0], (NumberObject, FloatObject)) and args[0] >= 4 for args, op in unit)):
                    raise Unsupported("q/Q 外の文字クリッピングによるグループ間依存は未対応")
                normalized = []
                overridden, override_stack, needed = set(), [], set()
                for args, op in unit:
                    if op == "q":
                        override_stack.append(set(overridden))
                    elif op == "Q":
                        overridden = override_stack.pop()
                    if op in {"BDC", "BMC", "DP", "MP"}:
                        if op in {"DP", "MP"}:
                            raise Unsupported("marked-content point は未対応")
                        if len(args) != COUNTS[op] or not isinstance(args[0], NameObject) or (op == "BMC" and args[0] == "/OC"):
                            raise Unsupported("marked content のタグまたは属性が不正")
                        value = args
                        if op == "BDC":
                            prop = args[1]
                            if isinstance(prop, NameObject):
                                prop = self.resource(resources, "/Properties", prop)
                            if args[0] == "/OC":
                                value = [NameObject("/OC"), self.ocg.owner(prop)]
                                # Python strings are represented explicitly below.
                                normalized.append(Content((op, owner), (op, owner)))
                                continue
                            prop = dictionary(prop, "marked-content 属性")
                            validate_resource(prop, self.reader, self.ocg)
                            value = [args[0], prop]
                        normalized.append(combine(op, [self.scalar(value)]))
                    else:
                        value, _ = self.operation(args, op, resources)
                        normalized.append(value)
                    updates = self.state_updates(args, op, resources)
                    overridden.update(k for k in updates if k != "op:cm")
                    if op in PAINTING:
                        needed.update(k for k in inherited if k not in overridden and self.inherited_is_used(k, op))
                paints = any(op in PAINTING for _, op in unit)
                if paints:
                    # Only persistent state can affect the next isolated unit;
                    # prior q/Q drawings (including DEMO) cannot leak into it.
                    # Tf is carried at each text-show operation with its size;
                    # it must never taint a group that does not use that font.
                    prefix = [combine(key, [inherited[key]]) for key in sorted(needed)]
                    groups[owner].append(combine("drawing", [combine("inherited", prefix), combine("ops", normalized)]))
                    if not composition or composition[-1] != owner:
                        composition.append(owner)
                if not isolated:
                    for args, op in unit:
                        for key, value in self.state_updates(args, op, resources).items():
                            if key == "op:cm" and key in inherited:
                                inherited[key] = combine("matrices", [inherited[key], value])
                            else:
                                inherited[key] = value
            except Exception as exc:
                if not allow_layers:
                    raise
                if not isolated:
                    affected = set(groups)  # unknown state may reach later units
                for name in affected:
                    errors[name].append(str(exc))
                if isolated:
                    self.restore_state(old_state)
                    self.font_stack = old_stack
        return groups, errors, composition

    def unit_owners(self, unit, resources):
        stack, owners = [], set()
        for args, op in unit:
            owner = stack[-1] if stack else None
            if op in {"BDC", "BMC"}:
                if op == "BDC" and len(args) == 2 and args[0] == "/OC":
                    prop = args[1]
                    if isinstance(prop, NameObject):
                        prop = self.resource(resources, "/Properties", prop)
                    new_owner = self.ocg.owner(prop)
                    if owner is not None and owner != new_owner:
                        owners.update((owner, new_owner))
                    owner = new_owner
                    owners.add(owner)
                stack.append(owner)
            elif op == "EMC":
                if not stack:
                    raise Unsupported("対応しない EMC")
                stack.pop()
            elif op == "Do" and len(args) == 1:
                obj = dictionary(self.resource(resources, "/XObject", args[0]))
                if "/OC" in obj:
                    xowner = self.ocg.owner(obj.raw_get("/OC"))
                    if owner is not None and owner != xowner:
                        owners.update((owner, xowner))
                    owner = xowner
                owners.add(owner)
            elif op in GEOMETRY or op not in COUNTS and op not in {"SC", "sc", "SCN", "scn"}:
                owners.add(owner)
        return owners or {None}


PAGE_KEYS = {"/Type", "/Parent", "/Resources", "/Contents", "/Annots", "/MediaBox", "/CropBox", "/BleedBox", "/TrimBox", "/ArtBox", "/Rotate", "/UserUnit", "/Group", "/Metadata", "/StructParents", "/Tabs", "/Trans"}


def page_attributes(page, ocg):
    extra = set(page) - PAGE_KEYS
    if extra:
        raise Unsupported(f"未対応のページ属性: {', '.join(sorted(extra))}")
    attrs = DictionaryObject({k: v for k, v in page.items() if k not in {"/Parent", "/Resources", "/Contents", "/Annots", "/Metadata", "/StructParents"}})
    if "/Trans" in attrs:
        transition = dictionary(attrs["/Trans"], "ページ Trans")
        # An empty transition dictionary means the default replacement (no
        # animation). Editors may remove it when resaving. Preserve all actual
        # transition parameters so presentation behaviour changes are detected.
        if not transition:
            del attrs[NameObject("/Trans")]
    value = Canonicalizer(ocg).value(attrs)
    return Content(value, value)
