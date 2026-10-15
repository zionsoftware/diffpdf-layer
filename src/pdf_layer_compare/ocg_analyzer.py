from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, NameObject, TextStringObject

from .model import Unsupported
from .normalize import Canonicalizer, array, dictionary, resolve


class OCGAnalyzer:
    def __init__(self, root):
        self.groups = {}
        self.by_object = {}
        props = dictionary(root.get("/OCProperties", DictionaryObject()), "OCProperties")
        if not props:
            self.configuration = ()
            return
        if set(props) - {"/OCGs", "/D", "/Configs"}:
            raise Unsupported("未知の OCProperties キー")
        groups = array(props.get("/OCGs"), "OCGs")
        for ref in groups:
            if not isinstance(ref, IndirectObject):
                raise Unsupported("OCG は間接参照である必要があります")
            group = dictionary(ref, "OCG")
            if group.get("/Type") != "/OCG":
                raise Unsupported("OCGs に OCG 以外が存在")
            name = resolve(group.get("/Name"))
            if not isinstance(name, TextStringObject) or not name:
                raise Unsupported("レイヤー名が不正または空")
            if name in self.groups:
                raise Unsupported(f"レイヤー名が重複: {name}")
            if set(group) - {"/Type", "/Name", "/Intent", "/Usage"}:
                raise Unsupported(f"OCG {name}: 未対応の属性")
            if "/Intent" in group:
                self.validate_intent(group["/Intent"])
            if "/Usage" in group:
                # Automatic view/print/export behaviour needs real-editor
                # fixtures before it can be claimed as supported.
                raise Unsupported(f"OCG {name}: Usage 自動状態は未対応")
            self.groups[str(name)] = group
            self.by_object[id(group)] = str(name)
        default = dictionary(props.get("/D"), "OCG 既定設定 D")
        self.validate_config(default)
        for config in array(props.get("/Configs", ArrayObject()), "Configs"):
            self.validate_config(dictionary(config))
        normal = Canonicalizer(self)
        # Group order in OCGs is storage order, not visual order; /Order remains.
        self.configuration = normal.value(DictionaryObject({k: v for k, v in props.items() if k != "/OCGs"}))
        self.attributes = {name: Canonicalizer().value(group) for name, group in self.groups.items()}

    @property
    def names(self):
        return tuple(sorted(self.groups))

    def owner(self, ref):
        group = dictionary(ref, "OC 所属")
        if group.get("/Type") == "/OCMD":
            raise Unsupported("OCMD / VE / 複数条件の所属は未対応")
        name = self.by_object.get(id(group))
        if name is None:
            raise Unsupported("未知または不正な OCG 参照")
        return name

    def validate_config(self, config):
        if set(config) - {"/Name", "/Creator", "/BaseState", "/ON", "/OFF", "/Intent", "/AS", "/Order", "/ListMode", "/RBGroups", "/Locked"}:
            raise Unsupported("未対応の OCG 設定キー")
        if config.get("/BaseState", "/ON") not in {"/ON", "/OFF"}:
            raise Unsupported("既定設定の BaseState が未対応")
        if "/AS" in config:
            raise Unsupported("OCG 自動状態 AS は未対応")
        if "/Intent" in config:
            self.validate_intent(config["/Intent"])
        if config.get("/ListMode", "/AllPages") not in {"/AllPages", "/VisiblePages"}:
            raise Unsupported("OCG ListMode が不正")
        onoff = []
        for key in ("/ON", "/OFF", "/Locked"):
            names = [self.owner(ref) for ref in array(config.get(key, ArrayObject()), key)]
            if len(names) != len(set(names)):
                raise Unsupported(f"{key}: 重複する OCG")
            onoff.append(set(names))
        if onoff[0] & onoff[1]:
            raise Unsupported("ON と OFF に同じ OCG")
        if "/Order" in config:
            self.validate_order(config.raw_get("/Order"))
        for group in array(config.get("/RBGroups", ArrayObject()), "RBGroups"):
            names = [self.owner(ref) for ref in array(group, "RBGroups 内のグループ")]
            if len(names) != len(set(names)):
                raise Unsupported("RBGroups に OCG 重複")
        # Traverse all config objects, validating registered OCGs and cycles.
        Canonicalizer(self).value(config)

    def validate_order(self, obj, active=frozenset(), depth=0):
        values = array(obj, "Order")
        if id(values) in active or depth > 50:
            raise Unsupported("Order の循環または深度超過")
        active = active | {id(values)}
        for index, value in enumerate(values):
            resolved = resolve(value)
            if isinstance(resolved, ArrayObject):
                self.validate_order(resolved, active, depth + 1)
            elif isinstance(resolved, TextStringObject) and index == 0:
                continue
            else:
                self.owner(value)

    @staticmethod
    def validate_intent(value):
        value = resolve(value)
        values = value if isinstance(value, ArrayObject) else [value]
        if not values or any(not isinstance(resolve(v), NameObject) for v in values):
            raise Unsupported("OCG Intent が不正")
