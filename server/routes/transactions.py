"""GET /ledgers/{ledger_id}/transactions — filtered, paginated transaction history."""

import datetime
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query

from beancount.core import data as bdata
from server.routes.deps import get_ledger
from server.utils import serialize_transaction

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/transactions")
def get_transactions(
    ledger=Depends(get_ledger),
    account: Optional[str] = Query(None, description="Account substring (case-insensitive)"),
    date_from: Optional[datetime.date] = Query(None, description="Start date inclusive (YYYY-MM-DD)"),
    date_to: Optional[datetime.date] = Query(None, description="End date inclusive (YYYY-MM-DD)"),
    payee: Optional[str] = Query(None, description="Payee substring (case-insensitive)"),
    narration: Optional[str] = Query(None, description="Narration substring (case-insensitive)"),
    tag: Optional[str] = Query(None, description="Exact tag match"),
    flag: Optional[str] = Query(None, description="Flag character, e.g. * or !"),
    limit: int = Query(100, ge=1, le=10000, description="Max results to return"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
):
    entries, _, _ = ledger

    if date_from is not None or date_to is not None:
        begin = date_from or datetime.date.min
        end = (date_to + datetime.timedelta(days=1)) if date_to else datetime.date.max
        candidates = bdata.iter_entry_dates(entries, begin, end)
    else:
        candidates = iter(entries)

    txns = bdata.filter_txns(candidates)

    if account:
        account_lower = account.lower()
        txns = (t for t in txns if any(account_lower in p.account.lower() for p in t.postings))
    if payee:
        payee_lower = payee.lower()
        txns = (t for t in txns if t.payee and payee_lower in t.payee.lower())
    if narration:
        narration_lower = narration.lower()
        txns = (t for t in txns if narration_lower in t.narration.lower())
    if tag:
        txns = (t for t in txns if tag in t.tags)
    if flag:
        txns = (t for t in txns if t.flag == flag)

    result = []
    total_seen = 0
    for txn in txns:
        total_seen += 1
        if total_seen <= offset:
            continue
        if len(result) >= limit:
            break
        result.append(serialize_transaction(txn))

    return {"transactions": result, "count": len(result), "offset": offset, "limit": limit}
