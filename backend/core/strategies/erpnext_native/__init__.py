from typing import Any

from core.strategies.base import StrategyResult, TransformStrategy
from core.strategies.erpnext_native.accounts import emit_accounts
from core.strategies.erpnext_native.opening_balances import emit_opening_balances
from core.strategies.erpnext_shared.audit import emit_audit
from core.strategies.erpnext_shared.context import Context
from core.strategies.erpnext_shared.employees import emit_employees
from core.strategies.erpnext_shared.items import emit_item_prices, emit_items
from core.strategies.erpnext_shared.masters import emit_masters
from core.strategies.erpnext_shared.parties import emit_parties
from core.strategies.erpnext_shared.stock_moves import emit_stock_opening


class ErpnextNativeStrategy(TransformStrategy):
    """Convert Al Arabi legacy schema → ERPnext v16, using ERPnext's
    standard (modular) chart of accounts.

    Unlike `ErpnextMirrorStrategy`, this strategy does NOT preserve the
    legacy Arabic tree. Each legacy leaf is classified into one of
    ERPnext's standard buckets (Sales, Miscellaneous Expenses, etc.)
    and balances are aggregated per bucket instead of per legacy
    account.

    Phase 1 status: CLASS-only mapping. Most expense / income legacy
    leaves land in `Miscellaneous Expenses` / `Sales` until Phase 2
    adds NAME-based heuristics to split them per ERPnext leaf
    (Salary, Office Rent, Marketing Expenses, etc.).

    Assumes the admin creates the company first so ERPnext auto-creates
    the standard CoA. This strategy emits only the customs not in
    default (bank GL leaves, Cheques in Hand, VAT).
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
        "fit_score": 60,
    }
    config_schema: dict[str, Any] = {
        "company_name": {
            "type": "string",
            "required": True,
            "label": "Company Name",
            "help": "Must exist in ERPnext (or will be created with this name).",
        },
        "company_abbr": {
            "type": "string",
            "required": True,
            "label": "Abbreviation",
            "help": "Used in autonamed accounts/warehouses (e.g. 'Cash - ALA').",
        },
        "opening_date": {
            "type": "date",
            "required": True,
            "label": "Opening Date",
            "help": "Cutover date for opening balances and stock.",
        },
        "summarize_walkin_sales": {
            "type": "boolean",
            "default": True,
            "label": "Summarize walk-in sales",
            "help": "One Sales Invoice per (date × terminal) for anonymous sales.",
        },
        "include_legacy_fields": {
            "type": "boolean",
            "default": True,
            "label": "Include legacy_* fields",
            "help": (
                "Adds legacy_custid, cheque_owner_name, etc. as custom fields. "
                "Required if you want post-migration traceback."
            ),
        },
    }

    def transform(
        self,
        tables: dict[str, list[dict[str, Any]]],
        config: dict[str, Any],
        staging_dir: str | None = None,
        table_loader=None,
    ) -> StrategyResult:
        result = StrategyResult()
        if staging_dir:
            result.use_disk_staging(staging_dir)
        ctx = Context.build(tables, config, result, table_loader=table_loader)
        self._record_intake(ctx)

        emit_masters(ctx)
        ctx.free_table("UNITT")

        emit_items(ctx)
        emit_item_prices(ctx)
        ctx.free_table("CATEGORYT")
        ctx.free_table("CATPRICET")
        ctx.free_table("CATESYNONYMT")
        ctx.free_table("CATSUPPLIERT")
        ctx.free_table("CATDESCT")

        emit_parties(ctx)
        ctx.free_table("CONTACTST")

        emit_accounts(ctx)

        emit_opening_balances(ctx)
        ctx.free_table("CUSTT")
        ctx.free_table("SUPPLIERT")
        ctx.free_table("CHEQUET")
        for unused in (
            "CATESINVDOCT", "CATESRETINVDOCT", "CATESRETINVDOCDETT",
            "CATEPINVDOCT", "CATEPRETINVDOCT", "CATEPRETINVDOCDETT",
            "RECDOCT", "RECDOCDETT", "PAYDOCT", "PAYDOCDETT",
            "ENTRYDOCT", "ENTRYDOCDETT",
            "STARTENTRYDOCT", "STARTENTRYDOCDETT",
            "DNOTEDOCT", "DNOTEDOCDETT",
        ):
            ctx.free_table(unused)

        emit_stock_opening(ctx)
        ctx.free_table("CATSTORET")

        emit_employees(ctx)
        ctx.free_table("EMPLOYEET")
        ctx.free_table("ACCOUNTT")

        emit_audit(ctx)
        return result

    def _record_intake(self, ctx: Context) -> None:
        ctx.result.bump("legacy_tables_seen", len(ctx.legacy))
        ctx.result.bump("legacy_accounts", len(ctx.accounts_by_id))
        ctx.result.bump("legacy_units", len(ctx.units_by_id))
        ctx.result.bump("legacy_currencies", len(ctx.currencies_by_id))
        ctx.result.bump("legacy_stores", len(ctx.stores_by_id))
        ctx.result.bump("legacy_customer_accounts", len(ctx.customer_account_ids))
        ctx.result.bump("legacy_supplier_accounts", len(ctx.supplier_account_ids))
