"""Migration entities — coherent slices the user can opt into.

Each entity is one logical chunk of ERPnext data (Customers, Items, Bank
Accounts, …). The strategy orchestrator runs only the emit phases for
the entities the user selected, plus their transitive dependencies.
Empty / unset selection means "everything".
"""

from typing import Iterable

ENTITIES: dict[str, dict] = {
    "customers": {"label": "Customers", "depends_on": []},
    "suppliers": {"label": "Suppliers", "depends_on": []},
    "items": {"label": "Items", "depends_on": []},
    "chart_of_accounts": {"label": "Chart of Accounts", "depends_on": []},
    "bank_accounts": {"label": "Bank Accounts", "depends_on": ["chart_of_accounts"]},
    "employees": {"label": "Employees", "depends_on": []},
    "opening_stock": {"label": "Opening Stock", "depends_on": ["items"]},
    "opening_balances": {
        "label": "Opening Balances",
        "depends_on": ["customers", "suppliers", "chart_of_accounts", "bank_accounts"],
    },
}

ALL_ENTITIES: list[str] = list(ENTITIES.keys())


def resolve_dependencies(selected: Iterable[str] | None) -> frozenset[str]:
    """Return the entity set including transitive deps.

    Empty / None means full migration → everything. Unknown names are
    silently dropped so a stale frontend selection doesn't crash the run.
    """
    if not selected:
        return frozenset(ALL_ENTITIES)
    valid = {e for e in selected if e in ENTITIES}
    if not valid:
        return frozenset(ALL_ENTITIES)
    pending = list(valid)
    while pending:
        cur = pending.pop()
        for dep in ENTITIES[cur]["depends_on"]:
            if dep not in valid:
                valid.add(dep)
                pending.append(dep)
    return frozenset(valid)


def descriptors() -> list[dict]:
    """Frontend-shaped list for the entity picker."""
    return [
        {"id": eid, "label": meta["label"], "depends_on": meta["depends_on"]}
        for eid, meta in ENTITIES.items()
    ]
