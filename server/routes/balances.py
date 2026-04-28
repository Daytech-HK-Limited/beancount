"""GET /ledgers/{ledger_id}/balances — account balances with optional date and glob filter."""

import datetime
import fnmatch
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query

from beancount.core import realization, data as bdata
from server.routes.deps import get_ledger, get_ledger_with_root
from server.utils import serialize_inventory

logger = logging.getLogger(__name__)
router = APIRouter()


def _iter_matching_accounts(real_root, pattern: Optional[str]):
    for ra in realization.iter_children(real_root):
        if not ra.account:
            continue
        if pattern is None or fnmatch.fnmatch(ra.account, pattern):
            yield ra


@router.get("/balances")
def get_balances(
    ledger=Depends(get_ledger_with_root),
    account: Optional[str] = Query(None, description="Account glob pattern, e.g. Assets:*"),
    date: Optional[datetime.date] = Query(None, description="Balance as of this date (YYYY-MM-DD)"),
):
    entries, _, _, real_root = ledger

    if date is not None:
        # Date-scoped: build a temporary realization from the sliced entry window
        scoped = list(bdata.iter_entry_dates(
            entries, datetime.date.min, date + datetime.timedelta(days=1)
        ))
        real_root = realization.realize(scoped)
    # else: use the pre-computed real_root — no extra work needed

    result = [
        {"account": ra.account, "balance": serialize_inventory(ra.balance)}
        for ra in _iter_matching_accounts(real_root, account)
        if not ra.balance.is_empty()
    ]
    result.sort(key=lambda r: r["account"])
    return {"balances": result, "count": len(result)}
