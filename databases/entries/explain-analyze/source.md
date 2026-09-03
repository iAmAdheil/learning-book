---
slug: explain-analyze
title: EXPLAIN & EXPLAIN ANALYZE — Reading Query Plans in Practice
topic: databases
bloom-level: some
created: 2026-09-01
updated: 2026-09-01
published: 2026-09-03
related: [query-planning, join-algorithms, sql-fundamentals, btree-indexes, composite-indexes, covering-indexes, buffer-pool, heap-storage-layout, statistics-cardinality]
tags: [explain, explain-analyze, query-plan, plan-tree, startup-cost, total-cost, estimated-rows, actual-rows, width, loops, per-loop-averages, rows-removed-by-filter, buffers, shared-hit, shared-read, planning-time, execution-time, seq-scan, index-scan, index-only-scan, bitmap-heap-scan, recheck-cond, heap-fetches, nested-loop, hash-join, merge-join, batches, external-merge, sort-method, work-mem, timing-off, generic-plan, format-json, verbose, settings, wal, side-effects, rollback, interview-priority]
sources:
  - title: "PostgreSQL Documentation — 14.1. Using EXPLAIN"
    url: "https://www.postgresql.org/docs/current/using-explain.html"
  - title: "PostgreSQL Documentation — EXPLAIN (SQL command reference)"
    url: "https://www.postgresql.org/docs/current/sql-explain.html"
  - title: "PostgreSQL Documentation — 52.5. Planner/Optimizer"
    url: "https://www.postgresql.org/docs/current/planner-optimizer.html"
  - title: "PostgreSQL Documentation — 20.4. Resource Consumption (work_mem)"
    url: "https://www.postgresql.org/docs/current/runtime-config-resource.html"
---

## Answer

[[query-planning]] described a machine that predicts. `EXPLAIN ANALYZE` is the instrument that shows you **what it predicted and what actually happened, side by side**.

That pairing is the whole value. `EXPLAIN` alone shows only the prediction, which tells you what the planner believes but never whether it was right. The single most useful skill in database performance work is reading the gap between the two columns.

> **`EXPLAIN` shows intent. `EXPLAIN ANALYZE` shows intent versus reality. Almost every diagnosis lives in the difference.**

### The one warning that matters first

> "Keep in mind that the statement is actually executed when the `ANALYZE` option is used. Although `EXPLAIN` will discard any output that a `SELECT` would return, **other side effects of the statement will happen as usual**."

`EXPLAIN ANALYZE UPDATE ...` performs the update. The row output is discarded; the write is not. The documented protection:

```sql
BEGIN;
EXPLAIN ANALYZE UPDATE transactions SET status = 'FAILED' WHERE txn_id = 42;
ROLLBACK;
```

Make that reflex before you ever run `ANALYZE` on a write. It is also a genuine interview question.

---

## Part 1 — Anatomy of a node

A plan is a tree. "Nodes at the bottom level of the tree are scan nodes: they return raw rows from a table." Every node consumes rows from its children and emits rows to its parent.

```
Seq Scan on transactions  (cost=0.00..470.00 rows=7000 width=244)
                          (actual time=0.030..1.995 rows=7000 loops=1)
                                ^      ^           ^         ^
                                |      |           |         times this node ran
                                |      |           rows it ACTUALLY produced (per loop)
                                |      time until the LAST row
                                time until the FIRST row
```

The estimate half:

| Field | Meaning (docs) |
|---|---|
| startup cost | "the time expended before the output phase can begin, e.g., time to do the sorting in a sort node" |
| total cost | "stated on the assumption that the plan node is run to completion, i.e., all available rows are retrieved" |
| `rows=` | estimated rows, again assuming the node runs to completion |
| `width=` | "Estimated average width of rows output by this plan node (in bytes)" |

### Two structural facts people get wrong

**1. Costs are cumulative upward.**

> "**It's important to understand that the cost of an upper-level node includes the cost of all its child nodes.**"

> "**The very first line (the summary line for the topmost node) has the estimated total execution cost for the plan; it is this number that the planner seeks to minimize.**"

So a node's *own* cost is its total minus its children's totals. A `Hash Join` showing `cost=...15000` has not spent 15000 joining — most of that is the scans beneath it. Reading a plan means subtracting as you go up, not summing.

**2. `actual time` and `rows` are per-loop averages, not totals.**

> "the `loops` value reports the total number of executions of the node, and the actual time and rows values shown are **averages per-execution**... **Multiply by the `loops` value to get the total time actually spent in the node.**"

This is the single most common misreading of a plan, and it hides the worst problems. Inside a nested loop:

```
->  Index Scan on transactions  (actual time=0.012..0.014 rows=3 loops=50000)
                                              ^^^^^ looks instant       ^^^^^
```

`0.014 ms` looks harmless. The node ran **50,000 times**, so it actually consumed roughly **700 ms**, and produced 150,000 rows rather than 3. An inner node of a nested loop always needs this multiplication before its numbers mean anything.

---

## Part 2 — The diagnostic order

A practical reading order. Work down this list and stop when something is obviously wrong.

### 1. Compare `rows=` estimated against `rows=` actual — at every node

This is the diagnosis, not the join type. From [[query-planning]]: cost is arithmetic on top of cardinality, so a wrong row count corrupts every decision above it.

```
Nested Loop  (cost=0.29..8.31 rows=5 width=64) (actual ... rows=500000 loops=1)
                                    ^^^^^^                       ^^^^^^^^^^
                                  believed 5                    found 500,000
```

**Find the *lowest* node where the gap first appears.** Errors compound upward, so a bad number at the top is usually an echo of a bad number three levels down. The lowest divergence is the cause; everything above it is a symptom.

Rules of thumb: a gap under ~10× is normal noise. Beyond ~100× the plan choice is probably wrong. Beyond ~1000× expect a catastrophic plan.

### 2. Multiply by `loops` on anything under a nested loop

As above. Untranslated per-loop numbers are how a 40-minute query looks fast in its own plan.

### 3. Look for the expensive node, by *self* cost

Subtract children. The node with the largest self-contribution is where the time actually goes.

### 4. Check the physical warning signs

| Signal | Meaning |
|---|---|
| `Rows Removed by Filter: 3000000` | the scan read millions of rows and threw them away — a missing or unusable index |
| `Batches: 16` under a `Hash` | the hash table spilled to disk; `work_mem` too small **or** the row estimate was wrong |
| `Sort Method: external merge  Disk: 24MB` | the sort spilled to disk rather than staying in memory |
| `Heap Fetches: 480000` on an Index Only Scan | the visibility map is stale — `VACUUM` is behind. See [[covering-indexes]] |
| `Seq Scan` on the *inner* side of a nested loop | the emergency signal from [[join-algorithms]] |
| `loops=` in the tens of thousands | an N+1 shape inside the engine |

`Rows Removed by Filter` deserves emphasis because it directly measures wasted work:

> "The 'Rows Removed by Filter' line only appears when at least one scanned row, or potential join pair in the case of a join node, is rejected by the filter condition."

A node that emits 12 rows after removing 3,000,000 did 250,000× more work than the result required. That is an index request, stated numerically.

---

## Part 3 — Reading the scan nodes

The bottom of every plan, and where most fixes land.

**`Seq Scan`** — read every page of the table. Not automatically bad: for a small table, or when returning a large fraction of rows, it beats an index. Sequential reads are also cheaper per page than random ones (`seq_page_cost` 1.0 versus `random_page_cost` 4.0). It is bad when paired with a large `Rows Removed by Filter`.

**`Index Scan`** — descend the B-tree, then fetch each matching row from the heap. Two structures touched per row. Good for high selectivity — few rows out of many.

**`Index Only Scan`** — answered entirely from the index, no heap access, *provided* the visibility map says the page is all-visible. `Heap Fetches: 0` is the healthy state; a large number means `VACUUM` is behind and the "index only" scan is secretly visiting the heap anyway. This is [[covering-indexes]] and [[mvcc]] meeting in one line of output.

**`Bitmap Heap Scan`** with a `Bitmap Index Scan` beneath — the middle strategy. Collect all matching row locations in a bitmap first, sort them into physical page order, then read the heap **sequentially**. Chosen when too many rows for individual random fetches but too few for a full scan. The `Recheck Cond` line appears because a bitmap can degrade from exact row locations to whole pages when it grows large (`lossy`), forcing a re-test of the condition.

Seeing `Bitmap Heap Scan` is normal and usually fine. Seeing `Rows Removed by Index Recheck` with a large number means the bitmap went lossy — a `work_mem` signal.

---

## Part 4 — The options worth knowing

```sql
EXPLAIN (ANALYZE, BUFFERS, VERBOSE, SETTINGS) SELECT ...;
```

| Option | Default | What it adds |
|---|---|---|
| `ANALYZE` | `FALSE` | "Carry out the command and show actual run times and other statistics" |
| `BUFFERS` | `FALSE`, but **implied by `ANALYZE`** | shared/local/temp blocks hit, read, dirtied, written |
| `VERBOSE` | `FALSE` | output column list per node, schema-qualified names |
| `SETTINGS` | `FALSE` | "configuration parameters affecting query planning with values different from built-in defaults" |
| `WAL` | `FALSE` | WAL records and bytes generated — for write-heavy analysis |
| `TIMING` | `TRUE` | per-node timing; set `OFF` when the clock overhead distorts results |
| `GENERIC_PLAN` | `FALSE` | plan a parameterised query without values. **Cannot be combined with `ANALYZE`** |
| `FORMAT` | `TEXT` | `JSON` / `YAML` / `XML` for tooling |
| `MEMORY` | `FALSE` | planner memory consumption |

`SETTINGS` is underused and very effective in an unfamiliar environment — it shows exactly which planner-relevant settings are non-default, which often explains a plan immediately.

On `TIMING`: "The overhead of repeatedly reading the system clock can slow down the query significantly on some systems, so it may be useful to set this parameter to `FALSE` when only actual row counts, and not exact times, are needed. Run time of the entire statement is always measured."

`GENERIC_PLAN` answers a question that is otherwise hard to reach: what plan does the *prepared statement* form of this query get? It closes the loop on the custom-versus-generic plan behaviour from [[query-planning]].

### `BUFFERS` — where the I/O actually went

```
Buffers: shared hit=4523 read=812 dirtied=3
                 ^^^        ^^^^
                 |          had to go to the OS/disk
                 served from shared_buffers
```

This is [[buffer-pool]] made observable. A high `read` count on a repeated query means the working set does not fit in `shared_buffers`. `temp read/written` appearing at all means something spilled — a sort or a hash — and connects straight back to `work_mem`.

Buffer counts are also **more stable than timings**, because they do not depend on cache warmth or machine load. When comparing two plan variants, buffer counts often give a cleaner comparison than milliseconds.

### Planning time versus execution time

> "The `Planning time` shown by `EXPLAIN ANALYZE` is the time it took to generate the query plan from the parsed query and optimize it. It does not include parsing or rewriting."

> "The `Execution time` ... includes executor start-up and shut-down time, as well as the time to run any triggers that are fired, but it does not include parsing, rewriting, or planning time."

Two things this exposes. If planning time rivals execution time, the query is trivial and a prepared statement will help. And because execution time **includes trigger time**, a mysteriously slow `INSERT` whose plan looks trivial is usually a trigger — the plan will not show you the trigger's own work, but the total will account for it.

---

## Part 5 — A worked reading

```
Nested Loop  (cost=0.43..8912.55 rows=12 width=72)
             (actual time=0.052..41238.881 rows=48213 loops=1)
  ->  Seq Scan on merchants m  (cost=0.00..12.40 rows=4 width=32)
                               (actual time=0.011..0.204 rows=40 loops=1)
        Filter: (category = 'RETAIL')
        Rows Removed by Filter: 0
  ->  Index Scan using idx_txn_merchant on transactions t
        (cost=0.43..2222.51 rows=3 width=40)
        (actual time=0.094..1030.412 rows=1205 loops=40)
        Index Cond: (merchant_id = m.merchant_id)
        Filter: (status = 'SUCCESS')
        Rows Removed by Filter: 8734
```

Reading it in the diagnostic order:

1. **Estimate gaps.** Top node: 12 estimated, 48,213 actual — 4,000× off. But that is the echo. Go lower. The `Seq Scan` is 4 versus 40 (10×, acceptable). The `Index Scan` is 3 versus 1,205 — **400× off, and this is the lowest divergence.** That is the cause.
2. **Multiply by loops.** `1030.412 ms × 40 loops ≈ 41 seconds`, which matches the top node's actual time. The inner node is the entire query.
3. **Self cost.** Everything is in the inner index scan.
4. **Warning signs.** `Rows Removed by Filter: 8734` per loop, ×40 = ~350,000 rows fetched from the heap and discarded. The index found rows by `merchant_id`, but `status` was filtered **after** the fetch.

**Diagnosis:** the index covers `merchant_id` only, so `status = 'SUCCESS'` is a post-fetch filter, and the planner's estimate of 3 rows per merchant was 400× low.

**Fix:** a composite index on `(merchant_id, status)` moves `status` into the `Index Cond`, eliminates the 350,000 discarded heap fetches, and gives the planner a far better estimate. See [[composite-indexes]].

Note that "use a hash join instead" was never the answer. The join algorithm was a *consequence* of the bad estimate — the same conclusion as [[join-algorithms]].

---

## Practical habits

- **Run it twice.** The first run pays cold-cache costs. The second reflects steady state. Compare `shared read` between them to see the difference.
- **`EXPLAIN (ANALYZE, BUFFERS)` as the default incantation.** Timings vary with load; buffer counts do not.
- **`BEGIN; ... ROLLBACK;` around any write.**
- **Read bottom-up for *what happened*, top-down for *what it cost*.** Rows flow up from the scans; costs accumulate down from the root.
- **Predict before you run.** Write down which scan and join type you expect. The cases where you are wrong are where the learning is — and this is exactly the Week 1 deliverable.
- **`FORMAT JSON`** when a plan is too large to read, so a visualiser can render it.

## The one-line summary

> Find the **lowest** node where estimated and actual rows diverge sharply. Multiply anything under a nested loop by `loops`. Everything else is downstream of those two numbers.

---

## Clarifications

### `Index Cond` versus `Filter` — what `Rows Removed by Filter` actually measures

Added after recall mistook this line for a statement about access strategy. It is not. It counts **rows this node read and then discarded** because they failed a filter condition — a measure of wasted work, and it appears on index scans just as readily as on sequential scans.

| | Applied where | Cost of a non-matching row |
|---|---|---|
| **`Index Cond`** | during the B-tree traversal | **never visited** — the index entry is skipped |
| **`Filter`** | after the row is retrieved | **fully paid** — heap fetch performed, then discarded |

A row counted by `Rows Removed by Filter` is one the engine already went to the heap for: it paid the page access, read the tuple, checked visibility, and dropped it. So `Rows Removed by Filter: 3000000` on a node emitting 12 rows means three million heap fetches were performed and wasted.

**The fix is therefore more specific than "create an index"** — an index often already exists. The goal is to move the predicate *from* `Filter` *into* `Index Cond`:

```
idx(merchant_id)          -> Index Cond: merchant_id     Filter: status    <- 8734 wasted
idx(merchant_id, status)  -> Index Cond: merchant_id AND status            <- 0 wasted
```

**Diagnostic reflex:** a `Filter` line on an index scan with a large `Rows Removed` count is the question *"can that predicate become part of the index?"* — which is what composite index design exists to answer. See [[composite-indexes]].

### Why `BUFFERS` beats timing when comparing two plans

Two engineers benchmark the same fix on the same machine and disagree about whether it helped. Both read the plan correctly. The difference is which *number* they trusted.

Timings depend on cache warmth, background load, and whatever else the machine was doing. **Buffer counts do not** — they are a deterministic count of pages touched.

```
Buffers: shared hit=200000 read=812   ->   shared hit=1500 read=40
```

That is a real collapse in work, whatever the clock said on any single run.

**The consequence that matters for practice: on a small, fully-cached dataset a bad plan and a good plan can take almost the same wall-clock time.** Every table fits in memory, so nothing has to be read from disk either way, and the timings barely separate. The buffer counts still separate cleanly.

This is the concrete reason `EXPLAIN (ANALYZE, BUFFERS)` should be the default incantation rather than plain `EXPLAIN ANALYZE`, and it matters *most* on small practice datasets — exactly where timing-based comparison is least informative.

### Do the loop arithmetic explicitly

Reading `(actual time=0.014 rows=3 loops=50000)` as "higher than it looks" is correct but not usable. Convert it on the page:

```
0.014 ms x 50,000 loops  ~= 700 ms
3 rows   x 50,000 loops   = 150,000 rows
```

"It's 700 ms and 150,000 rows" is a diagnosis. "It's higher" is not.
