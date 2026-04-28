"""FastAPI application — beancount in-memory query server."""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.state import state
from server.watcher import FileWatcher
from server.routes import query, balances, transactions, reports

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

BEANCOUNT_FILE = os.environ.get("BEANCOUNT_FILE", "")
_watcher = FileWatcher(state)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not BEANCOUNT_FILE:
        raise RuntimeError(
            "Set the BEANCOUNT_FILE environment variable to the path of your .beancount ledger file."
        )
    state.load(BEANCOUNT_FILE)
    _watcher.start(BEANCOUNT_FILE)
    yield
    _watcher.stop()


app = FastAPI(
    title="Beancount Query Server",
    description=(
        "Long-running in-memory query service for beancount ledgers. "
        "Loads the ledger once at startup; serves BQL queries, balances, "
        "transactions, and financial reports at sub-100ms latency. "
        "Hot-reloads automatically when .beancount files change."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(query.router, tags=["Query"])
app.include_router(balances.router, tags=["Balances"])
app.include_router(transactions.router, tags=["Transactions"])
app.include_router(reports.router, tags=["Reports"])


@app.get("/health", tags=["Health"])
def health():
    """Return server health and loaded ledger statistics."""
    entries, errors, options_map = state.get()
    return {
        "status": "ok" if state.is_loaded else "loading",
        "entries": len(entries),
        "errors": len(errors),
        "loaded_at": state.loaded_at,
        "ledger": options_map.get("filename", BEANCOUNT_FILE),
    }
