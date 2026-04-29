"""FastAPI application — beancount in-memory query server (single and multi-ledger)."""

import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.state import registry
from server.watcher import FileWatcher
from server.routes import query, balances, transactions, reports, admin

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_watcher = FileWatcher(registry)


def _load_ledger_config() -> dict[str, str]:
    """Return {ledger_id: filename} from environment.

    Two env-var formats are supported:

    Single ledger (backwards compatible):
        BEANCOUNT_FILE=/ledger/main.beancount
        → registered as ledger_id "default"

    Multiple ledgers (JSON):
        BEANCOUNT_LEDGERS='{"company_a": "/ledger/a.beancount", "company_b": "/ledger/b.beancount"}'

    If both are set, BEANCOUNT_LEDGERS takes precedence.
    """
    multi = os.environ.get("BEANCOUNT_LEDGERS", "").strip()
    if multi:
        try:
            ledgers = json.loads(multi)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"BEANCOUNT_LEDGERS is not valid JSON: {exc}"
            ) from exc
        if not isinstance(ledgers, dict) or not ledgers:
            raise RuntimeError(
                "BEANCOUNT_LEDGERS must be a non-empty JSON object: "
                '{"company_a": "/path/a.beancount", ...}'
            )
        return ledgers

    single = os.environ.get("BEANCOUNT_FILE", "").strip()
    if single:
        return {"default": single}

    raise RuntimeError(
        "Set BEANCOUNT_FILE (single ledger) or BEANCOUNT_LEDGERS (JSON map) "
        "environment variable before starting the server."
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    ledgers = _load_ledger_config()
    logger.info("Registering %d ledger(s): %s", len(ledgers), list(ledgers.keys()))
    for ledger_id, filename in ledgers.items():
        registry.register(ledger_id, filename)
    _watcher.start()
    yield
    _watcher.stop()


app = FastAPI(
    title="Beancount Query Server",
    description=(
        "Long-running in-memory query service for beancount ledgers. "
        "Supports multiple simultaneous ledgers via /ledgers/{ledger_id}/... routes. "
        "Hot-reloads automatically when .beancount files change."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

# All accounting routes are namespaced under /ledgers/{ledger_id}/
app.include_router(query.router,        prefix="/ledgers/{ledger_id}", tags=["Query"])
app.include_router(balances.router,     prefix="/ledgers/{ledger_id}", tags=["Balances"])
app.include_router(transactions.router, prefix="/ledgers/{ledger_id}", tags=["Transactions"])
app.include_router(reports.router,      prefix="/ledgers/{ledger_id}", tags=["Reports"])
app.include_router(admin.router,        prefix="/ledgers/{ledger_id}", tags=["Admin"])


@app.get("/ledgers", tags=["Ledgers"])
def list_ledgers():
    """List all registered ledger IDs and their load status."""
    result = {}
    for ledger_id, state in registry.all().items():
        result[ledger_id] = {
            "status": "ok" if state.is_loaded else "loading",
            "entries": state.entry_count,
            "errors": state.error_count,
            "loaded_at": state.loaded_at,
            "filename": state.filename,
        }
    return result


@app.get("/health", tags=["Health"])
def health():
    """Overall health: ok when ALL ledgers are loaded without errors."""
    states = registry.all()
    all_ok = all(s.is_loaded and s.error_count == 0 for s in states.values())
    return {
        "status": "ok" if all_ok else "degraded",
        "ledgers": {
            lid: {
                "status": "reloading" if s.is_reloading else ("ok" if s.error_count == 0 else "error"),
                "entries": s.entry_count,
                "errors": s.error_count,
                "loaded_at": s.loaded_at,
            }
            for lid, s in states.items()
        },
    }
