from typing import Any

from core.strategies.base import StrategyResult, TransformStrategy
from core.strategies.erpnext_mirror.accounts import emit_accounts
from core.strategies.erpnext_mirror.opening_balances import emit_opening_balances
from core.strategies.erpnext_shared.audit import emit_audit
from core.strategies.erpnext_shared.context import Context
from core.strategies.erpnext_shared.employees import emit_employees
from core.strategies.erpnext_shared.items import emit_item_prices, emit_items
from core.strategies.erpnext_shared.masters import emit_bank_masters, emit_item_masters
from core.strategies.erpnext_shared.parties import emit_customers, emit_suppliers
from core.strategies.erpnext_shared.stock_moves import emit_stock_opening


class ErpnextMirrorStrategy(TransformStrategy):
    """Convert Al Arabi legacy schema → ERPnext v16, preserving the legacy
    chart of accounts as-is.

    The Al Arabi tree (~3,500 accounts, hierarchical Arabic naming) is
    emitted unchanged; opening balances are posted per-account with a
    1:1 correspondence to legacy `ACCOUNTT`.
    """

    name = "erpnext_mirror"
    label = "ERPnext Mirror"
    description = (
        "Mirrors the Al Arabi chart of accounts into ERPnext, preserving "
        "the Arabic hierarchy. Opening balances are emitted per-leaf so "
        "every legacy ACCOUNTID round-trips to a real GL account."
    )
    tier = "S"
    kind = "OFFICIAL"
    stats = {
        "target_doctypes": 13,
        "target_fields": 150,
        "source_tables": 20,
        "fit_score": 94,
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

        active = ctx.config.selected_entities

        if "items" in active:
            emit_item_masters(ctx)
            emit_items(ctx)
            emit_item_prices(ctx)
        if "bank_accounts" in active:
            emit_bank_masters(ctx)
        if "customers" in active:
            emit_customers(ctx)
        if "suppliers" in active:
            emit_suppliers(ctx)
        if "chart_of_accounts" in active:
            emit_accounts(ctx)
        if "opening_balances" in active:
            emit_opening_balances(ctx)
        if "opening_stock" in active:
            emit_stock_opening(ctx)
        if "employees" in active:
            emit_employees(ctx)

        for tbl in list(ctx.legacy.keys()):
            ctx.free_table(tbl)

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
