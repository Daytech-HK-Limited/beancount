"""GET /ledgers/{ledger_id}/report/* — period financial reports."""

import datetime
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query

from beancount.core import realization, data as bdata
from beancount.parser import options as boptions
from server.routes.deps import get_ledger, get_ledger_with_root
from server.utils import serialize_inventory

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/report/balance_sheet")
def balance_sheet(
    ledger=Depends(get_ledger_with_root),
    date: Optional[datetime.date] = Query(None, description="As-of date (YYYY-MM-DD); defaults to all entries"),
):
    entries, _, options_map, real_root = ledger
    account_types = boptions.get_account_types(options_map)

    if date is not None:
        scoped = list(bdata.iter_entry_dates(
            entries, datetime.date.min, date + datetime.timedelta(days=1)
        ))
        real_root = realization.realize(scoped)
    # else: use pre-computed real_root

    assets, liabilities, equity = [], [], []
    for ra in realization.iter_children(real_root):
        if not ra.account or ra.balance.is_empty():
            continue
        entry = {"account": ra.account, "balance": serialize_inventory(ra.balance)}
        if ra.account.startswith(account_types.assets):
            assets.append(entry)
        elif ra.account.startswith(account_types.liabilities):
            liabilities.append(entry)
        elif ra.account.startswith(account_types.equity):
            equity.append(entry)

    return {
        "as_of": (date or datetime.date.today()).isoformat(),
        "assets":      sorted(assets,      key=lambda r: r["account"]),
        "liabilities": sorted(liabilities, key=lambda r: r["account"]),
        "equity":      sorted(equity,      key=lambda r: r["account"]),
    }


@router.get("/report/income")
def income_statement(
    ledger=Depends(get_ledger),
    date_from: Optional[datetime.date] = Query(None, description="Period start inclusive (YYYY-MM-DD)"),
    date_to: Optional[datetime.date] = Query(None, description="Period end inclusive (YYYY-MM-DD); defaults to today"),
):
    entries, _, options_map = ledger
    account_types = boptions.get_account_types(options_map)

    period_end = (date_to or datetime.date.today()) + datetime.timedelta(days=1)
    scoped = list(bdata.iter_entry_dates(entries, date_from or datetime.date.min, period_end))
    real_root = realization.realize(scoped)

    income, expenses = [], []
    for ra in realization.iter_children(real_root):
        if not ra.account or ra.balance.is_empty():
            continue
        entry = {"account": ra.account, "balance": serialize_inventory(ra.balance)}
        if ra.account.startswith(account_types.income):
            income.append(entry)
        elif ra.account.startswith(account_types.expenses):
            expenses.append(entry)

    return {
        "date_from": date_from.isoformat() if date_from else None,
        "date_to": (period_end - datetime.timedelta(days=1)).isoformat(),
        "income":   sorted(income,   key=lambda r: r["account"]),
        "expenses": sorted(expenses, key=lambda r: r["account"]),
    }
