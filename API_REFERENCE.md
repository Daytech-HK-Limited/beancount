# Beancount Query Server — API Reference

This document is structured for use by AI agents and automated clients. Every endpoint includes the full request schema, response schema, and a concrete JSON example.

---

## Base URL

```
http://<host>:<port>
```

Default port: `8000`. Configurable via the `PORT` environment variable.

No authentication is required. All endpoints return `application/json`.

---

## Common Types

These types appear in multiple response bodies.

### Amount

```json
{ "number": "1234.56", "currency": "USD" }
```

| Field | Type | Description |
|-------|------|-------------|
| `number` | string (decimal) | Numeric value as a string to preserve precision |
| `currency` | string | 3-letter ISO currency code or commodity symbol |

### Cost

```json
{ "number": "42.00", "currency": "USD", "date": "2023-06-15", "label": null }
```

| Field | Type | Description |
|-------|------|-------------|
| `number` | string (decimal) | Cost per unit |
| `currency` | string | Cost currency |
| `date` | string (YYYY-MM-DD) or null | Lot acquisition date |
| `label` | string or null | Optional lot label |

### InventoryPosition

```json
{ "units": { "number": "10", "currency": "AAPL" }, "cost": { "number": "150.00", "currency": "USD", "date": "2023-01-10", "label": null } }
```

| Field | Type | Description |
|-------|------|-------------|
| `units` | Amount | How many units and in what commodity |
| `cost` | Cost or null | Acquisition cost basis (null for simple cash positions) |

### Balance

A balance is a list of `InventoryPosition` objects. Simple cash accounts have one element; multi-lot or multi-currency accounts have more.

```json
[
  { "units": { "number": "5000.00", "currency": "USD" }, "cost": null }
]
```

### Posting

```json
{
  "account": "Expenses:Food:Restaurant",
  "units": { "number": "-45.00", "currency": "USD" },
  "cost": null,
  "price": null,
  "flag": null
}
```

| Field | Type | Description |
|-------|------|-------------|
| `account` | string | Colon-delimited beancount account name |
| `units` | Amount | Amount posted |
| `cost` | Cost or null | Lot cost basis |
| `price` | Amount or null | Price annotation (for currency conversions) |
| `flag` | string or null | Posting-level flag (e.g. `"!"`) |

### Transaction

```json
{
  "date": "2024-03-15",
  "flag": "*",
  "payee": "Whole Foods",
  "narration": "Weekly groceries",
  "tags": ["personal"],
  "links": [],
  "postings": [
    { "account": "Expenses:Food:Groceries", "units": { "number": "78.50", "currency": "USD" }, "cost": null, "price": null, "flag": null },
    { "account": "Assets:Checking",         "units": { "number": "-78.50", "currency": "USD" }, "cost": null, "price": null, "flag": null }
  ],
  "meta": { "filename": "/ledger/2024.beancount", "lineno": 42 }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `date` | string (YYYY-MM-DD) | Transaction date |
| `flag` | string | `"*"` = cleared, `"!"` = pending |
| `payee` | string or null | Counter-party name |
| `narration` | string | Free-text description |
| `tags` | string[] | Sorted list of tags |
| `links` | string[] | Sorted list of links |
| `postings` | Posting[] | Balanced list of postings |
| `meta.filename` | string | Source file path |
| `meta.lineno` | integer | Source line number |

---

## Endpoints

### GET /health

Returns overall server health. Status is `"ok"` only when all registered ledgers have loaded without errors.

**Response 200**

```json
{
  "status": "ok",
  "ledgers": {
    "default": {
      "status": "ok",
      "entries": 120034,
      "errors": 0,
      "loaded_at": 1714000000.123
    }
  }
}
```

| Field | Values | Description |
|-------|--------|-------------|
| `status` | `"ok"` / `"degraded"` | Degraded if any ledger has errors or is still loading |
| `ledgers[id].status` | `"ok"` / `"error"` / `"reloading"` | Per-ledger status |
| `ledgers[id].entries` | integer | Number of loaded entries |
| `ledgers[id].errors` | integer | Number of parse/validation errors |
| `ledgers[id].loaded_at` | float (Unix timestamp) | When the ledger last finished loading |

---

### GET /ledgers

Lists all registered ledgers and their load state.

**Response 200**

```json
{
  "company_a": {
    "status": "ok",
    "entries": 85000,
    "errors": 0,
    "loaded_at": 1714000000.123,
    "filename": "/ledger/company_a.beancount"
  },
  "company_b": {
    "status": "loading",
    "entries": 0,
    "errors": 0,
    "loaded_at": null,
    "filename": "/ledger/company_b.beancount"
  }
}
```

---

### GET /ledgers/{ledger_id}/balances

Returns account balances. If a `date` is given, balances are computed as of that date. If an `account` glob is given, only matching accounts are returned. Accounts with a zero balance are excluded.

**Path parameters**

| Name | Description |
|------|-------------|
| `ledger_id` | Ledger ID registered at startup (e.g. `"default"`, `"company_a"`) |

**Query parameters**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `account` | string | No | Glob pattern (e.g. `Assets:*`, `Liabilities:CreditCard:*`). Case-sensitive. Omit to return all accounts. |
| `date` | YYYY-MM-DD | No | Balance as of this date. Omit to use all entries. |

**Response 200**

```json
{
  "balances": [
    {
      "account": "Assets:Bank:Checking",
      "balance": [
        { "units": { "number": "12345.67", "currency": "USD" }, "cost": null }
      ]
    },
    {
      "account": "Assets:Investments:Brokerage",
      "balance": [
        { "units": { "number": "50", "currency": "AAPL" }, "cost": { "number": "150.00", "currency": "USD", "date": "2023-01-10", "label": null } },
        { "units": { "number": "3000.00", "currency": "USD" }, "cost": null }
      ]
    }
  ],
  "count": 2
}
```

**Error responses**

| Status | Condition |
|--------|-----------|
| 404 | `ledger_id` not found |
| 503 | Ledger reload timed out (>120s) |

---

### GET /ledgers/{ledger_id}/transactions

Returns a filtered, paginated list of transactions. All filters are optional and combine with AND logic.

**Path parameters**

| Name | Description |
|------|-------------|
| `ledger_id` | Ledger ID |

**Query parameters**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `account` | string | — | Substring match against any posting account (case-insensitive) |
| `date_from` | YYYY-MM-DD | — | Start date inclusive |
| `date_to` | YYYY-MM-DD | — | End date inclusive |
| `payee` | string | — | Substring match against payee field (case-insensitive) |
| `narration` | string | — | Substring match against narration field (case-insensitive) |
| `tag` | string | — | Exact tag match |
| `flag` | string | — | Exact flag match, e.g. `*` or `!` |
| `limit` | integer | 100 | Max results to return. Range: 1–100000 |
| `offset` | integer | 0 | Number of results to skip (for pagination) |

**Response 200**

```json
{
  "transactions": [
    {
      "date": "2024-03-15",
      "flag": "*",
      "payee": "Whole Foods",
      "narration": "Weekly groceries",
      "tags": [],
      "links": [],
      "postings": [
        { "account": "Expenses:Food:Groceries", "units": { "number": "78.50", "currency": "USD" }, "cost": null, "price": null, "flag": null },
        { "account": "Assets:Checking",         "units": { "number": "-78.50", "currency": "USD" }, "cost": null, "price": null, "flag": null }
      ],
      "meta": { "filename": "/ledger/2024.beancount", "lineno": 42 }
    }
  ],
  "count": 1,
  "offset": 0,
  "limit": 100
}
```

**Pagination pattern**

```
GET /ledgers/default/transactions?limit=1000&offset=0     → first 1000
GET /ledgers/default/transactions?limit=1000&offset=1000  → next 1000
```

**Error responses**

| Status | Condition |
|--------|-----------|
| 404 | `ledger_id` not found |
| 422 | Invalid query parameter types |
| 503 | Ledger reload timed out |

---

### POST /ledgers/{ledger_id}/query

Run an arbitrary BQL (Beancount Query Language) statement against the in-memory ledger. Replaces shelling out to `bean-query`.

**Path parameters**

| Name | Description |
|------|-------------|
| `ledger_id` | Ledger ID |

**Request body** (`application/json`)

```json
{ "sql": "SELECT account, sum(units(position)) WHERE account ~ 'Assets' GROUP BY account ORDER BY account" }
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `sql` | string | Yes | BQL query string. Same syntax as `bean-query`. |

**Response 200**

```json
{
  "columns": ["account", "sum_units_position_"],
  "rows": [
    { "account": "Assets:Bank:Checking", "sum_units_position_": [{ "units": { "number": "12345.67", "currency": "USD" }, "cost": null }] },
    { "account": "Assets:Investments",   "sum_units_position_": [{ "units": { "number": "50", "currency": "AAPL" }, "cost": null }] }
  ],
  "count": 2
}
```

| Field | Type | Description |
|-------|------|-------------|
| `columns` | string[] | Column names derived from the SELECT clause |
| `rows` | object[] | Each row is an object keyed by column name |
| `count` | integer | Number of result rows |

Column value serialization rules:
- Decimal numbers → string (e.g. `"1234.56"`)
- Dates → ISO string (e.g. `"2024-03-15"`)
- Sets / frozensets → sorted string array
- Inventory → array of InventoryPosition objects
- NamedTuples → object with field names as keys

**Error responses**

| Status | Condition |
|--------|-----------|
| 400 | Invalid BQL syntax or query execution error. `detail` contains the error message. |
| 404 | `ledger_id` not found |
| 501 | `beanquery` package not installed |
| 503 | Ledger reload timed out |

**Common BQL examples**

```sql
-- All account balances
SELECT account, sum(units(position)) GROUP BY account ORDER BY account

-- Transactions in a date range
SELECT date, payee, narration, position
  WHERE date >= 2024-01-01 AND date <= 2024-03-31

-- Monthly expenses by category
SELECT year, month, account, sum(position)
  WHERE account ~ 'Expenses'
  GROUP BY year, month, account

-- Net income for the year
SELECT sum(position)
  WHERE account ~ 'Income' OR account ~ 'Expenses'
```

---

### GET /ledgers/{ledger_id}/report/balance_sheet

Returns assets, liabilities, and equity accounts grouped by type, optionally as of a specific date. Zero-balance accounts are excluded.

**Path parameters**

| Name | Description |
|------|-------------|
| `ledger_id` | Ledger ID |

**Query parameters**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `date` | YYYY-MM-DD | No | As-of date. Omit to use all entries (latest state). |

**Response 200**

```json
{
  "as_of": "2024-03-31",
  "assets": [
    { "account": "Assets:Bank:Checking",    "balance": [{ "units": { "number": "12345.67", "currency": "USD" }, "cost": null }] },
    { "account": "Assets:Investments",      "balance": [{ "units": { "number": "50", "currency": "AAPL" }, "cost": { "number": "150.00", "currency": "USD", "date": "2023-01-10", "label": null } }] }
  ],
  "liabilities": [
    { "account": "Liabilities:CreditCard",  "balance": [{ "units": { "number": "-450.00", "currency": "USD" }, "cost": null }] }
  ],
  "equity": [
    { "account": "Equity:Opening-Balances", "balance": [{ "units": { "number": "-11895.67", "currency": "USD" }, "cost": null }] }
  ]
}
```

Each section (`assets`, `liabilities`, `equity`) is a list of `{ "account": string, "balance": Balance }` sorted alphabetically by account name.

---

### GET /ledgers/{ledger_id}/report/income

Returns income and expense accounts for a time period (income statement / P&L).

**Path parameters**

| Name | Description |
|------|-------------|
| `ledger_id` | Ledger ID |

**Query parameters**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `date_from` | YYYY-MM-DD | No | Period start inclusive. Omit for all history. |
| `date_to` | YYYY-MM-DD | No | Period end inclusive. Defaults to today. |

**Response 200**

```json
{
  "date_from": "2024-01-01",
  "date_to": "2024-03-31",
  "income": [
    { "account": "Income:Salary",           "balance": [{ "units": { "number": "-15000.00", "currency": "USD" }, "cost": null }] }
  ],
  "expenses": [
    { "account": "Expenses:Food:Groceries", "balance": [{ "units": { "number": "780.00",   "currency": "USD" }, "cost": null }] },
    { "account": "Expenses:Rent",           "balance": [{ "units": { "number": "3600.00",  "currency": "USD" }, "cost": null }] }
  ]
}
```

**Important:** Income account balances are negative by beancount convention (credit-normal). To compute net income: `sum(income[].balance[].units.number) + sum(expenses[].balance[].units.number)`.

---

### POST /ledgers/{ledger_id}/reload

Forces an **immediate synchronous reload** of the specified ledger. Blocks until the reload is complete and fresh data is live. Use this when your application layer knows the ledger file has changed and cannot wait for the background file watcher.

**Recommended ERP integration flow:**
1. Write changes to the `.beancount` file
2. Invalidate your own application cache
3. Call `POST /ledgers/{ledger_id}/reload` — request blocks here
4. On `200` response — all subsequent API calls return fresh data

**Path parameters**

| Name | Description |
|------|-------------|
| `ledger_id` | Ledger ID to reload |

**Request body:** none

**Response 200**

```json
{
  "status": "ok",
  "ledger_id": "company_a",
  "entries": 120034,
  "errors": 0,
  "loaded_at": 1714000012.456,
  "filename": "/ledger/company_a.beancount"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | Always `"ok"` on success |
| `ledger_id` | string | Echoes the requested ledger ID |
| `entries` | integer | Number of entries loaded |
| `errors` | integer | Parse/validation error count (0 = clean) |
| `loaded_at` | float | Unix timestamp when this reload completed |
| `filename` | string | Absolute path to the reloaded ledger file |

**Error responses**

| Status | Condition |
|--------|-----------|
| 404 | `ledger_id` not found |
| 500 | Reload failed (e.g. file missing, parse error). `detail` contains the error. |
| 503 | Ledger has no filename set |

**Concurrency note:** If a file-watcher reload is already running when this is called, the explicit reload waits for it to finish, then performs another full reload. The `200` response always reflects a state loaded after this request was received.

---

## Error Response Format

All errors use the standard FastAPI shape:

```json
{ "detail": "Ledger 'company_x' not found. Available: ['default', 'company_a']" }
```

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `BEANCOUNT_FILE` | Path to a single ledger file. Registered as ledger ID `"default"`. |
| `BEANCOUNT_LEDGERS` | JSON object mapping ledger IDs to file paths: `{"company_a": "/ledger/a.beancount", "company_b": "/ledger/b.beancount"}`. Takes precedence over `BEANCOUNT_FILE`. |
| `PORT` | HTTP port (default: `8000`) |
| `CORS_ORIGINS` | Comma-separated allowed CORS origins (default: `*`) |
| `BEANCOUNT_LOAD_CACHE_FILENAME` | Override path pattern for beancount's pickle cache. Redirect to a persistent volume: `/cache/.{filename}.picklecache` |
| `BEANCOUNT_DISABLE_LOAD_CACHE` | Set to any non-empty value to disable the pickle cache. |

---

## Hot Reload Behaviour

The server polls all registered ledger files every **2 seconds**. On detecting any change, it waits **3 seconds** (debounce) then reloads in a background thread. During reload, all incoming requests block and resume with fresh data once complete.

To bypass the poll + debounce delay entirely, call `POST /ledgers/{ledger_id}/reload` immediately after writing changes.
