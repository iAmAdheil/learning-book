---
slug: join-algorithms
title: Join Algorithms — Nested Loop, Hash Join & Merge Join
topic: databases
bloom-level: some
created: 2026-08-24
updated: 2026-09-01
published: 2026-09-03
related: [sql-fundamentals, window-functions, btree-indexes, composite-indexes, covering-indexes, buffer-pool, heap-storage-layout, clustered-vs-nonclustered-indexes, query-planning, explain-analyze, statistics-cardinality]
tags: [join-algorithms, nested-loop-join, hash-join, merge-join, query-planner, cost-based-optimizer, inner-relation, outer-relation, build-phase, probe-phase, batching, spill-to-disk, work-mem, hash-mem-multiplier, sort-merge, index-scan, memoize, materialize, equijoin, range-join, full-outer-join, cardinality-estimation, row-estimate, plan-regression, seq-page-cost, random-page-cost, geqo, geqo-threshold, join-ordering, selinger, n-plus-1, enable-nestloop, enable-hashjoin, enable-mergejoin, interview-priority]
sources:
  - title: "PostgreSQL Documentation — 52.5. Planner/Optimizer"
    url: "https://www.postgresql.org/docs/current/planner-optimizer.html"
  - title: "PostgreSQL Documentation — 20.7. Query Planning (planner method config and cost constants)"
    url: "https://www.postgresql.org/docs/current/runtime-config-query.html"
  - title: "PostgreSQL Documentation — 20.4. Resource Consumption (work_mem, hash_mem_multiplier)"
    url: "https://www.postgresql.org/docs/current/runtime-config-resource.html"
  - title: "PostgreSQL Documentation — 7.2. Table Expressions (join semantics)"
    url: "https://www.postgresql.org/docs/current/queries-table-expressions.html"
---

## Answer

`JOIN` is a word in a language. It is not an algorithm. When you write

```sql
FROM transactions t JOIN merchants m ON t.merchant_id = m.merchant_id
```

you have specified a **result set** — which pairs of rows belong together. You have said nothing about how to find them. The planner must choose, and there are exactly three ways it can.

This is where the declarative half of [[sql-fundamentals]] finally meets the physical half you already know. [[btree-indexes]] told you how to find one row fast. [[buffer-pool]] told you how pages get into memory. [[heap-storage-layout]] told you what a page contains. Join algorithms are the layer that decides **which of those capabilities the query actually uses**, and it is the layer `EXPLAIN` reports on.

### One question, three answers

Every join algorithm answers the same question:

> **Given a row from table A, how do I find its matching rows in table B?**

That is a lookup problem, and computer science has three standard answers to a lookup problem. The database uses all three:

| Answer | Algorithm | Everyday analogue |
|---|---|---|
| Search B from scratch, every time | **Nested loop** | scanning a list linearly |
| Build an index of B once, then look up | **Hash join** | building a hash map |
| Sort both, then walk them together | **Merge join** | merging two sorted lists |

None is "the fast one". Each wins in a regime the others lose, and the planner's job is to guess which regime it is in — a guess it makes from statistics, which is why bad statistics produce catastrophically bad joins.

The cost-based approach itself dates to Selinger et al.'s 1979 System R paper *"Access Path Selection in a Relational Database Management System"*, which established the model every mainstream planner still uses: enumerate the plans, estimate a cost for each, pick the cheapest.

---

## 1. Nested Loop Join

> "The right relation is scanned once for every row found in the left relation. This strategy is easy to implement but can be very time consuming. (However, if the right relation can be scanned with an index scan, this can be a good strategy. It is possible to use values from the current row of the left relation as keys for the index scan of the right.)"

```
for each row R1 in OUTER relation:        -- scanned once
    for each row R2 in INNER relation:    -- rescanned for EVERY outer row
        if join_condition(R1, R2):
            emit (R1, R2)
```

**Terminology that matters for reading plans:** the **outer** relation is the one driving the loop, and it appears *first* (upper) in `EXPLAIN` output. The **inner** relation is rescanned. Postgres's prose calls these left and right.

### The two completely different performances

Naively this is **O(N × M)** and it is as bad as it sounds. 300 customers against 3,120 transactions is 936,000 comparisons for a result of a few thousand rows.

But read the parenthetical in the docs again, because it is the whole point:

```
Nested Loop
  ->  Seq Scan on merchants m           (N = 40 rows)
  ->  Index Scan using idx_txn_merchant on transactions t
        Index Cond: (merchant_id = m.merchant_id)     <-- the outer row's value
```

With an index on the inner side's join key, the inner "scan" is a B-tree descent, not a table scan. The cost becomes **O(N × log M)**, and if N is small that is the best plan available — better than hash or merge, because it never touches the rows it does not need.

**So the real rule is not "nested loops are slow". It is:**

> A nested loop is excellent when the outer side is **small** and the inner side is **indexed on the join key**. It is a disaster when the outer side is large or the inner side has no usable index.

This is also the **only** algorithm that can exploit an index on the inner relation, because it is the only one that looks up one value at a time. Hash and merge joins consume their inputs wholesale.

### It is the N+1 problem, in the right place

The loop above is structurally identical to the application-level N+1 antipattern: fetch a list, then issue one query per element. The difference is entirely about **where** the loop runs.

| | Inside the engine | In application code |
|---|---|---|
| Per-iteration cost | a B-tree descent, pages likely in `shared_buffers` | a full network round trip + parse + plan |
| Typical cost | microseconds | ~1 ms or more |
| Planner can see it? | yes — costs and may reject it | no |

Same loop, three orders of magnitude apart. That is why "push the join into the database" is advice rather than dogma, and it is the direct link to the N+1 topic later this week.

### `Materialize` and `Memoize`

Two nodes you will meet underneath nested loops, both there to make rescanning cheaper.

- **`Materialize`** caches the inner relation's rows once so later iterations read from memory instead of re-executing the scan. "It is impossible to suppress materialization entirely, but turning this variable off prevents the planner from inserting materialize nodes except in cases where it is required for correctness."
- **`Memoize`** (PostgreSQL 14+) caches results *per parameter value*: "Enables or disables the query planner's use of memoize plans for caching results from parameterized scans inside nested-loop joins. This plan type allows scans to the underlying plans to be skipped when the results for the current parameters are already in the cache."

`Memoize` is the planner applying the exact fix you would apply to an N+1 in application code — remembering the answer for a repeated key. It pays off when outer values repeat.

---

## 2. Hash Join

> "the right relation is first scanned and loaded into a hash table, using its join attributes as hash keys. Next the left relation is scanned and the appropriate values of every row found are used as hash keys to locate the matching rows in the table."

Two phases:

```
BUILD phase:  scan the INNER (build) relation once
              -> hash each row on the join key
              -> store it in an in-memory hash table

PROBE phase:  scan the OUTER (probe) relation once
              -> hash each row's join key
              -> look it up in the table, emit any matches
```

**Cost: O(N + M).** Each side is read exactly once. No sorting, no repeated scanning. For two large unsorted tables with no useful index, nothing beats it.

In `EXPLAIN` the build side is always the one under the `Hash` node:

```
Hash Join
  Hash Cond: (t.merchant_id = m.merchant_id)
  ->  Seq Scan on transactions t          <-- probe side (large)
  ->  Hash
        ->  Seq Scan on merchants m       <-- build side (small)
```

**The planner builds the hash table on the smaller side**, because the table has to fit in memory. That is a cost decision, not a syntax one — writing the tables in the other order changes nothing.

### Restriction: equality only

A hash table answers "which rows have exactly this key?" It cannot answer "which rows have a key less than this one." So:

> **A hash join can only implement an equijoin.** Any join condition using `<`, `>`, `BETWEEN`, or a range overlap is not hashable.

This is a hard capability limit, not a preference. It is the most useful single fact in this entry, because it explains plans that otherwise look irrational — the planner did not "choose" a nested loop over your million-row range join, it had no alternative.

### The memory cliff

The hash table lives in the executor's own working memory, **not** in `shared_buffers`. This is a genuinely separate allocation from [[buffer-pool]], and conflating the two is a common misunderstanding.

> "Sets the base maximum amount of memory to be used by a query operation (such as a sort or hash table) before writing to temporary disk files ... The default value is four megabytes (`4MB`)."

> "Hash-based operations are generally more sensitive to memory availability than equivalent sort-based operations. The memory limit for a hash table is computed by multiplying `work_mem` by `hash_mem_multiplier`."

`hash_mem_multiplier` defaults to **2.0**, so a hash table's real budget is `work_mem × 2` — 8 MB by default.

When the build side does not fit, the join does not fail. It **batches**: both inputs are partitioned by hash value and spilled to temporary files, then processed one partition pair at a time. Correct, and dramatically slower. `EXPLAIN ANALYZE` reports it directly:

```
Buckets: 1024  Batches: 16  Memory Usage: 8193kB
                        ^^ anything above 1 means it spilled
```

**`Batches: 1` is the healthy state.** Seeing a large batch count is one of the highest-value signals in a plan, and it usually has two possible causes: `work_mem` is genuinely too small, or the row estimate was wrong and the planner sized the table for far fewer rows than arrived.

And the warning the docs attach to raising it: "a complex query might perform several sort and hash operations at the same time, with each operation generally being allowed to use as much memory as this value specifies ... Also, several running sessions could be doing such operations concurrently. Therefore, the total memory used could be many times the value of `work_mem`." `work_mem` is **per operation, per session** — not a server-wide budget. Multiplying it by your connection count is the number that matters, which ties directly to connection pooling later in the plan.

---

## 3. Merge Join

> "Each relation is sorted on the join attributes before the join starts. Then the two relations are scanned in parallel, and matching rows are combined to form join rows. This kind of join is attractive because each relation has to be scanned only once. The required sorting might be achieved either by an explicit sort step, or by scanning the relation in the proper order using an index on the join key."

```
sort A on join key            (or read it already sorted)
sort B on join key            (or read it already sorted)
walk both with two cursors, advancing whichever side is behind
```

**Cost: O(N log N + M log M)** when sorting is needed — dominated by the sorts. But that last sentence in the docs is the interesting one:

> **If an index already supplies the order, the sort disappears and the join is O(N + M) with no memory pressure at all.**

That is [[btree-indexes]] cashing out. A B-tree is a sorted structure, so an index scan on the join key emits rows in join-key order for free. In `EXPLAIN` the difference is visible immediately:

```
Merge Join
  ->  Index Scan using merchants_pkey on merchants     <-- free ordering
  ->  Materialize
        ->  Sort                                        <-- paid ordering
              Sort Key: t.merchant_id
              ->  Seq Scan on transactions t
```

### Its two advantages over hash join

1. **It handles inequality conditions.** Sorted order supports `<`, `>` and range predicates, which a hash table cannot. Merge join and nested loop are the only options for a range join.
2. **It degrades gracefully on memory.** A sort that exceeds `work_mem` spills to an external merge sort, which is a well-behaved, predictable slowdown. A hash join that exceeds its budget re-partitions everything, which is sharper.

Merge join tends to win for **two large, already-sorted (or cheaply sortable) inputs** — classically two big tables joined on their primary keys.

---

## The decision table

This is the part worth being able to reproduce cold.

| | Nested Loop | Hash Join | Merge Join |
|---|---|---|---|
| **Cost** | O(N × M), or **O(N × log M)** with an inner index | O(N + M) | O(N log N + M log M), or **O(N + M)** if pre-sorted |
| **Needs an index?** | to be good, yes — on the **inner** join key | no | helps enormously; removes the sort |
| **Memory** | negligible | build side must fit in `work_mem × hash_mem_multiplier` | sort needs `work_mem`, spills gracefully |
| **Equality only?** | no — any condition | **yes** | no |
| **Best when** | outer side is **small**, inner is **indexed** | one side is small enough to hash; no useful indexes | both sides **large** and **already sorted** |
| **Worst when** | outer is large or inner is unindexed | build side vastly exceeds memory | neither side is sorted and both are huge |
| **Rows arrive** | immediately (streams) | only after the build completes | after sorting completes |

That last row is a subtlety worth knowing: a nested loop can return its first row almost instantly, whereas a hash join must finish building before it emits anything. This is why the planner's choice changes when you add `LIMIT` — cheap-startup plans become attractive when you only need the first few rows.

### One capability note

A `FULL OUTER JOIN` cannot be executed by a nested loop, because the algorithm has no cheap way to identify inner rows that never matched anything. Postgres therefore requires the condition to be hash-joinable or merge-joinable:

```sql
-- ERROR: FULL JOIN is only supported with merge-joinable or hash-joinable join conditions
FROM a FULL JOIN b ON a.x < b.y
```

An error that is otherwise baffling becomes obvious once you know which algorithms can do which job.

---

## What actually goes wrong: the row-estimate cliff

The planner's choice is only as good as its estimate of **how many rows** each side produces. Get that wrong and the algorithm choice inverts from optimal to catastrophic.

The classic failure:

```
Estimated:  Nested Loop, outer produces ~5 rows      -> 5 index lookups. 2 ms.
Reality:    outer produces 500,000 rows              -> 500,000 index lookups. 40 minutes.
```

The plan was *correct* for the statistics it had. It was wrong about the statistics. And note the asymmetry: **a nested loop chosen wrongly degrades without bound**, because the error multiplies. A hash join chosen wrongly merely spills to disk — bad, but bounded. That asymmetry is why a surprise nested loop over a large outer is the single most common cause of a query that used to take 50 ms and now takes an hour.

The signature in `EXPLAIN ANALYZE` is the gap between the two row counts:

```
Nested Loop  (cost=... rows=5 ...) (actual time=... rows=500000 ...)
                          ^^^^^^                          ^^^^^^^^^^
                        estimate                            reality
```

**A large estimate-versus-actual divergence is the root cause to hunt for, not the join type itself.** Changing the join type treats the symptom. Common causes are stale statistics, correlated columns the planner assumes are independent, and expressions it cannot estimate through. That is the Statistics & cardinality estimation topic later this week, and this is why it sits right after this one.

---

## What you actually control

You do not choose the algorithm. You create the conditions under which the planner chooses well.

| Lever | Effect |
|---|---|
| **Index the foreign key / join column** | makes the indexed nested loop and the sort-free merge join possible at all |
| **Match the index to the join key order** | leftmost prefix must cover the join key — see [[composite-indexes]] |
| **Keep statistics fresh** (`ANALYZE`) | the estimates that drive the whole decision |
| **Size `work_mem` for the workload** | keeps hash joins at `Batches: 1` |
| **Filter early and reduce the row count** | a smaller outer side makes a nested loop viable |

**A note on the `enable_*` switches.** `enable_nestloop`, `enable_hashjoin` and `enable_mergejoin` all default to `on`. They are **diagnostic tools, not tuning knobs**: setting `enable_nestloop = off` in a session and re-running `EXPLAIN` tells you what the planner's second choice was and what it cost, which tells you how confident it was. The docs are explicit that the suppression is not even absolute — "It is impossible to suppress nested-loop joins entirely, but turning this variable off discourages the planner from using one if there are other methods available." Never ship them in application configuration. If a plan is wrong, the fix is an index or better statistics.

### Cost constants

The planner converts everything to one abstract unit, anchored on a sequential page read:

| Constant | Default | Meaning |
|---|---|---|
| `seq_page_cost` | 1.0 | "the cost of a disk page fetch that is part of a series of sequential fetches" |
| `random_page_cost` | 4.0 | "the cost of a non-sequentially-fetched disk page" |
| `cpu_tuple_cost` | 0.01 | "the cost of processing each row during a query" |
| `cpu_index_tuple_cost` | 0.005 | "the cost of processing each index entry during an index scan" |
| `cpu_operator_cost` | 0.0025 | "the cost of processing each operator or function executed" |

The 4:1 ratio between random and sequential encodes a spinning disk. On SSDs that penalty is far too high, and lowering `random_page_cost` to roughly 1.1 is the standard adjustment — it makes index scans, and therefore indexed nested loops, look correctly cheaper. This is the same seek-cost story as the clustering factor in [[clustered-vs-nonclustered-indexes]].

---

## A separate decision: join *order*

Choosing an algorithm for one join is not the whole problem. With N tables the planner must also choose the **order** to combine them, and the number of orderings grows factorially.

> "If the query uses fewer than `geqo_threshold` relations, a near-exhaustive search is conducted to find the best join sequence. The planner preferentially considers joins between any two relations for which there exists a corresponding join clause in the `WHERE` qualification ... Join pairs with no join clause are considered only when there is no other choice."

Above the threshold (default **12** relations), exhaustive search becomes too expensive and Postgres switches to a genetic algorithm: "When `geqo_threshold` is exceeded, the join sequences considered are determined by heuristics."

Two consequences worth carrying:

1. **The order you write joins in does not matter** below the threshold. The planner re-orders freely. Ordering tables "smallest first" is folklore.
2. **Above the threshold, planning becomes heuristic and non-deterministic.** Very wide queries — 15-way joins in generated ORM code, for instance — can produce a different plan on different runs. If a query has unstable performance and joins a dozen-plus tables, this is the first thing to check.

---

## Reading it in `EXPLAIN`

Everything above surfaces as three node names and a handful of numbers:

```
Hash Join                          <-- the algorithm
  Hash Cond: (t.merchant_id = m.merchant_id)
  ->  Seq Scan on transactions t   <-- probe side
  ->  Hash
        Buckets: 1024  Batches: 1  Memory Usage: 40kB    <-- Batches: 1 = healthy
        ->  Seq Scan on merchants m                      <-- build side
```

The checklist:

1. **Which of the three node names is it?** `Nested Loop`, `Hash Join`, `Merge Join`.
2. **`rows=` estimated versus `rows=` actual.** A large gap is the root cause of most bad joins.
3. **`Batches:`** on a hash join. Above 1 means it spilled.
4. **`Sort` versus `Index Scan`** under a merge join. A sort means an index could remove it.
5. **Which side is inner** on a nested loop, and is it an `Index Scan` or a `Seq Scan`. A `Seq Scan` on the inner side of a nested loop over a large outer is the emergency signal.

That output is the next topic in this week's sequence, and this entry is what makes it readable.

---

## Clarifications

### Diagnosing a `Hash Join` -> `Nested Loop` regression

Added after recall showed the mechanisms were solid but the diagnostic reasoning was not. Scenario: identical query, unchanged schema, ran in 50 ms for months, now takes 40 minutes, and the plan flipped from `Hash Join` to `Nested Loop`.

**Why this direction of flip is dangerous, and the reverse is not.**

> A wrongly-chosen nested loop degrades **without bound**. A wrongly-chosen hash join degrades by a **bounded** amount.

The nested loop's estimate error *multiplies*, because the estimate becomes the iteration count. Believing the outer side holds 5 rows when it holds 500,000 does not produce a plan that is somewhat too slow — it produces 500,000 index descents instead of 5.

A hash join that guesses wrong spills to disk. Still O(N + M), with a constant factor attached. It cannot run away.

So `Hash Join -> Nested Loop` warrants alarm that `Nested Loop -> Hash Join` does not.

**What to inspect first — not the join type.** The estimated-versus-actual row counts:

```
Nested Loop  (cost=... rows=5 ...) (actual time=... rows=500000 ...)
                          ^^^^^^                          ^^^^^^^^^^
                     what it believed                 what was true
```

The join type is the symptom. The planner chose correctly *for the numbers it had*. Suppressing nested loops papers over a bad estimate that is simultaneously corrupting every other plan on that table.

Causes, in order of likelihood:

1. **Stale statistics** — the table grew and `ANALYZE` has not caught up. Most common, especially after a bulk load.
2. **A crossed cost threshold** — data grew gradually until estimated hash cost exceeded estimated loop cost. Nothing broke; the plan tipped.
3. **Correlated columns** — the planner assumes independence, so `WHERE city = 'Mumbai' AND state = 'Maharashtra'` is estimated as the *product* of two selectivities and comes out far too small. That underestimate is precisely what selects a nested loop.

**The general principle:** when a plan goes wrong, the plan is rarely the bug. Trace back to the estimate that produced it.

### `Batches > 1` has two causes, not one

A spilling hash join is a signal to investigate, not a diagnosis.

1. **`work_mem` is genuinely too small** for the workload.
2. **The row estimate was wrong.** The planner sized the hash table for the rows it expected. If it expected 10,000 and 4 million arrived, the table overflows regardless of how reasonable `work_mem` is.

Same symptom, opposite fixes. Check estimated-versus-actual rows on the **build** side before changing any configuration — otherwise you tune memory forever on what is a statistics problem.

**Precision on the memory risk:** `work_mem` is granted per **operation**, per session — not per transaction. A single query containing three hash joins and two sorts can hold five separate grants by itself. The real multiplier is therefore connections x operations-per-query, not connections alone.

### Why a B-tree supplies merge-join ordering for free

A B-tree's leaf level *is* the keys in sorted order, linked. An index scan on the join key therefore emits rows already in join-key order.

A merge join's precondition is "both inputs sorted on the join key". The index satisfies that as a side effect of existing. There is no sort being skipped, because there was never a sort to perform — which is what lets merge join drop from O(N log N + M log M) to O(N + M). See [[btree-indexes]].

**And the cost of the sort side is worse than CPU plus memory.** A sort exceeding `work_mem` becomes an *external merge sort* and spills to temporary files, adding disk I/O to the bill.

### Capability limit, not fallback

When a range join gets a nested loop or merge join, the planner did not "degrade" to it. A hash table can only answer exact-key lookups, so a non-equality condition leaves exactly two candidates, and the planner costed both and picked the cheaper. Framing it as a capability limit rather than a fallback is what shows the reasoning is understood.
