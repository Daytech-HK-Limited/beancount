"""GET /report/income and /report/balance_sheet — period financial reports."""

import datetime
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from beancount.core import realization, data as bdata
from beancount.parser import options as boptions
from server.state import state
from server.cache import get_realized
from server.utils import serialize_inventory

logger = logging.getLogger(__name__)
router = APIRouter()


def _realize_to_dict(real_root):
    """Serialize realized account tree to a flat list."""
    result = []
    for real_account in realization.iter_children(real_root):
        if not real_account.account:
            continue
        balance = real_account.balance
        if not balance.is_empty():
            result.append({
                "account": real_account.account,
                "balance": serialize_inventory(balance),
            })
    result.sort(key=lambda r: r["account"])
    return result


@router.get("/report/balance_sheet")
def balance_sheet(
    date: Optional[datetime.date] = Query(None, description="As-of date (YYYY-MM-DD); defaults to today"),
):
    """Return a balance sheet (assets, liabilities, equity) as of a given date."""
    entries, _, options_map = state.get()
    if not entries:
        raise HTTPException(status_code=503, detail="Ledger not yet loaded")

    account_types = boptions.get_account_types(options_map)

    if date is None:
        # No date filter: use cached full realization
        real_root = get_realized(entries)
    else:
        scoped = list(bdata.iter_entry_dates(entries, datetime.date.min, date + datetime.timedelta(days=1)))
        real_root = realization.realize(scoped)

    assets = []
    liabilities = []
    equity = []

    for real_account in realization.iter_children(real_root):
        acct = real_account.account
        if not acct:
            continue
        bal = real_account.balance
        if bal.is_empty():
            continue
        entry = {"account": acct, "balance": serialize_inventory(bal)}
        if acct.startswith(account_types.assets):
            assets.append(entry)
        elif acct.startswith(account_types.liabilities):
            liabilities.append(entry)
        elif acct.startswith(account_types.equity):
            equity.append(entry)

    return {
        "as_of": (date or datetime.date.today()).isoformat(),
        "assets": sorted(assets, key=lambda r: r["account"]),
        "liabilities": sorted(liabilities, key=lambda r: r["account"]),
        "equity": sorted(equity, key=lambda r: r["account"]),
    }


@router.get("/report/income")
def income_statement(
    date_from: Optional[datetime.date] = Query(None, description="Period start (YYYY-MM-DD)"),
    date_to: Optional[datetime.date] = Query(None, description="Period end (YYYY-MM-DD); defaults to today"),
):
    """Return income and expenses for a time period."""
    entries, _, options_map = state.get()
    if not entries:
        raise HTTPException(status_code=503, detail="Ledger not yet loaded")

    period_end = (date_to or datetime.date.today()) + datetime.timedelta(days=1)

    # Scope entries to the period
    if date_from is not None:
        scoped = list(bdata.iter_entry_dates(entries, date_from, period_end))
    else:
        scoped = list(bdata.iter_entry_dates(entries, datetime.date.min, period_end))

    account_types = boptions.get_account_types(options_map)
    real_root = realization.realize(scoped)

    income = []
    expenses = []

    for real_account in realization.iter_children(real_root):
        acct = real_account.account
        if not acct:
            continue
        bal = real_account.balance
        if bal.is_empty():
            continue
        entry = {"account": acct, "balance": serialize_inventory(bal)}
        if acct.startswith(account_types.income):
            income.append(entry)
        elif acct.startswith(account_types.expenses):
            expenses.append(entry)

    return {
        "date_from": date_from.isoformat() if date_from else None,
        "date_to": (period_end - datetime.timedelta(days=1)).isoformat(),
        "income": sorted(income, key=lambda r: r["account"]),
        "expenses": sorted(expenses, key=lambda r: r["account"]),
    }
