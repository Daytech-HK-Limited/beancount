"""Shared FastAPI dependencies: resolve ledger_id → state, blocking on reload."""

from fastapi import Depends, HTTPException, Path

from server.state import registry


def _resolve_state(ledger_id: str):
    state = registry.get(ledger_id)
    if state is None:
        raise HTTPException(
            status_code=404,
            detail=f"Ledger '{ledger_id}' not found. Available: {registry.ledger_ids()}",
        )
    return state


def get_ledger(ledger_id: str = Path(..., description="Ledger ID registered at startup")):
    """Resolve ledger_id → (entries, errors, options_map).

    Blocks if the ledger is currently reloading; returns fresh data once done.
    Raises 503 on timeout (reload took longer than 120s).
    """
    state = _resolve_state(ledger_id)
    try:
        return state.get()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


def get_ledger_with_root(ledger_id: str = Path(..., description="Ledger ID registered at startup")):
    """Resolve ledger_id → (entries, errors, options_map, real_root).

    Same blocking semantics as get_ledger but also returns the pre-computed
    realization tree for balance/report routes that need it.
    """
    state = _resolve_state(ledger_id)
    try:
        entries, errors, options_map = state.get()
        real_root = state.get_real_root()
        return entries, errors, options_map, real_root
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
