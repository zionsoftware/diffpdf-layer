from dataclasses import dataclass, field
from enum import StrEnum


class Status(StrEnum):
    MATCH = "一致"
    DIFFERENT = "不一致"
    UNKNOWN = "検証不能"


ROLES = ("担当", "確認", "審査", "承認")


class BusinessStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNVERIFIABLE"


@dataclass
class FileInfo:
    path: str
    role: str = ""
    sha256: str = ""
    modified_at: str = ""
    size_bytes: int | None = None
    error: str = ""

    @property
    def short_hash(self):
        return f"{self.sha256[:6]}-{self.sha256[6:12]}" if self.sha256 else "取得不能"


@dataclass
class PairSummary:
    left: str
    right: str
    overall: Status
    business: BusinessStatus
    required: list[str] = field(default_factory=list)
    allowed: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    left_role: str = ""
    right_role: str = ""


class Unsupported(ValueError):
    """Input cannot be safely interpreted within the supported PDF subset."""


@dataclass
class Content:
    """Exact structure first; font-neutral structure is only a second check."""
    exact: object
    semantic: object
    fonts: tuple = ()
    font_errors: tuple = ()


def combine(tag, values, *, unordered=False):
    values = list(values)
    exact = [v.exact for v in values]
    semantic = [v.semantic for v in values]
    if unordered:
        exact.sort(key=repr)
        semantic.sort(key=repr)
    return Content((tag, tuple(exact)), (tag, tuple(semantic)),
                   tuple(f for v in values for f in v.fonts),
                   tuple(e for v in values for e in v.font_errors))


@dataclass
class Group:
    values: list[Content] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def content(self):
        return combine("group", self.values)


BODY = "PDF本体"
UNLAYERED = "レイヤーなし"


def layer_key(name):
    return f"レイヤー: {name}"


@dataclass
class AuthorInfo:
    """Annotation /T record values, never authenticated user identities."""
    counts: dict[str, int] = field(default_factory=dict)
    unset_count: int = 0
    unreadable_count: int = 0
    complete: bool = True
    group_present: bool | None = True
    errors: list[str] = field(default_factory=list)

    def incomplete(self, reason):
        self.complete = False
        if reason not in self.errors:
            self.errors.append(reason)


@dataclass
class Snapshot:
    path: str
    names: tuple[str, ...] = ()
    ocg: object = None
    groups: dict[str, Group] = field(default_factory=dict)
    file_error: str = ""
    authors: dict[str, AuthorInfo] = field(default_factory=dict)
    file_info: FileInfo | None = None


@dataclass
class Result:
    left: str
    right: str
    component: str
    status: Status
    detail: str = ""
    font_changes: list[dict] = field(default_factory=list)
    reference_authors: AuthorInfo | None = None
    target_authors: AuthorInfo | None = None
    authors_changed: bool | None = None
    left_role: str = ""
    right_role: str = ""


@dataclass
class Report:
    files: list[str]
    results: list[Result] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    file_info: list[FileInfo] = field(default_factory=list)
    pairs: list[PairSummary] = field(default_factory=list)
    reference: str = ""
    layer_names: list[str] = field(default_factory=list)
    extra_names: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.reference and self.files:
            self.reference = self.files[-1]
        if not self.roles:
            self.roles = list(ROLES[:len(self.files)])
