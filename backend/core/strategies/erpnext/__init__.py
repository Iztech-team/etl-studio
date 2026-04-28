from typing import Any

from core.strategies.base import StrategyResult, TransformStrategy


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
    label = "ERPnext (Al Arabi)"
    description = (
        "Transform Al Arabi legacy ERP data into ERPnext v16 Frappe Data Import CSVs. "
        "Targets a fresh ERPnext company; emits masters, items with barcodes, parties, "
        "chart of accounts, invoices (with returns), payments, journals, opening stock, "
        "and employees."
    )
    config_schema: dict[str, Any] = {
        "company_name": {
            "type": "string",
            "required": True,
            "label": "Company Name",
            "help": "Must already exist in ERPnext as a fresh company.",
        },
        "company_abbr": {
            "type": "string",
            "required": True,
            "label": "Company Abbreviation",
            "help": "Used in autonamed warehouses/accounts (e.g. 'Stores - ALA').",
        },
        "country": {
            "type": "string",
            "required": True,
            "default": "Palestinian Territory",
            "label": "Country",
        },
        "default_currency": {
            "type": "string",
            "default": "ILS",
            "label": "Default Currency",
        },
        "opening_date": {
            "type": "date",
            "required": True,
            "label": "Opening Date",
            "help": "Cutover date for opening balances and stock (e.g. 2026-01-01).",
        },
        "summarize_walkin_sales": {
            "type": "boolean",
            "default": True,
            "label": "Summarize walk-in sales",
            "help": (
                "Group anonymous walk-in sales into one Sales Invoice per "
                "(date × terminal). Named-customer sales remain per-invoice."
            ),
        },
    }

    def transform(
        self,
        tables: dict[str, list[dict[str, Any]]],
        config: dict[str, Any],
    ) -> StrategyResult:
        result = StrategyResult()
        # Domain modules wire in over the next slices:
        #   masters → items → parties → accounts → invoices → payments
        #   → journals → stock → employees → audit
        result.bump("legacy_tables_seen", len(tables))
        return result
