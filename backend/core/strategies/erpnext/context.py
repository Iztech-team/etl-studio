"""Per-run context bundling config, legacy lookups, and result accumulator.

Built once at the top of `ErpnextStrategy.transform`. Domain modules read
from `ctx.legacy` / `ctx.accounts_by_id` / etc. and emit through
`ctx.result.emit(...)`. Keeps domain module signatures small and uniform.
"""
from dataclasses import dataclass, field
from typing import Any

from core.strategies.base import StrategyResult
from core.strategies.erpnext.common import (
    DEFAULT_CURRENCY,
    clean_str,
    customer_id,
    index_by,
    supplier_id,
    with_abbr,
)


@dataclass
class Config:
    company_name: str
    company_abbr: str
    country: str = "Palestinian Territory"
    default_currency: str = DEFAULT_CURRENCY
    opening_date: str | None = None
    summarize_walkin_sales: bool = True
    include_legacy_fields: bool = True

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Config":
        return cls(
            company_name=clean_str(raw.get("company_name")) or "Al Arabi",
            company_abbr=clean_str(raw.get("company_abbr")) or "ALA",
            country=clean_str(raw.get("country")) or "Palestinian Territory",
            default_currency=clean_str(raw.get("default_currency")) or DEFAULT_CURRENCY,
            opening_date=clean_str(raw.get("opening_date")) or None,
            summarize_walkin_sales=bool(raw.get("summarize_walkin_sales", True)),
            include_legacy_fields=bool(raw.get("include_legacy_fields", True)),
        )


@dataclass
class Context:
    config: Config
    legacy: dict[str, list[dict]]
    result: StrategyResult

    # Master lookups, populated by `build()` for cheap in-loop joins.
    accounts_by_id: dict[str, dict] = field(default_factory=dict)
    units_by_name: dict[str, dict] = field(default_factory=dict)
    units_by_id: dict[str, dict] = field(default_factory=dict)
    currencies_by_id: dict[str, dict] = field(default_factory=dict)
    stores_by_id: dict[str, dict] = field(default_factory=dict)
    banks_by_id: dict[str, dict] = field(default_factory=dict)
    bank_accounts_by_id: dict[str, dict] = field(default_factory=dict)
    customer_account_ids: set[str] = field(default_factory=set)
    supplier_account_ids: set[str] = field(default_factory=set)

    @classmethod
    def build(
        cls,
        legacy: dict[str, list[dict]],
        config_dict: dict[str, Any],
        result: StrategyResult,
    ) -> "Context":
        cfg = Config.from_dict(config_dict)
        ctx = cls(config=cfg, legacy=legacy, result=result)
        ctx._build_lookups()
        return ctx

    def table(self, name: str) -> list[dict]:
        return self.legacy.get(name) or []

    def with_abbr(self, base: str) -> str:
        return with_abbr(base, self.config.company_abbr)

    def party_kind(self, account_id: Any) -> str | None:
        """Return 'customer' / 'supplier' / None for a legacy ACCOUNTID."""
        s = clean_str(account_id)
        if s in self.customer_account_ids:
            return "customer"
        if s in self.supplier_account_ids:
            return "supplier"
        return None

    def party_link(self, account_id: Any) -> tuple[str | None, str | None]:
        """Resolve an ACCOUNTID to (party_type, party_name)."""
        kind = self.party_kind(account_id)
        if kind == "customer":
            return "Customer", customer_id(account_id)
        if kind == "supplier":
            return "Supplier", supplier_id(account_id)
        return None, None

    # -- lookup construction --------------------------------------------------

    def _build_lookups(self) -> None:
        self.accounts_by_id = index_by(self.table("ACCOUNTT"), "ACCOUNTID")
        self.currencies_by_id = index_by(self.table("CURT"), "CURID")
        self.stores_by_id = index_by(self.table("STORET"), "STOREID")
        self.banks_by_id = index_by(self.table("BANKT"), "BANKID")
        self.bank_accounts_by_id = index_by(self.table("BANKACCOUNTT"), "BANKACCID")
        self._index_units()
        self._index_party_accounts()

    def _index_units(self) -> None:
        units = self.table("UNITT")
        self.units_by_id = index_by(units, "UNITID")
        # Index by both Arabic and English names so item.UNIT free-text matches.
        by_name: dict[str, dict] = {}
        for row in units:
            for field_name in ("UNITNAME", "UNITNAMEE", "UNITNAMEH"):
                key = clean_str(row.get(field_name))
                if key:
                    by_name.setdefault(key, row)
        self.units_by_name = by_name

    def _index_party_accounts(self) -> None:
        self.customer_account_ids = {
            clean_str(r.get("ACCOUNT"))
            for r in self.table("CUSTT")
            if clean_str(r.get("ACCOUNT"))
        }
        self.supplier_account_ids = {
            clean_str(r.get("ACCOUNT"))
            for r in self.table("SUPPLIERT")
            if clean_str(r.get("ACCOUNT"))
        }
