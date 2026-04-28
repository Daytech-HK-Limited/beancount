"""Serialization helpers for beancount types."""

import datetime
from decimal import Decimal


def serialize_amount(amount):
    if amount is None:
        return None
    return {"number": str(amount.number), "currency": amount.currency}


def serialize_cost(cost):
    if cost is None:
        return None
    return {
        "number": str(cost.number),
        "currency": cost.currency,
        "date": cost.date.isoformat() if cost.date else None,
        "label": cost.label,
    }


def serialize_inventory(inv):
    """Convert an Inventory to a list of position dicts."""
    result = []
    for pos in inv:
        result.append({
            "units": serialize_amount(pos.units),
            "cost": serialize_cost(pos.cost),
        })
    return result


def serialize_posting(posting):
    return {
        "account": posting.account,
        "units": serialize_amount(posting.units),
        "cost": serialize_cost(posting.cost),
        "price": serialize_amount(posting.price),
        "flag": posting.flag,
    }


def serialize_transaction(txn):
    return {
        "date": txn.date.isoformat(),
        "flag": txn.flag,
        "payee": txn.payee,
        "narration": txn.narration,
        "tags": sorted(txn.tags),
        "links": sorted(txn.links),
        "postings": [serialize_posting(p) for p in txn.postings],
        "meta": {
            "filename": txn.meta.get("filename"),
            "lineno": txn.meta.get("lineno"),
        },
    }
