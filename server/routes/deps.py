"""Shared FastAPI dependency: resolve ledger_id path param → (entries, errors, options_map)."""

from fastapi import Depends, HTTPException, Path

from server.state import registry


def get_ledger(ledger_id: str = Path(..., description="Ledger ID registered at startup")):
    """Return (entries, errors, options_map) for the requested ledger.

    Raises 404 if the ledger_id is unknown, 503 if it has not finished loading.
    """
    state = registry.get(ledger_id)
    if state is None:
        raise HTTPException(
            status_code=404,
            detail=f"Ledger '{ledger_id}' not found. Available: {registry.ledger_ids()}",
        )
    entries, errors, options_map = state.get()
    if not entries:
        raise HTTPException(
            status_code=503,
            detail=f"Ledger '{ledger_id}' is still loading. Try again shortly.",
        )
    return entries, errors, options_map
