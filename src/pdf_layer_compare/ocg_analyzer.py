from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, NameObject, TextStringObject

from .model import Unsupported
from .normalize import Canonicalizer, array, dictionary, resolve


class OCGAnalyzer:
    def __init__(self, root):
        self.groups = {}
        self.by_object = {}
        self.errors = {}
        self.global_errors = []
        self.states = {}
        self.registry_complete = False
        try:
            self.load(root)
        except Exception as exc:
            self.global_errors.append(str(exc))

    def load(self, root):
        props = dictionary(root.get("/OCProperties", DictionaryObject()), "OCProperties")
        if not props:
            self.registry_complete = True
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
                self.errors.setdefault(str(name), []).append(f"レイヤー名が重複: {name}")
            self.groups[str(name)] = group
            self.by_object[id(group)] = str(name)
            try:
                if set(group) - {"/Type", "/Name", "/Intent", "/Usage"}:
                    raise Unsupported(f"OCG {name}: 未対応の属性")
                if "/Intent" in group:
                    self.validate_intent(group["/Intent"])
                if "/Usage" in group:
                    self.validate_usage(group["/Usage"])
            except Exception as exc:
                self.errors.setdefault(str(name), []).append(str(exc))
        self.registry_complete = True
        default = dictionary(props.get("/D"), "OCG 既定設定 D")
        self.validate_config(default)
        for config in array(props.get("/Configs", ArrayObject()), "Configs"):
            self.validate_config(dictionary(config))
        configs = [default, *array(props.get("/Configs", ArrayObject()), "Configs")]
        for name, group in self.groups.items():
            self.states[name] = (Canonicalizer().value(group), tuple(self.group_config(dictionary(c), name) for c in configs))

    def group_config(self, config, name):
        """Project visibility/locking/automatic state onto its actual group."""
        normal = Canonicalizer(self)
        selected = lambda key: name in [self.owner(r) for r in array(config.get(key, ArrayObject()))]
        state = config.get("/BaseState", "/ON")
        if selected("/ON"):
            state = "/ON"
        if selected("/OFF"):
            state = "/OFF"
        automatic = []
        for raw in array(config.get("/AS", ArrayObject())):
            entry = dictionary(raw)
            if "/OCGs" not in entry or name in [self.owner(r) for r in array(entry["/OCGs"])]:
                automatic.append(normal.value(DictionaryObject({k: v for k, v in entry.items() if k != "/OCGs"})))
        radio = []
        for refs in array(config.get("/RBGroups", ArrayObject())):
            names = tuple(sorted(self.owner(r) for r in array(refs)))
            if name in names:
                radio.append(names)
        return (str(state), selected("/Locked"), tuple(automatic), tuple(sorted(radio)),
                normal.value(config.get("/Intent", NameObject("/View"))))

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
            self.validate_auto_state(config["/AS"])
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

    @staticmethod
    def validate_usage(value):
        usage = dictionary(value, "OCG Usage")
        if set(usage) - {"/View", "/Print", "/Export"}:
            raise Unsupported("OCG Usage の条件 (言語・ズーム等) は未対応")
        for category, value in usage.items():
            item = dictionary(value, f"Usage {category}")
            state_key = category + "State"
            if set(item) != {state_key} or item[state_key] not in {"/ON", "/OFF"}:
                raise Unsupported(f"Usage {category}: 未対応または不正な状態")

    def validate_auto_state(self, value):
        # Compare these conditions exactly; do not assign a drawing to a layer
        # by evaluating its current on/off state. OCMD remains unsupported.
        entries = array(value, "OCG AS")
        if not entries:
            raise Unsupported("OCG AS が空です")
        for value in entries:
            entry = dictionary(value, "AS entry")
            if set(entry) - {"/Event", "/Category", "/OCGs"}:
                raise Unsupported("OCG AS: 未対応のキー")
            if entry.get("/Event") not in {"/View", "/Print", "/Export"}:
                raise Unsupported("OCG AS: 未対応のイベント")
            categories = array(entry.get("/Category"), "AS Category")
            if not categories or any(c not in {"/View", "/Print", "/Export"} for c in categories):
                raise Unsupported("OCG AS: 未対応の条件")
            if "/OCGs" in entry:
                refs = array(entry["/OCGs"], "AS OCGs")
                names = [self.owner(ref) for ref in refs]
                if not names or len(names) != len(set(names)):
                    raise Unsupported("OCG AS: 空または重複する OCG")
