from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar


@dataclass
class StrategyResult:
    """Output of a strategy run. `output_tables` is keyed by target doctype
    (e.g. 'Item', 'Sales Invoice') and holds Frappe-Data-Import-shaped rows.

    `warnings` are non-fatal observations the operator should review;
    `errors` are rows the strategy chose to drop with a reason.
    `stats` accumulates counters (rows emitted, skipped, fallbacks taken).
    """

    output_tables: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)

    def warn(self, source: str, message: str, **extra: Any) -> None:
        self.warnings.append({"source": source, "message": message, **extra})

    def fail(self, source: str, error: str, **extra: Any) -> None:
        self.errors.append({"source": source, "error": error, **extra})

    def bump(self, key: str, by: int = 1) -> None:
        self.stats[key] = self.stats.get(key, 0) + by

    def emit(self, doctype: str, row: dict[str, Any]) -> None:
        self.output_tables.setdefault(doctype, []).append(row)


class TransformStrategy(ABC):
    """Convert legacy source tables into a target schema's import format.

    Subclasses declare metadata (name/label/description/config_schema) as
    class attributes and implement `transform`. The registry surfaces the
    metadata to the API; `transform` is invoked once per pipeline run.
    """

    name: ClassVar[str] = ""
    label: ClassVar[str] = ""
    description: ClassVar[str] = ""
    config_schema: ClassVar[dict[str, Any]] = {}

    @abstractmethod
    def transform(
        self,
        tables: dict[str, list[dict[str, Any]]],
        config: dict[str, Any],
    ) -> StrategyResult: ...
