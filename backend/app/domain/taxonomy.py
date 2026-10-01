"""Case category taxonomy: Type → Category → Subcategory.

This is what the webform's dropdowns are built from, and what queue matching
and the compensation matrix will key on later.

For now every tenant gets this default taxonomy. Later it becomes
tenant-configurable (stored per tenant, edited in the admin UI — see
docs/05-data-model.md, `caseSchemas`). The API shape won't change when that
happens, so the webform won't need to either.
"""

from typing import TypedDict


class Subcategory(TypedDict):
    name: str


class Category(TypedDict):
    name: str
    subcategories: list[Subcategory]


class CaseType(TypedDict):
    name: str
    categories: list[Category]


def _cat(name: str, *subs: str) -> Category:
    return {"name": name, "subcategories": [{"name": s} for s in subs]}


DEFAULT_TAXONOMY: list[CaseType] = [
    {
        "name": "Complaint",
        "categories": [
            _cat("Delivery", "Late delivery", "Missing package", "Wrong address"),
            _cat("Order", "Damaged item", "Wrong item", "Missing item"),
            _cat("Refund", "Refund not received", "Partial refund"),
            _cat("Employee experience", "Rude staff", "Unhelpful response"),
        ],
    },
    {
        "name": "Question",
        "categories": [
            _cat("Order", "Order status", "Change order"),
            _cat("Refund", "Refund status", "Refund policy"),
            _cat("Account", "Login issue", "Update details"),
        ],
    },
    {
        "name": "Compliment",
        "categories": [
            _cat("Employee experience", "Helpful staff"),
            _cat("Product", "Product quality"),
        ],
    },
]
