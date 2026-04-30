from typing import Any

from core.strategies.base import StrategyResult, TransformStrategy


class ErpnextNativeStrategy(TransformStrategy):
    """Convert Al Arabi legacy schema → ERPnext v16, using ERPnext's
    standard (modular) chart of accounts.

    Unlike `ErpnextMirrorStrategy`, this strategy does NOT preserve the
    legacy Arabic tree. Each legacy leaf is classified into one of
    ERPnext's standard buckets (Sales, Cost of Goods Sold, Office Rent,
    etc.) and balances are aggregated per bucket instead of per legacy
    account. New transactions posted in ERPnext after cutover route
    through standard accounts, so built-in reports and auto-postings
    (depreciation, exchange gain/loss, COGS) work without remapping.

    NOT YET IMPLEMENTED — picker entry is reserved for the follow-up
    branch that builds the legacy → bucket mapping table.
    """

    name = "erpnext_native"
    label = "ERPnext Native"
    description = (
        "Targets ERPnext's standard chart of accounts. Aggregates legacy "
        "balances into ERPnext buckets so built-in reports and modules "
        "work out of the box. Loses per-legacy-account drilldown."
    )
    tier = "A"
    kind = "OFFICIAL"
    stats = {
        "target_doctypes": 13,
        "target_fields": 150,
        "source_tables": 20,
        "fit_score": 0,
    }
    config_schema: dict[str, Any] = {
        "company_name": {
            "type": "string",
            "required": True,
            "label": "Company Name",
        },
        "company_abbr": {
            "type": "string",
            "required": True,
            "label": "Abbreviation",
        },
        "opening_date": {
            "type": "date",
            "required": True,
            "label": "Opening Date",
        },
    }

    def transform(
        self,
        tables: dict[str, list[dict[str, Any]]],
        config: dict[str, Any],
        staging_dir: str | None = None,
        table_loader=None,
    ) -> StrategyResult:
        raise NotImplementedError(
            "ERPnext Native strategy is not yet implemented. "
            "Use 'ERPnext Mirror' for now, or pick up implementation on "
            "a follow-up branch — see CLAUDE notes for the mapping work."
        )
