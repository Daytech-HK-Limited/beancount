"""POST /ledgers/{ledger_id}/query — run arbitrary BQL against in-memory entries."""

import datetime
import decimal
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from server.routes.deps import get_ledger

logger = logging.getLogger(__name__)
router = APIRouter()


def _to_json(value):
    """Recursively convert beancount result values to JSON-safe primitives."""
    if value is None:
        return None
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, (set, frozenset)):
        return sorted(str(v) for v in value)
    try:
        from beancount.core.inventory import Inventory
        if isinstance(value, Inventory):
            return [_to_json(pos) for pos in value]
    except ImportError:
        pass
    if hasattr(value, "_asdict"):
        return {k: _to_json(v) for k, v in value._asdict().items()}
    if isinstance(value, (list, tuple)):
        return [_to_json(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _to_json(v) for k, v in value.items()}
    return value


class QueryRequest(BaseModel):
    sql: str


@router.post("/query")
def run_query(body: QueryRequest, ledger=Depends(get_ledger)):
    """Run a BQL query string against the named in-memory ledger.

    Requires the `beanquery` package (`pip install beanquery`).
    """
    try:
        from beanquery.query import run_query as bql_run_query
    except ImportError:
        raise HTTPException(
            status_code=501,
            detail="beanquery package is not installed. Run: pip install beanquery",
        )

    entries, _, options_map = ledger

    try:
        rtypes, rrows = bql_run_query(entries, options_map, body.sql)
    except Exception as exc:
        logger.warning("Query error: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc))

    columns = [col.name for col in rtypes]
    rows = [
        {col: _to_json(val) for col, val in zip(columns, row)}
        for row in rrows
    ]
    return {"columns": columns, "rows": rows, "count": len(rows)}
