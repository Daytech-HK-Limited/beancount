"""GET /ledgers/{ledger_id}/balances — account balances with optional date and glob filter."""

import datetime
import fnmatch
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query

from beancount.core import realization, data as bdata
from server.routes.deps import get_ledger
from server.cache import get_realized
from server.utils import serialize_inventory

logger = logging.getLogger(__name__)
router = APIRouter()


def _iter_matching_accounts(real_root, pattern: Optional[str]):
    for real_account in realization.iter_children(real_root):
        if not real_account.account:
            continue
        if pattern is None or fnmatch.fnmatch(real_account.account, pattern):
            yield real_account


@router.get("/balances")
def get_balances(
    ledger=Depends(get_ledger),
    account: Optional[str] = Query(None, description="Account glob pattern, e.g. Assets:*"),
    date: Optional[datetime.date] = Query(None, description="Balance as of this date (YYYY-MM-DD)"),
):
    entries, _, _ = ledger

    if date is not None:
        scoped = list(bdata.iter_entry_dates(
            entries, datetime.date.min, date + datetime.timedelta(days=1)
        ))
        real_root = realization.realize(scoped)
    else:
        real_root = get_realized(entries)

    result = []
    for real_account in _iter_matching_accounts(real_root, account):
        if not real_account.balance.is_empty():
            result.append({
                "account": real_account.account,
                "balance": serialize_inventory(real_account.balance),
            })

    result.sort(key=lambda r: r["account"])
    return {"balances": result, "count": len(result)}
