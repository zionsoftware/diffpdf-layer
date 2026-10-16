from dataclasses import dataclass, field
from enum import StrEnum


class Status(StrEnum):
    MATCH = "一致"
    FONT_ONLY = "一致（フォントのみ変更）"
    DIFFERENT = "不一致"
    ADDED = "新規追加"
    REMOVED = "削除"
    UNKNOWN = "検証不能"


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


@dataclass
class Report:
    files: list[str]
    results: list[Result] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
