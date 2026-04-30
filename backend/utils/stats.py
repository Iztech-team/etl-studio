from typing import Any, Dict


class StatsEngine:
    def __init__(self, session: Dict[str, Any]):
        self.session = session

    def compute(self) -> Dict[str, Any]:
        raw = self.session.get("raw", {})
        transformed = self.session.get("transformed", {})
        load_result = self.session.get("load_result", {})
        validation = self.session.get("validation", {})

        raw_tables = raw.get("tables", {})
        t_tables = (
            transformed.get("tables", {}) if isinstance(transformed, dict) else {}
        )

        total_in = sum(len(v) for v in raw_tables.values())
        total_out = sum(len(v) for v in t_tables.values()) if t_tables else total_in

        table_stats = {}
        for t, rows in raw_tables.items():
            target = t
            out_rows = len(t_tables.get(target, rows))
            table_stats[t] = {
                "rows_in": len(rows),
                "rows_out": out_rows,
                "columns": len(rows[0]) if rows else 0,
                "duplicates": validation.get("duplicate_counts", {}).get(t, 0),
            }

        # Quality score: start at 100, penalise issues
        issues = validation.get("issues", [])
        errors = sum(1 for i in issues if i.get("level") == "error")
        warnings = sum(1 for i in issues if i.get("level") == "warning")
        quality = max(0.0, 100.0 - errors * 20 - warnings * 5)

        stage = "idle"
        if load_result:
            stage = "loaded"
        elif transformed:
            stage = "transformed"
        elif validation:
            stage = "validated"
        elif raw_tables:
            stage = "extracted"

        return {
            "pipeline_stage": stage,
            "total_records_in": total_in,
            "total_records_out": total_out,
            "tables": table_stats,
            "timing": {},
            "quality_score": round(quality, 1),
        }
