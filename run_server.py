"""Entry point: start the beancount query server.

Usage:
    BEANCOUNT_FILE=/path/to/ledger.beancount python run_server.py

Or with uvicorn directly:
    BEANCOUNT_FILE=/path/to/ledger.beancount uvicorn server.app:app --host 0.0.0.0 --port 8000

Note: Use a single worker process. Multiple workers each load a full copy of the
ledger in memory. For horizontal scaling, run multiple single-worker processes
behind a load balancer.
"""

import sys
import os

# When running from the beancount source tree, the uncompiled local beancount/
# package shadows the installed wheel (which has the required C extension).
# Fix: move this directory to the END of sys.path so site-packages (installed
# beancount) is resolved first, while server/ is still importable.
_here = os.path.dirname(os.path.abspath(__file__))
sys.path = [p for p in sys.path if os.path.abspath(p) != _here]
sys.path.append(_here)

import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(
        "server.app:app",
        host="0.0.0.0",
        port=port,
        workers=1,
        log_level="info",
    )
