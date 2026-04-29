from typing import Any

from core.strategies.base import StrategyResult, TransformStrategy
from core.strategies.erpnext.accounts import emit_accounts
from core.strategies.erpnext.audit import emit_audit
from core.strategies.erpnext.context import Context
from core.strategies.erpnext.invoices import emit_invoices
from core.strategies.erpnext.items import emit_item_prices, emit_items
from core.strategies.erpnext.journals import emit_journals
from core.strategies.erpnext.masters import emit_masters
from core.strategies.erpnext.parties import emit_parties
from core.strategies.erpnext.employees import emit_employees
from core.strategies.erpnext.payments import emit_payments
from core.strategies.erpnext.stock_moves import emit_stock_opening


class ErpnextStrategy(TransformStrategy):
    """Convert Al Arabi legacy schema → ERPnext v16 Frappe Data Import CSVs.

    Output is grouped by ERPnext doctype (Item, Customer, Sales Invoice, …).
    Mapping rationale lives in `.planning/research/erpnext-mapping.md`.

    The class is intentionally a thin orchestrator. Each domain
    (masters / items / parties / accounts / invoices / payments / journals /
    stock / employees) is implemented in a sibling module and dispatched
    here so the file stays readable as the migration grows.
    """

    name = "erpnext"
    label = "ERPnext"
    description = (
        "Standard ERPnext v16 doctype layout. Items, barcodes, customers, "
        "suppliers, accounts, invoices (with returns), payments, journals, "
        "opening stock, employees."
    )
    # Card-level metadata for the picker (tier / kind / stats).
    tier = "S"
    kind = "OFFICIAL"
    stats = {
        "target_doctypes": 17,    # how many ERPnext doctypes we emit
        "target_fields": 190,     # approx total fields across emitted shapes
        "source_tables": 30,      # legacy tables we consume
        "fit_score": 94,          # mapping confidence %
    }
    # Only fields the operator must decide remain in `config_schema`. Country
    # and default_currency live as defaults inside Config.from_dict so the
    # admin can override via API/file but the UI stays compact.
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
                "Required if you want post-migration traceback. Disable to skip "
                "the Customize Form setup step."
            ),
        },
    }

    def transform(
        self,
        tables: dict[str, list[dict[str, Any]]],
        config: dict[str, Any],
        staging_dir: str | None = None,
    ) -> StrategyResult:
        result = StrategyResult()
        if staging_dir:
            result.use_disk_staging(staging_dir)
        ctx = Context.build(tables, config, result)
        self._record_intake(ctx)
        emit_masters(ctx)
        emit_items(ctx)
        emit_item_prices(ctx)
        emit_parties(ctx)
        emit_accounts(ctx)
        emit_invoices(ctx)
        emit_payments(ctx)
        emit_journals(ctx)
        emit_stock_opening(ctx)
        emit_employees(ctx)
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
