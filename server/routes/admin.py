"""POST /ledgers/{ledger_id}/reload — force an immediate synchronous reload."""

import logging

from fastapi import APIRouter, HTTPException, Path

from server.state import registry

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/reload")
def force_reload(
    ledger_id: str = Path(..., description="Ledger ID to reload"),
):
    """Trigger an immediate reload of the ledger and wait until it is complete.

    Returns only after fresh data is loaded and ready to serve.
    Use this when your application knows the ledger file has changed and
    cannot wait for the file watcher to detect the change on its own.
    """
    state = registry.get(ledger_id)
    if state is None:
        raise HTTPException(
            status_code=404,
            detail=f"Ledger '{ledger_id}' not found. Available: {registry.ledger_ids()}",
        )

    filename = state.filename
    if filename is None:
        raise HTTPException(status_code=503, detail=f"Ledger '{ledger_id}' has no filename set.")

    logger.info("[%s] Explicit reload requested via API", ledger_id)

    # Runs synchronously — blocks until the reload is complete.
    # _reload_lock inside state.load() prevents a race with the file watcher
    # if it also fires at the same time.
    try:
        state.load(filename)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Reload failed: {exc}")

    return {
        "status": "ok",
        "ledger_id": ledger_id,
        "entries": state.entry_count,
        "errors": state.error_count,
        "loaded_at": state.loaded_at,
        "filename": filename,
    }
