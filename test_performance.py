#!/usr/bin/env python3
"""
Beancount query server — performance test.

Generates a large ledger (default: 120,000 transactions), starts the server,
verifies that transaction queries return > 10,000 entries, then benchmarks
all key endpoints with both sequential and concurrent load patterns.

Usage (from the beancount project root):
    python test_performance.py
    python test_performance.py --transactions 200000
    python test_performance.py --port 8765 --keep-file
"""

import argparse
import json
import os
import random
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from statistics import median

import requests

# ── Account universe ──────────────────────────────────────────────────────────

_ACCOUNTS = [
    "Assets:Bank:Checking",
    "Assets:Bank:Savings",
    "Assets:Cash",
    "Assets:Investments:Stocks",
    "Assets:Investments:Bonds",
    "Assets:Receivable",
    "Liabilities:CreditCard:Visa",
    "Liabilities:CreditCard:Amex",
    "Liabilities:Loan:Mortgage",
    "Liabilities:Payable",
    "Income:Salary",
    "Income:Freelance",
    "Income:Dividends",
    "Income:Interest",
    "Income:Rental",
    "Expenses:Food:Groceries",
    "Expenses:Food:Restaurant",
    "Expenses:Transport:Gas",
    "Expenses:Transport:Transit",
    "Expenses:Housing:Rent",
    "Expenses:Housing:Utilities",
    "Expenses:Healthcare",
    "Expenses:Entertainment",
    "Expenses:Shopping",
    "Expenses:Education",
    "Expenses:Insurance",
    "Expenses:Taxes",
    "Equity:Opening-Balances",
    "Equity:Retained-Earnings",
]

_ASSET       = [a for a in _ACCOUNTS if a.startswith("Assets:")]
_LIABILITY   = [a for a in _ACCOUNTS if a.startswith("Liabilities:")]
_INCOME      = [a for a in _ACCOUNTS if a.startswith("Income:")]
_EXPENSE     = [a for a in _ACCOUNTS if a.startswith("Expenses:")]

_PAYEES = [
    "Whole Foods", "Amazon", "Starbucks", "Shell Gas", "Netflix",
    "Apple Store", "Uber", "Target", "Costco", "Home Depot",
    "Chase Bank", "Verizon", "PG&E", "Kaiser", "Southwest Airlines",
    "Employer Inc", "Client A", "Client B", "Government", "Insurance Co",
    "University", "Restaurant Row", "Corner Store", "City Pharmacy",
]

_NARRATIONS = [
    "Monthly expense", "Weekly purchase", "Payment received",
    "Transfer", "Bill payment", "Subscription renewal",
    "Refund", "Deposit", "Service fee", "Interest payment",
    "Dividend received", "Annual bonus", "Reimbursement",
]

# ── Ledger generation ─────────────────────────────────────────────────────────

def generate_ledger(path: str, num_transactions: int, start: date, end: date) -> None:
    """Write a syntactically valid beancount file with num_transactions entries."""
    rng = random.Random(42)
    total_days = (end - start).days

    # Generate and sort all transaction dates up front
    offsets = sorted(rng.randint(0, total_days) for _ in range(num_transactions))

    with open(path, "w", encoding="utf-8") as f:
        f.write('option "title" "Performance Test Ledger"\n\n')

        # Open every account on the day before the first transaction
        setup_date = start - timedelta(days=1)
        for account in _ACCOUNTS:
            f.write(f"{setup_date} open {account} USD\n")
        f.write("\n")

        # Seed asset accounts with opening balances
        for account, amount in [
            ("Assets:Bank:Checking",      500_000.00),
            ("Assets:Bank:Savings",       200_000.00),
            ("Assets:Cash",                 5_000.00),
            ("Assets:Investments:Stocks",  80_000.00),
            ("Assets:Investments:Bonds",   40_000.00),
        ]:
            f.write(
                f"{setup_date} * \"Opening balance\" \"Initial balance\"\n"
                f"  {account}  {amount:.2f} USD\n"
                f"  Equity:Opening-Balances  -{amount:.2f} USD\n\n"
            )

        # Write transactions
        for offset in offsets:
            txn_date = start + timedelta(days=offset)
            amount   = round(rng.uniform(10.0, 5_000.0), 2)
            payee    = rng.choice(_PAYEES)
            narr     = rng.choice(_NARRATIONS)
            flag     = "*" if rng.random() < 0.85 else "!"

            roll = rng.random()
            if roll < 0.70:
                # Expense: debit expense, credit asset or liability
                debit  = rng.choice(_EXPENSE)
                credit = rng.choice(_ASSET + _LIABILITY)
            elif roll < 0.90:
                # Income: debit asset, credit income
                debit  = rng.choice(_ASSET)
                credit = rng.choice(_INCOME)
            else:
                # Transfer: asset to asset
                debit  = rng.choice(_ASSET)
                credit = rng.choice([a for a in _ASSET if a != debit])

            f.write(
                f"{txn_date} {flag} \"{payee}\" \"{narr}\"\n"
                f"  {debit}  {amount:.2f} USD\n"
                f"  {credit}  -{amount:.2f} USD\n\n"
            )


# ── Server management ─────────────────────────────────────────────────────────

def start_server(ledger_path: str, ledger_id: str, port: int) -> subprocess.Popen:
    project_root = os.path.dirname(os.path.abspath(__file__))
    env = os.environ.copy()
    env["BEANCOUNT_LEDGERS"] = json.dumps({ledger_id: ledger_path})
    env["PORT"] = str(port)
    return subprocess.Popen(
        [sys.executable, "run_server.py"],
        cwd=project_root,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def wait_for_ready(base_url: str, timeout: float = 300.0) -> None:
    """Poll /health until every ledger shows status != 'reloading'. Raises on timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"{base_url}/health", timeout=3)
            if r.status_code == 200:
                data = r.json()
                ledgers = data.get("ledgers", {})
                if ledgers and all(v["status"] != "reloading" for v in ledgers.values()):
                    return
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(1.0)
    raise TimeoutError(f"Server at {base_url} did not become ready within {timeout:.0f}s")


# ── Timing helpers ────────────────────────────────────────────────────────────

def _percentile(sorted_values: list, p: float) -> float:
    idx = min(int(len(sorted_values) * p), len(sorted_values) - 1)
    return sorted_values[idx]


def bench_sequential(fn, n: int, warmup: int = 3) -> dict:
    """Run fn() sequentially n times; return latency stats in ms."""
    for _ in range(warmup):
        fn()
    times = sorted((time.perf_counter(), fn())[0] for _ in range(n))
    # Re-run properly timing each call
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1_000)
    times.sort()
    return {
        "n": n,
        "min":    times[0],
        "median": median(times),
        "p95":    _percentile(times, 0.95),
        "max":    times[-1],
    }


def bench_concurrent(fn, threads: int, calls_per_thread: int) -> dict:
    """Fire threads × calls_per_thread requests concurrently; return stats in ms."""
    barrier = [False]

    def worker():
        while not barrier[0]:
            time.sleep(0.001)
        times = []
        for _ in range(calls_per_thread):
            t0 = time.perf_counter()
            fn()
            times.append((time.perf_counter() - t0) * 1_000)
        return times

    t_wall_start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=threads) as pool:
        futures = [pool.submit(worker) for _ in range(threads)]
        time.sleep(0.05)   # give all threads a moment to reach the barrier
        barrier[0] = True
        all_times = []
        for fut in as_completed(futures):
            all_times.extend(fut.result())
    wall_ms = (time.perf_counter() - t_wall_start) * 1_000

    all_times.sort()
    total = len(all_times)
    return {
        "n":        total,
        "min":      all_times[0],
        "median":   median(all_times),
        "p95":      _percentile(all_times, 0.95),
        "max":      all_times[-1],
        "wall_ms":  wall_ms,
        "rps":      total / (wall_ms / 1_000),
    }


# ── Output formatting ─────────────────────────────────────────────────────────

def _row(label: str, stats: dict) -> str:
    return (
        f"  {label:<55}  {stats['n']:>5}  "
        f"{stats['min']:>7.1f}  {stats['median']:>7.1f}  "
        f"{stats['p95']:>7.1f}  {stats['max']:>7.1f}"
    )


def print_table(title: str, rows: list) -> None:
    header = f"  {'Endpoint':<55}  {'n':>5}  {'min':>7}  {'p50':>7}  {'p95':>7}  {'max':>7}"
    sep    = "  " + "-" * (len(header) - 2)
    print(f"\n{title}")
    print(header)
    print(sep)
    for label, stats in rows:
        print(_row(label, stats))


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="Beancount server performance test")
    ap.add_argument("--transactions", type=int, default=120_000,
                    help="Number of transactions to generate (default: 120,000)")
    ap.add_argument("--port", type=int, default=8765,
                    help="Port for the test server (default: 8765)")
    ap.add_argument("--keep-file", action="store_true",
                    help="Keep the generated ledger file after the test")
    ap.add_argument("--concurrent-threads", type=int, default=10,
                    help="Threads for concurrent benchmark (default: 10)")
    args = ap.parse_args()

    LEDGER_ID = "perf_test"
    BASE_URL  = f"http://localhost:{args.port}"
    START     = date(2000, 1, 1)
    END       = date(2025, 12, 31)

    # ── 1. Generate ledger ────────────────────────────────────────────────────
    tmp_fd, ledger_path = tempfile.mkstemp(suffix=".beancount", prefix="bc_perf_")
    os.close(tmp_fd)

    print(f"\n{'=' * 70}")
    print(f" BEANCOUNT QUERY SERVER - PERFORMANCE TEST")
    print(f"{'=' * 70}")
    print(f"\n[1/4] Generating ledger: {ledger_path}")
    print(f"      {args.transactions:,} transactions  |  {START} to {END}")
    t0 = time.time()
    generate_ledger(ledger_path, args.transactions, START, END)
    gen_elapsed = time.time() - t0
    size_mb = os.path.getsize(ledger_path) / 1_048_576
    print(f"      Done in {gen_elapsed:.1f}s  ({size_mb:.1f} MB)")

    proc = None
    try:
        # ── 2. Start server ───────────────────────────────────────────────────
        print(f"\n[2/4] Starting server on port {args.port} ...")
        t_launch = time.time()
        proc = start_server(ledger_path, LEDGER_ID, args.port)
        wait_for_ready(BASE_URL, timeout=300)
        load_elapsed = time.time() - t_launch

        health  = requests.get(f"{BASE_URL}/health", timeout=10).json()
        ledger_health = health["ledgers"][LEDGER_ID]
        entries = ledger_health["entries"]
        errors  = ledger_health["errors"]
        status  = ledger_health["status"]

        print(f"      Status : {status}")
        print(f"      Entries: {entries:,}  (errors: {errors})")
        print(f"      Load time (wall clock incl. realize()): {load_elapsed:.1f}s")

        if status != "ok":
            print(f"\n  WARNING: ledger status is '{status}'. Errors may affect results.")

        # ── 3. Verify large transaction response ──────────────────────────────
        print(f"\n[3/4] Verifying large transaction response ...")
        sess = requests.Session()

        r = sess.get(
            f"{BASE_URL}/ledgers/{LEDGER_ID}/transactions",
            params={"limit": 15_000},
            timeout=120,
        )
        r.raise_for_status()
        txn_data  = r.json()
        txn_count = txn_data["count"]
        ok_marker = "OK" if txn_count >= 10_000 else "FAIL"
        print(f"      [{ok_marker}] /transactions?limit=15000 returned {txn_count:,} transactions")

        r2 = sess.get(f"{BASE_URL}/ledgers/{LEDGER_ID}/balances", timeout=30)
        r2.raise_for_status()
        bal_count = r2.json()["count"]
        print(f"      [OK] /balances returned {bal_count:,} non-zero accounts")

        # ── 4. Benchmarks ─────────────────────────────────────────────────────
        print(f"\n[4/4] Running benchmarks  (all latencies in ms) ...")

        lid = LEDGER_ID

        def _get(path, **params):
            return lambda: sess.get(f"{BASE_URL}{path}", params=params or None, timeout=60)

        def _post(path, body):
            return lambda: sess.post(f"{BASE_URL}{path}", json=body, timeout=120)

        seq_rows = [
            ("GET /ledgers",
             bench_sequential(_get("/ledgers"), 100)),
            (f"GET /ledgers/{lid}/balances  (all accounts)",
             bench_sequential(_get(f"/ledgers/{lid}/balances"), 100)),
            (f"GET /ledgers/{lid}/balances?account=Assets:*",
             bench_sequential(_get(f"/ledgers/{lid}/balances", account="Assets:*"), 100)),
            (f"GET /ledgers/{lid}/report/balance_sheet",
             bench_sequential(_get(f"/ledgers/{lid}/report/balance_sheet"), 50)),
            (f"GET /ledgers/{lid}/report/income  (full period)",
             bench_sequential(_get(f"/ledgers/{lid}/report/income"), 20)),
            (f"GET /ledgers/{lid}/transactions?limit=1000",
             bench_sequential(_get(f"/ledgers/{lid}/transactions", limit=1000), 30)),
            (f"GET /ledgers/{lid}/transactions?limit=15000",
             bench_sequential(_get(f"/ledgers/{lid}/transactions", limit=15_000), 10)),
            (f"POST /ledgers/{lid}/query  (GROUP BY account)",
             bench_sequential(
                 _post(f"/ledgers/{lid}/query",
                       {"sql": "SELECT account, sum(units(position)) AS total "
                               "GROUP BY account ORDER BY account"}),
                 20,
             )),
        ]

        print_table("-- Sequential (single request at a time) --", seq_rows)

        # Concurrent: balance endpoint under parallel load
        conc_fn  = _get(f"/ledgers/{lid}/balances")
        conc     = bench_concurrent(conc_fn, threads=args.concurrent_threads, calls_per_thread=10)
        conc_txn = bench_concurrent(
            _get(f"/ledgers/{lid}/transactions", limit=1000),
            threads=args.concurrent_threads,
            calls_per_thread=5,
        )

        print(f"\n-- Concurrent ({args.concurrent_threads} threads) --")
        print(f"\n  /balances  ({conc['n']} total requests)")
        print(f"    {'min':>7}  {'p50':>7}  {'p95':>7}  {'max':>7}  {'wall':>8}  {'req/s':>7}")
        print(f"    {conc['min']:>6.1f}ms  {conc['median']:>6.1f}ms  {conc['p95']:>6.1f}ms  "
              f"{conc['max']:>6.1f}ms  {conc['wall_ms']:>7.0f}ms  {conc['rps']:>6.0f}")

        print(f"\n  /transactions?limit=1000  ({conc_txn['n']} total requests)")
        print(f"    {'min':>7}  {'p50':>7}  {'p95':>7}  {'max':>7}  {'wall':>8}  {'req/s':>7}")
        print(f"    {conc_txn['min']:>6.1f}ms  {conc_txn['median']:>6.1f}ms  {conc_txn['p95']:>6.1f}ms  "
              f"{conc_txn['max']:>6.1f}ms  {conc_txn['wall_ms']:>7.0f}ms  {conc_txn['rps']:>6.0f}")

        # ── Summary ───────────────────────────────────────────────────────────
        print(f"\n{'=' * 70}")
        print(f" SUMMARY")
        print(f"{'=' * 70}")
        print(f"  Ledger entries   : {entries:,}")
        print(f"  Load + realize   : {load_elapsed:.1f}s  (one-time cost at startup / after file change)")
        print(f"  Transactions>10k : {txn_count:,} returned in "
              f"{seq_rows[6][1]['median']:.0f}ms median")
        print(f"  Balance query    : {seq_rows[1][1]['median']:.1f}ms median  "
              f"(pre-computed realization tree)")
        print(f"  Concurrent rps   : {conc['rps']:.0f} req/s on /balances  "
              f"({args.concurrent_threads} threads)")
        print()

    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        if args.keep_file:
            print(f"Kept ledger file: {ledger_path}")
        else:
            try:
                os.unlink(ledger_path)
            except OSError:
                pass


if __name__ == "__main__":
    main()
