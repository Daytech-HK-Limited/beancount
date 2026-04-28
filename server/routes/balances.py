"""GET /balances — account balances with optional date and glob filter."""

import datetime
import fnmatch
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from beancount.core import realization, data as bdata
from server.state import state
from server.cache import get_realized
from server.utils import serialize_inventory

logger = logging.getLogger(__name__)
router = APIRouter()


def _iter_matching_accounts(real_root, pattern: Optional[str]):
    """Yield (account_name, real_account) for all accounts matching pattern."""
    for real_account in realization.iter_children(real_root):
        if not real_account.account:
            continue
        if pattern is None or fnmatch.fnmatch(real_account.account, pattern):
            yield real_account


@router.get("/balances")
def get_balances(
    account: Optional[str] = Query(None, description="Account glob pattern, e.g. Assets:*"),
    date: Optional[datetime.date] = Query(None, description="Balance as of this date (YYYY-MM-DD)"),
):
    """Return account balances. Optionally filter by account glob and/or date."""
    entries, _, _ = state.get()
    if not entries:
        raise HTTPException(status_code=503, detail="Ledger not yet loaded")

    if date is not None:
        # Scope entries up to and including the given date
        scoped = list(bdata.iter_entry_dates(entries, datetime.date.min, date + datetime.timedelta(days=1)))
        real_root = realization.realize(scoped)
    else:
        real_root = get_realized(entries)

    result = []
    for real_account in _iter_matching_accounts(real_root, account):
        balance = real_account.balance
        if not balance.is_empty():
            result.append({
                "account": real_account.account,
                "balance": serialize_inventory(balance),
            })

    result.sort(key=lambda r: r["account"])
    return {"balances": result, "count": len(result)}
