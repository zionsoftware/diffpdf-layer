"""Bounded Unicode decoding for the optional font-only comparison.

No extraction fallback, glyph guessing, font installation or external tools.
An exact match does not need decoding; a font-only match always does.
"""
from hashlib import sha256
import re

from pypdf._codecs import adobe_glyphs, charset_encoding
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, NumberObject, StreamObject

from .model import Content, Unsupported
from .normalize import Canonicalizer, array, dictionary, resolve, stream_data

BASE14 = {"Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Helvetica-BoldOblique",
          "Times-Roman", "Times-Bold", "Times-Italic", "Times-BoldItalic",
          "Courier", "Courier-Bold", "Courier-Oblique", "Courier-BoldOblique"}
TOKEN = re.compile(rb"<[0-9a-fA-F\s]+>|\[|\]")
FONT_KEYS = {"/Type", "/Subtype", "/BaseFont", "/Name", "/FirstChar", "/LastChar", "/Widths", "/FontDescriptor", "/Encoding", "/ToUnicode", "/DescendantFonts"}
CID_KEYS = {"/Type", "/Subtype", "/BaseFont", "/CIDSystemInfo", "/FontDescriptor", "/DW", "/W", "/DW2", "/W2", "/CIDToGIDMap"}
DESCRIPTOR_KEYS = {"/Type", "/FontName", "/FontFamily", "/FontStretch", "/FontWeight", "/Flags", "/FontBBox", "/ItalicAngle", "/Ascent", "/Descent", "/Leading", "/CapHeight", "/XHeight", "/StemV", "/StemH", "/AvgWidth", "/MaxWidth", "/MissingWidth", "/FontFile", "/FontFile2", "/FontFile3", "/CharSet", "/Style", "/Lang", "/FD", "/CIDSet", "/FSType"}


def validate_descriptor(font):
    if "/FontDescriptor" in font:
        descriptor = dictionary(font["/FontDescriptor"], "FontDescriptor")
        if set(descriptor) - DESCRIPTOR_KEYS:
            raise Unsupported("未対応の FontDescriptor 属性")


def internal_name(font):
    name = str(font.get("/BaseFont", "不明"))
    return re.sub(r"^/?[A-Z]{6}\+", "", name).lstrip("/")


def _hex(token):
    if not token.startswith(b"<"):
        raise Unsupported("ToUnicode: 16進文字列が必要")
    data = bytes.fromhex(token[1:-1].decode("ascii"))
    if not data or len(data) > 16:
        raise Unsupported("ToUnicode: コード長が対応範囲外")
    return data


def unicode_map(stream):
    if not isinstance(resolve(stream), StreamObject):
        raise Unsupported("ToUnicode がストリームではありません")
    if "/UseCMap" in resolve(stream):
        raise Unsupported("ToUnicode UseCMap は未対応")
    data = stream_data(resolve(stream))[0]
    data = re.sub(rb"%[^\r\n]*", b"", data)
    if re.search(rb"\b(usecmap|begincidchar|begincidrange|beginnotdefchar|beginnotdefrange)\b", data):
        raise Unsupported("ToUnicode の継承・CID・notdef 条件は未対応")
    mapping, spaces = {}, []
    blocks = list(re.finditer(rb"(\d+)\s+begin(codespacerange|bfchar|bfrange)\b(.*?)\bend\2\b", data, re.S))
    if len(re.findall(rb"\bbegin(?:codespacerange|bfchar|bfrange)\b", data)) != len(blocks):
        raise Unsupported("ToUnicode ブロックが閉じていません")
    for block in blocks:
        count, kind, body = int(block[1]), block[2], block[3]
        tokens = TOKEN.findall(body)
        if TOKEN.sub(b"", body).strip() or count > 65536:
            raise Unsupported("ToUnicode に未対応の構文")
        pos = 0
        for _ in range(count):
            if pos + 2 > len(tokens):
                raise Unsupported("ToUnicode の要素数不足")
            lo, hi = _hex(tokens[pos]), _hex(tokens[pos+1])
            pos += 2
            if kind == b"codespacerange":
                if len(lo) != len(hi) or lo > hi or len(lo) > 4:
                    raise Unsupported("ToUnicode codespace が不正")
                spaces.append((lo, hi))
                continue
            if kind == b"bfchar":
                pairs = [(lo, hi)]
            else:
                if len(lo) != len(hi) or lo > hi:
                    raise Unsupported("ToUnicode bfrange が不正")
                size = int.from_bytes(hi) - int.from_bytes(lo) + 1
                if size > 65536 or pos >= len(tokens):
                    raise Unsupported("ToUnicode 範囲の上限超過または要素不足")
                if tokens[pos] == b"[":
                    end = pos + size + 1
                    if end >= len(tokens) or tokens[end] != b"]":
                        raise Unsupported("ToUnicode 範囲配列の要素数が不正")
                    destinations = [_hex(t) for t in tokens[pos+1:end]]
                    pos = end + 1
                else:
                    first = _hex(tokens[pos])
                    pos += 1
                    destinations = [(int.from_bytes(first)+i).to_bytes(len(first)) for i in range(size)]
                pairs = [((int.from_bytes(lo)+i).to_bytes(len(lo)), dest) for i, dest in enumerate(destinations)]
            for source, destination in pairs:
                text = destination.decode("utf-16-be", errors="strict")
                if not text or "\ufffd" in text or source in mapping:
                    raise Unsupported("ToUnicode が空・重複・不正な文字マッピング")
                mapping[source] = text
                if len(mapping) > 65536:
                    raise Unsupported("ToUnicode マッピングの上限超過")
        if pos != len(tokens):
            raise Unsupported("ToUnicode の要素数が宣言と不一致")
    if not spaces or not mapping:
        raise Unsupported("ToUnicode のコード範囲または文字マッピング不足")
    for source in mapping:
        if sum(len(source) == len(lo) and lo <= source <= hi for lo, hi in spaces) != 1:
            raise Unsupported("ToUnicode のコード範囲が曖昧または不一致")
    return mapping, spaces


class Font:
    def __init__(self, obj, normal=None):
        self.obj = dictionary(obj, "Font")
        if self.obj.get("/Subtype") not in {"/Type1", "/TrueType", "/Type0", "/MMType1"}:
            raise Unsupported("未対応の Font subtype")
        if set(self.obj) - FONT_KEYS:
            raise Unsupported("未対応の Font 属性")
        validate_descriptor(self.obj)
        if self.obj.get("/Subtype") == "/Type0":
            descendants = array(self.obj.get("/DescendantFonts"), "DescendantFonts")
            if len(descendants) != 1:
                raise Unsupported("DescendantFonts の個数が不正")
            descendant = dictionary(descendants[0], "CIDFont")
            if set(descendant) - CID_KEYS or descendant.get("/Subtype") not in {"/CIDFontType0", "/CIDFontType2"}:
                raise Unsupported("未対応の CIDFont 属性または種類")
            validate_descriptor(descendant)
        self.exact = (normal or Canonicalizer()).value(self.obj)
        self.name = internal_name(self.obj)
        self.digest = sha256(repr(self.exact).encode("utf-8")).hexdigest()
        self.mapping = None
        self.decode_error = ""
        try:
            self.mapping, self.spaces = self._mapping()
        except Exception as exc:
            self.decode_error = f"フォント {self.name}: 文字内容を安全に復元できません ({exc})"

    def value(self):
        return Content(("font", self.exact), ("font",), ((self.name, self.digest),))

    def _mapping(self):
        font = self.obj
        if font.get("/Subtype") == "/Type0" and font.get("/Encoding") != "/Identity-H":
            raise Unsupported("複合フォントは Identity-H のみ文字復元対応")
        if "/ToUnicode" in font:
            return unicode_map(font["/ToUnicode"])
        if font.get("/Subtype") == "/Type0":
            raise Unsupported("CID フォントの ToUnicode がありません")
        encoding = resolve(font.get("/Encoding"))
        if encoding is None:
            descriptor = dictionary(font.get("/FontDescriptor", DictionaryObject()))
            embedded = any(key in descriptor for key in ("/FontFile", "/FontFile2", "/FontFile3"))
            if self.name not in BASE14 or embedded or font.get("/Subtype") != "/Type1":
                raise Unsupported("フォント固有の暗黙エンコーディング")
            encoding = NameObject("/StandardEncoding")
        differences = []
        if isinstance(encoding, DictionaryObject):
            if set(encoding) - {"/Type", "/BaseEncoding", "/Differences"}:
                raise Unsupported("未対応の Encoding 属性")
            differences = array(encoding.get("/Differences", ArrayObject()), "Encoding Differences")
            encoding = encoding.get("/BaseEncoding")
        if encoding not in {"/StandardEncoding", "/WinAnsiEncoding", "/MacRomanEncoding"}:
            raise Unsupported("未対応の Encoding")
        mapping = {bytes([i]): c for i, c in enumerate(charset_encoding[encoding]) if c and c != "\ufffd" and not c.startswith("/")}
        code = None
        for value in differences:
            value = resolve(value)
            if isinstance(value, NumberObject):
                code = int(value)
            else:
                if code is None or not 0 <= code <= 255 or not isinstance(value, NameObject):
                    raise Unsupported("Encoding Differences が不正")
                glyph = adobe_glyphs.get(str(value))
                if glyph is None:
                    mapping.pop(bytes([code]), None)
                else:
                    mapping[bytes([code])] = glyph
                code += 1
        return mapping, [(b"\x00", b"\xff")]

    def decode(self, data, word_space=0):
        if self.mapping is None:
            raise Unsupported(self.decode_error)
        data = bytes(data)
        result, offset = [], 0
        while offset < len(data):
            lengths = {len(lo) for lo, hi in self.spaces if len(data[offset:offset+len(lo)]) == len(lo) and lo <= data[offset:offset+len(lo)] <= hi}
            if len(lengths) != 1:
                raise Unsupported(f"フォント {self.name}: 文字コード範囲が曖昧")
            length = next(iter(lengths))
            code = data[offset:offset+length]
            if code not in self.mapping or any(ord(c) < 32 for c in self.mapping[code]):
                raise Unsupported(f"フォント {self.name}: 未知の文字コード")
            # Preserve character-code clusters. A ligature mapped to two
            # Unicode characters must not be confused with two positioned
            # glyphs. Tw applies only to the single-byte code 0x20.
            result.append((self.mapping[code], code == b" ") if word_space else self.mapping[code])
            offset += length
        return tuple(result)


def text_value(data, font, normal, word_space=0):
    exact = normal.value(data)
    try:
        if font is None:
            raise Unsupported("文字描画の有効な Tf がありません")
        return Content(exact, ("unicode-clusters", font.decode(data, word_space)))
    except Exception as exc:
        return Content(exact, ("unresolved-text", exact), font_errors=(str(exc),))
