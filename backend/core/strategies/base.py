import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, IO


@dataclass
class StrategyResult:
    """Output of a strategy run.

    Two modes:

    - **In-memory** (default): `output_tables` is keyed by target doctype
      (e.g. 'Item', 'Sales Invoice') and holds the Frappe-Data-Import-
      shaped rows in Python lists. Simple and self-contained — fine for
      small datasets.

    - **Disk-streaming**: when `use_disk_staging(dir)` is called before
      transform, every emitted row is written immediately to a per-
      doctype JSONL file under that dir and **never accumulates in RAM**.
      Audit/writer downstream consume the JSONL files. This keeps peak
      memory bounded during emit when datasets are large.

    The `__audit_report__` / `__migration_setup_checklist__` synthetic
    "doctypes" are always kept in memory regardless of mode — they're
    small and the response payload needs them inline.

    `warnings` are non-fatal observations; `errors` are rows the strategy
    chose to drop with a reason; `stats` accumulates per-emit counters.
    """

    output_tables: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)

    # -- disk-streaming state --------------------------------------------------
    _staging_dir: str | None = None
    _writers: dict[str, IO[str]] = field(default_factory=dict)
    _row_counts: dict[str, int] = field(default_factory=dict)

    def use_disk_staging(self, staging_dir: str) -> None:
        os.makedirs(staging_dir, exist_ok=True)
        self._staging_dir = staging_dir

    def warn(self, source: str, message: str, **extra: Any) -> None:
        self.warnings.append({"source": source, "message": message, **extra})

    def fail(self, source: str, error: str, **extra: Any) -> None:
        self.errors.append({"source": source, "error": error, **extra})

    def bump(self, key: str, by: int = 1) -> None:
        self.stats[key] = self.stats.get(key, 0) + by

    def emit(self, doctype: str, row: dict[str, Any]) -> None:
        # Synthetic artifacts (audit, checklist) always stay in memory —
        # they're small and the response payload needs them inline.
        if doctype.startswith("__") or self._staging_dir is None:
            self.output_tables.setdefault(doctype, []).append(row)
            self._row_counts[doctype] = self._row_counts.get(doctype, 0) + 1
            return
        writer = self._writers.get(doctype)
        if writer is None:
            path = os.path.join(self._staging_dir, _safe_doctype(doctype) + ".jsonl")
            writer = open(path, "w", encoding="utf-8")
            self._writers[doctype] = writer
        writer.write(json.dumps(row, ensure_ascii=False))
        writer.write("\n")
        self._row_counts[doctype] = self._row_counts.get(doctype, 0) + 1

    def close_files(self) -> None:
        for writer in self._writers.values():
            try:
                writer.close()
            except Exception:
                pass
        self._writers.clear()

    def doctype_counts(self) -> dict[str, int]:
        """Per-doctype emit counts, regardless of in-memory vs disk mode."""
        return {
            dt: count
            for dt, count in self._row_counts.items()
            if not dt.startswith("__")
        }

    def docs_for(self, doctype: str) -> list[dict[str, Any]]:
        """Return all emitted rows for `doctype` (in-memory or from disk)."""
        in_mem = self.output_tables.get(doctype)
        if in_mem:
            return in_mem
        if self._staging_dir is None:
            return []
        path = os.path.join(self._staging_dir, _safe_doctype(doctype) + ".jsonl")
        if not os.path.exists(path):
            return []
        # Flush the writer so all rows are on disk before reading back.
        writer = self._writers.get(doctype)
        if writer is not None:
            writer.flush()
        rows: list[dict[str, Any]] = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        return rows

    def staging_dir(self) -> str | None:
        return self._staging_dir


def _safe_doctype(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in name)


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
        staging_dir: str | None = None,
    ) -> StrategyResult:
        """Run the strategy; return a StrategyResult.

        If `staging_dir` is provided, the implementation should call
        `result.use_disk_staging(staging_dir)` BEFORE emitting any rows
        so per-doctype output streams to JSONL on disk and never
        accumulates in RAM.
        """
        ...
