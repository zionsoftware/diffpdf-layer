from dataclasses import dataclass, field
from enum import StrEnum


class Status(StrEnum):
    MATCH = "一致"
    DIFFERENT = "不一致"
    UNKNOWN = "検証不能"


class Unsupported(ValueError):
    """Input cannot be safely interpreted within the supported PDF subset."""


@dataclass
class Snapshot:
    path: str
    names: tuple[str, ...] = ()
    ocg: object = None
    base: object = None
    layers: dict = field(default_factory=dict)
    composition: list = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    configuration_error: str = ""


@dataclass
class Result:
    left: str
    right: str
    component: str
    status: Status
    detail: str = ""


@dataclass
class Report:
    files: list[str]
    results: list[Result] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    configuration_ok: bool = False

    @property
    def status(self):
        if self.errors or any(r.status == Status.UNKNOWN for r in self.results):
            return Status.UNKNOWN
        if any(r.status == Status.DIFFERENT for r in self.results):
            return Status.DIFFERENT
        return Status.MATCH if self.results else Status.UNKNOWN
