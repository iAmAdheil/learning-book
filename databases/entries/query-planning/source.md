---
slug: query-planning
title: Query Planning & Optimization — How the Database Picks a Plan
topic: databases
bloom-level: some
created: 2026-08-31
updated: 2026-09-01
published: 2026-09-03
related: [join-algorithms, sql-fundamentals, btree-indexes, composite-indexes, covering-indexes, buffer-pool, window-functions, explain-analyze, statistics-cardinality]
tags: [query-planner, cost-based-optimizer, query-path, parser, query-tree, rewrite-system, view-expansion, path-vs-plan, plan-tree, executor, cost-model, startup-cost, total-cost, cardinality, selectivity, pg-class, reltuples, relpages, pg-statistic, pg-stats, analyze, default-statistics-target, geqo, geqo-threshold, join-ordering, system-r, selinger, dynamic-programming, predicate-pushdown, subquery-flattening, constant-folding, cte-inlining, volatile-function, column-independence-assumption, prepared-statement, generic-plan, custom-plan, plan-cache-mode, enable-seqscan, interview-priority]
sources:
  - title: "PostgreSQL Documentation — 52.1. The Path of a Query"
    url: "https://www.postgresql.org/docs/current/query-path.html"
  - title: "PostgreSQL Documentation — 52.5. Planner/Optimizer"
    url: "https://www.postgresql.org/docs/current/planner-optimizer.html"
  - title: "PostgreSQL Documentation — 14.2. Statistics Used by the Planner"
    url: "https://www.postgresql.org/docs/current/planner-stats.html"
  - title: "PostgreSQL Documentation — 61.1. Query Handling as a Complex Optimization Problem (GEQO)"
    url: "https://www.postgresql.org/docs/current/geqo-intro.html"
  - title: "PostgreSQL Documentation — 20.7. Query Planning (cost constants)"
    url: "https://www.postgresql.org/docs/current/runtime-config-query.html"
---

## Answer

[[sql-fundamentals]] established that SQL says **what**, never **how**. [[join-algorithms]] showed there are three different *hows* for a single join, and that they are not interchangeable.

The planner is the component that closes that gap. It is not a translator — a translator would have one output. It is a **search engine with a cost function**:

1. Enumerate many different physical strategies that all produce the same result set.
2. Estimate a cost for each.
3. Execute the cheapest one.

Everything that ever goes right or wrong with query performance is downstream of those three steps. And step 2 is the weak one — the planner never measures, it only *predicts*, from approximate statistics gathered earlier. **The planner does not choose the fastest plan. It chooses the plan it estimates to be cheapest.** Those differ exactly when the estimates are wrong, which is the root of nearly every performance mystery.

---

## Part 1 — The path of a query

Five stages, each producing a distinct artifact. Knowing where each stage sits explains a surprising number of behaviours.

```
SQL text
   |
   v  PARSER          -> query tree      (syntax only; does it parse? do these tables exist?)
   |
   v  REWRITE SYSTEM  -> query tree'     (views expanded, rules applied, RLS policies injected)
   |
   v  PLANNER         -> plan tree       (paths generated, costed, cheapest expanded)
   |
   v  EXECUTOR        -> rows            (walks the plan tree, calls the storage layer)
```

**Parser.** "The *parser stage* checks the query transmitted by the application program for correct syntax and creates a *query tree*." Syntax and name resolution only. No decisions about performance are made here.

**Rewrite system.** "The *rewrite system* takes the query tree created by the parser stage and looks for any *rules* (stored in the *system catalogs*) to apply to the query tree. It performs the transformations given in the *rule bodies*."

The important consequence is views:

> "One application of the rewrite system is in the realization of *views*. Whenever a query against a view (i.e., a *virtual table*) is made, the rewrite system rewrites the user's query to a query that accesses the *base tables* given in the *view definition* instead."

**A view is not a stored result. It is a substitution performed before planning.** This is why a plain view has no inherent performance cost, why the planner can push your outer `WHERE` clause down inside a view's definition, and why a five-level stack of views can produce a monstrous plan — by planning time it is one enormous flattened query. It is also why a materialized view is a genuinely different object: that one *does* store rows.

**Planner/optimizer.** The stage this entry is about:

> "The *planner/optimizer* takes the (rewritten) query tree and creates a *query plan* that will be the input to the *executor*. It does so by first creating all possible *paths* leading to the same result... Next the cost for the execution of each path is estimated and the cheapest path is chosen. The cheapest path is expanded into a complete plan that the executor can use."

**Executor.** "The executor recursively steps through the *plan tree* and retrieves rows in the way represented by the plan. The executor makes use of the *storage system* while scanning relations, performs *sorts* and *joins*, evaluates *qualifications* and finally hands back the rows derived."

### Paths versus plans

A small internal distinction with real explanatory power.

A **path** is a lightweight sketch: "scan `transactions` via `idx_txn_merchant`, producing rows in merchant order, costing 0.29..842.11". The planner generates many paths per relation and per join, keeping only the ones that are not dominated by a cheaper alternative.

A **plan** is the fully expanded executable tree, built from the single winning path at the end.

The planner therefore explores in a cheap currency and materialises only once. It also explains why a path is kept even when it looks more expensive: a path with a **useful sort order** may win later by removing a sort above it. Cheapest-total is not the only thing the planner tracks.

---

## Part 2 — The cost model

Every path is reduced to one number, in an abstract unit anchored on a single sequential page read.

| Constant | Default | Meaning (docs) |
|---|---|---|
| `seq_page_cost` | 1.0 | "the cost of a disk page fetch that is part of a series of sequential fetches" |
| `random_page_cost` | 4.0 | "the cost of a non-sequentially-fetched disk page" |
| `cpu_tuple_cost` | 0.01 | "the cost of processing each row during a query" |
| `cpu_index_tuple_cost` | 0.005 | "the cost of processing each index entry during an index scan" |
| `cpu_operator_cost` | 0.0025 | "the cost of processing each operator or function executed" |

The unit is arbitrary. **It is not milliseconds and it does not convert to milliseconds.** Only ratios between plans matter.

Two facts about the model that matter more than the numbers:

**1. Cost is a pair, not a single number.** `EXPLAIN` prints `cost=0.29..8.31`:

```
cost=<startup>..<total>
      ^          ^
      |          cost to return ALL rows
      cost before the FIRST row can be returned
```

Startup cost is why the planner's choice changes under `LIMIT`. A sort or a hash build must complete before emitting anything, so both carry a high startup cost. A nested loop with an index scan streams — near-zero startup. Add `LIMIT 10` and plans with cheap startup suddenly win, because the total cost is never paid. This is the mechanism behind the classic surprise that adding a `LIMIT` makes a query *slower*: it flipped the plan to one that streams but has a bad worst case.

**2. Cost is derived from cardinality.** Every cost is essentially `rows × per-row-cost + pages × per-page-cost`. So a cost estimate is only as good as the **row count** estimate feeding it — and row counts compound upward through the tree. An error at a leaf scan is multiplied by every join above it.

> **Cardinality estimation is the hard problem. Costing is arithmetic on top of it.**

That is why `EXPLAIN ANALYZE` is worth more than `EXPLAIN`: it prints estimated *and* actual rows side by side, exposing exactly where the compounding began.

### Where the numbers come from

Two catalogs, both populated offline.

> "One component of the statistics is the total number of entries in each table and index, as well as the number of disk blocks occupied by each table and index. This information is kept in the table `pg_class`, in the columns `reltuples` and `relpages`."

And crucially:

> "For efficiency reasons, `reltuples` and `relpages` are not updated on-the-fly, and so they usually contain somewhat out-of-date values. They are updated by `VACUUM`, `ANALYZE`, and a few DDL commands such as `CREATE INDEX`."

Column-level distribution data lives in `pg_statistic`, readable through the `pg_stats` view:

> "Entries in `pg_statistic` are updated by the `ANALYZE` and `VACUUM ANALYZE` commands, and are **always approximate even when freshly updated**."

`default_statistics_target` controls the detail level — "The default limit is presently 100 entries" — and raising it "might allow more accurate planner estimates to be made, particularly for columns with irregular data distributions, at the price of consuming more space in `pg_statistic` and slightly more time to compute the estimates."

**The load-bearing point: statistics are a sampled snapshot, taken at some past moment, and approximate by design.** The planner is reasoning about a photograph of the table, not the table. Every planner failure mode traces back to that sentence. The mechanics of how those samples become selectivity estimates is the next topic in this week's sequence.

---

## Part 3 — The search

Costing one plan is easy. The difficulty is that there are enormously many plans.

> "The number of possible query plans grows exponentially with the number of joins in the query."

For N tables the join orderings alone number N factorial before you even choose an algorithm for each join — and each join has three algorithm choices and each table several access methods. A 10-table query has billions of candidate plans.

Postgres uses the System R approach from Selinger et al. (1979): build up **bottom-up**, computing the best plan for every subset of relations of size 1, then 2, then 3, reusing the smaller answers. This is dynamic programming, and it works because of an assumption — that the best plan for a large set can be built from best plans for its subsets.

> "If the query uses fewer than `geqo_threshold` relations, a near-exhaustive search is conducted to find the best join sequence. The planner preferentially considers joins between any two relations for which there exists a corresponding join clause in the `WHERE` qualification ... Join pairs with no join clause are considered only when there is no other choice, that is, a particular relation has no available join clauses to any other relation."

That second sentence is a real pruning rule: the planner will not consider a Cartesian product unless it has no alternative, which collapses the search space dramatically for normally-shaped queries.

Past the threshold (default **12**), exhaustive search is abandoned:

> "The normal PostgreSQL query optimizer performs a *near-exhaustive search* over the space of alternative strategies. This algorithm, first introduced in IBM's System R database, produces a near-optimal join order, but can take an enormous amount of time and memory space when the number of joins in the query grows large. This makes the ordinary PostgreSQL query optimizer inappropriate for queries that join a large number of tables."

Above the threshold a genetic algorithm takes over. **GEQO is randomised**, so a very wide query can plan differently between runs. If a 15-way join has performance that varies for no visible reason, this is the first thing to check.

### Planning is not free

The search itself costs CPU, on every execution. For a short query against a well-indexed table, planning can genuinely exceed execution.

This is what prepared statements address. On the first executions Postgres builds a **custom plan** using the actual parameter values. After roughly five executions it compares the average custom-plan cost against a **generic plan** built without knowing the values, and switches to the generic plan if it is not more expensive. `plan_cache_mode` forces either behaviour.

The trade-off is real in both directions. A generic plan skips planning cost but cannot adapt to skewed parameters — a query filtered on a value present in 0.01% of rows and one present in 60% of rows want completely different plans, and a generic plan serves one of them badly.

---

## Part 4 — What the planner does *for* you

Rewrites the planner applies before costing anything. Knowing these prevents a lot of pointless hand-optimisation.

| Transformation | Effect |
|---|---|
| **View expansion** | the view's definition is inlined into the query tree |
| **Subquery flattening** | a simple subquery in `FROM` is pulled up and merged into the outer query |
| **Predicate pushdown** | `WHERE` conditions are moved as close to the scans as possible, including inside views and flattened subqueries |
| **Constant folding** | `WHERE x > 2 + 3` becomes `WHERE x > 5` once, not per row |
| **Join reordering** | the written order is ignored; see [[join-algorithms]] |
| **CTE inlining** | since PG12, non-recursive side-effect-free CTEs referenced once are merged — see [[sql-fundamentals]] |
| **`IN` to semi-join** | `IN (subquery)` and `EXISTS` typically compile to the same semi-join |
| **Redundant `DISTINCT` removal** | dropped when the result is provably unique already |

The practical consequence: **rewriting a query into a "smarter" shape usually changes nothing**, because the planner already normalises both shapes to the same internal form. Time spent reordering joins or converting `IN` to `EXISTS` for speed is time not spent on the index or the statistics that would actually matter.

## Part 5 — What the planner cannot do

The honest limits. Each one is a category of problem no amount of query rewriting will fix.

1. **It cannot create an index.** If no access path exists, the cheapest plan is still a sequential scan. The planner picks among what it has.
2. **It assumes columns are independent.** Selectivity for `WHERE city = 'Mumbai' AND state = 'Maharashtra'` is estimated as the *product* of the two selectivities. For correlated columns this underestimates severely — and underestimates are what select a nested loop over a huge relation. Extended statistics (`CREATE STATISTICS`) exist precisely to patch this.
3. **It cannot see through opaque expressions.** `WHERE lower(email) = 'x'` or a user-defined function in a predicate gives it no distribution to work from, so it falls back to a hardcoded default guess. An expression index restores both the access path and the statistics.
4. **It cannot see through `VOLATILE` functions**, and must re-evaluate them per row rather than folding or caching.
5. **It has no feedback loop.** Postgres does not learn that yesterday's estimate was wrong by a factor of 10,000. Every planning run starts from the same stale statistics and repeats the same mistake until `ANALYZE` runs.
6. **It optimises estimated cost, not measured time.** The cost model encodes assumptions — notably the 4:1 `random_page_cost` to `seq_page_cost` ratio, which describes a spinning disk. On SSDs that penalty is too high and makes index scans look artificially expensive; lowering `random_page_cost` toward 1.1 is the standard correction.

---

## The two failure modes

Every bad plan resolves to one of two causes, and the distinction determines the fix.

| | **Bad cardinality estimate** | **Bad cost model** |
|---|---|---|
| Symptom | `EXPLAIN ANALYZE` shows a large estimated-vs-actual row gap | estimates are accurate but the plan is still poor |
| Typical cause | stale `ANALYZE`, correlated columns, opaque expressions | `random_page_cost` wrong for the hardware, `work_mem` too small |
| Fix | `ANALYZE`, `CREATE STATISTICS`, expression index, raise the statistics target | tune the cost constants or the memory settings |
| Frequency | **the overwhelming majority** | uncommon |

Check the estimate gap first, every time. This is the same conclusion reached from the other direction in [[join-algorithms]]:

> **When a plan goes wrong, the plan is rarely the bug. Trace back to the estimate that produced it.**

## What you actually control

| Lever | What it changes |
|---|---|
| **Indexes** | which paths exist at all — the largest lever by far |
| **`ANALYZE` / autovacuum tuning** | accuracy of the estimates driving every decision |
| **`CREATE STATISTICS`** | fixes the column-independence assumption for correlated columns |
| **`ALTER TABLE ... SET STATISTICS`** | more histogram detail on a specific skewed column |
| **`random_page_cost`** | corrects the cost model for SSDs |
| **`work_mem`** | whether hash joins and sorts stay in memory |
| **Query shape** | far less than people think — the planner normalises most of it away |

**On the `enable_*` switches** (`enable_seqscan`, `enable_nestloop`, `enable_hashjoin`, ...): these are **diagnostics, not tuning knobs**. Turning one off in a session and re-running `EXPLAIN` reveals the planner's second choice and its estimated cost, which tells you how close the decision was. They add a large constant penalty rather than truly forbidding the plan type, so a plan can still appear with them off. Never set them in application configuration — if a plan is wrong, the cause is an index or a statistic.

---

## Reading it in `EXPLAIN`

Everything above appears in one annotated line:

```
Index Scan using idx_txn_merchant on transactions t
  (cost=0.29..842.11 rows=1200 width=64)
        ^^^^  ^^^^^^      ^^^^       ^^
        |     |           |          average row size in bytes
        |     |           ESTIMATED row count  <-- the number that matters
        |     total cost (all rows)
        startup cost (before the first row)
```

The reading order that matters:

1. **`rows=`** — the estimate. With `ANALYZE`, compare against actual. This is the diagnosis.
2. **`cost=a..b`** — the gap between `a` and `b` tells you whether the node streams or blocks.
3. **The node type** — which access path and join algorithm won.

That output is the next topic, and this entry is the model it renders.
