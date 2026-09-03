---
slug: sql-fundamentals
title: SQL Fundamentals — Joins, Aggregations, Subqueries & CTEs
topic: databases
bloom-level: some
created: 2026-08-24
updated: 2026-09-01
published: 2026-09-03
related: [relational-data-model, schema-design-normalization, btree-indexes, composite-indexes, mvcc, select-for-update-skip-locked, isolation-levels, denormalization, window-functions, join-algorithms, query-planning, explain-analyze]
tags: [sql, select, join, inner-join, left-join, outer-join, cross-join, cartesian-product, on-vs-where, using, natural-join, lateral, join-fan-out, aggregation, group-by, having, count-star, filter-clause, conditional-aggregation, null-semantics, three-valued-logic, subquery, scalar-subquery, correlated-subquery, exists, not-exists, not-in-trap, any-all, anti-join, semi-join, cte, with-query, materialized, not-materialized, optimization-fence, recursive-cte, working-table, data-modifying-cte, returning, logical-evaluation-order, alias-scope, grouping-sets, rollup, cube, interview-priority]
sources:
  - title: "PostgreSQL Documentation — 7.2. Table Expressions (FROM, joins, GROUP BY, HAVING, GROUPING SETS)"
    url: "https://www.postgresql.org/docs/current/queries-table-expressions.html"
  - title: "PostgreSQL Documentation — 7.8. WITH Queries (Common Table Expressions)"
    url: "https://www.postgresql.org/docs/current/queries-with.html"
  - title: "PostgreSQL Documentation — 9.23. Subquery Expressions"
    url: "https://www.postgresql.org/docs/current/functions-subquery.html"
  - title: "PostgreSQL Documentation — SELECT (logical processing order)"
    url: "https://www.postgresql.org/docs/current/sql-select.html"
  - title: "PostgreSQL 12 Release Notes — CTE inlining, MATERIALIZED / NOT MATERIALIZED"
    url: "https://www.postgresql.org/docs/release/12.0/"
---

## Answer

SQL is a **declarative** language. You describe the shape of the answer you want. You do not describe the procedure that produces it. The planner reads that description, consults its statistics, and chooses the procedure — which index to use, whether to run a hash join or a merge join, in what order to combine the tables.

That single fact is the reason this topic is worth real depth, and it is the reason it belongs *after* the storage and index material rather than before it. Someone who has already studied [[btree-indexes]], [[composite-indexes]] and [[mvcc]] knows *how a database executes work*. SQL is the missing half: the language that tells it **what work to do**. Every clause below is a statement about the shape of a result set, and the engine holds a free hand in how it gets there.

Two consequences follow immediately, and they run through the whole topic:

1. **Two queries that look different can produce identical plans**, because they describe the same result set. `IN` and `EXISTS` frequently compile to the same semi-join.
2. **Two queries that look nearly identical can differ enormously**, because one accidentally describes a different result set. A predicate moved from `ON` to `WHERE` is four characters of edit that silently converts an outer join into an inner join.

The skill being built here is reading a query and seeing the *result set it describes*, not the text.

### The master key: logical evaluation order

You **write** clauses in one order. The database **logically evaluates** them in a different one. Almost every "why doesn't this work?" in SQL is a direct consequence of that mismatch.

Postgres documents the order explicitly (`SELECT` reference, Description). Condensed to the clauses that matter daily:

```
1. WITH        -> compute the CTEs
2. FROM/JOIN   -> assemble source rows (multiple FROM items are cross-joined)
3. WHERE       -> discard individual ROWS
4. GROUP BY    -> collapse rows into groups; compute aggregates
   HAVING      -> discard whole GROUPS
5. SELECT      -> compute output expressions  <-- COLUMN ALIASES ARE BORN HERE
6. DISTINCT    -> discard duplicate output rows
7. UNION/INTERSECT/EXCEPT
8. ORDER BY    -> sort
9. LIMIT/OFFSET-> slice
10. FOR UPDATE -> lock the selected rows
```

Step 5 is the load-bearing one. An alias defined in `SELECT` does not exist yet when `WHERE` and `HAVING` run. The docs state the rule directly:

> "An output column's name can be used to refer to the column's value in `ORDER BY` and `GROUP BY` clauses, but not in the `WHERE` or `HAVING` clauses; there you must write out the expression instead."

```sql
-- ERROR:  column "net" does not exist
SELECT amount - COALESCE(refunded, 0) AS net FROM t WHERE net > 100;

-- Works: ORDER BY and GROUP BY run after (or are specially allowed to see) SELECT
SELECT amount - COALESCE(refunded, 0) AS net FROM t ORDER BY net DESC;
```

`GROUP BY` is the odd one. It is step 4, before `SELECT`, yet it can see output names — Postgres calls this out as a deliberate exception: "Although query output columns are nominally computed in the next step, they can also be referenced (by name or ordinal number) in the `GROUP BY` clause."

**This is a *logical* order, not a physical one.** The planner reorders freely. It only has to produce the result *as if* this order held. That distinction is exactly what `EXPLAIN` makes visible, and it is the bridge to the next topic in the sequence.

**The 10-second debugging model:** when a query errors or behaves strangely, ask *at which step does this clause run, and does the thing it references exist yet?*

---

## Part 1 — Joins

### Why: the relational model stores facts once

[[schema-design-normalization]] deliberately scatters one real-world entity across several tables so that each fact is stored exactly once. A join is the inverse operation — the mechanism that reassembles a normalized schema back into the shape the caller wants. Normalization is the write-side decision; joins are the price paid at read time. [[denormalization]] is the choice to stop paying it.

### The mental model that makes every join type obvious

Start from one operation and derive the rest:

> **Form the Cartesian product of both tables. Keep the rows where the condition is true. Then, for outer joins, add back the rows that lost.**

The docs define it exactly this way. `CROSS JOIN`: "For every possible combination of rows from T1 and T2 (i.e., a Cartesian product), the joined table will contain a row consisting of all columns in T1 followed by all columns in T2." N rows × M rows = **N × M rows**.

`INNER JOIN` is that product, filtered: "For each row R1 of T1, the joined table has a row for each row in T2 that satisfies the join condition with R1."

`LEFT OUTER JOIN` is the inner join **plus a repair step**: "First, an inner join is performed. Then, for each row in T1 that does not satisfy the join condition with any row in T2, a joined row is added with null values in columns of T2. Thus, the joined table always has at least one row for each row in T1."

That last sentence is the guarantee worth memorising. `RIGHT` is the mirror image. `FULL` performs both repair steps.

| Join | Keeps | Guarantee |
|---|---|---|
| `CROSS` | every pairing | output = N × M |
| `INNER` | matched pairs only | unmatched rows on both sides vanish |
| `LEFT` | inner + unmatched left, right cols NULL | **≥ 1 row per left row** |
| `RIGHT` | inner + unmatched right, left cols NULL | ≥ 1 row per right row |
| `FULL` | inner + unmatched from both | no input row is lost |

**Note the comma trap.** `FROM T1, T2` is a cross join. `FROM T1 CROSS JOIN T2` ≡ `FROM T1 INNER JOIN T2 ON TRUE` ≡ `FROM T1, T2` — but the docs warn: "This latter equivalence does not hold exactly when more than two tables appear, because `JOIN` binds more tightly than comma." An accidentally omitted `WHERE` on comma-join syntax is how a 300-row and a 3,120-row table become 936,000 rows.

### `ON` vs `USING` vs `NATURAL`

Three ways to spell the condition, with different **output shapes**:

```sql
-- ON: the general form. Any boolean expression.
FROM transactions t JOIN merchants m ON t.merchant_id = m.merchant_id
-- output columns: all of t, then all of m  (merchant_id appears TWICE)

-- USING: shorthand when both sides use the same column name
FROM transactions t JOIN merchants m USING (merchant_id)
-- output columns: merchant_id ONCE, then rest of t, then rest of m

-- NATURAL: USING over every commonly-named column. Do not use this.
FROM transactions NATURAL JOIN merchants
```

`USING` is not merely cosmetic — the docs are precise: "While `JOIN ON` produces all columns from T1 followed by all columns from T2, `JOIN USING` produces one output column for each of the listed column pairs (in the listed order), followed by any remaining columns from T1, followed by any remaining columns from T2." That is why `SELECT *` over a `USING` join is cleaner, and why `USING` also lets you write bare `merchant_id` without qualifying it.

`NATURAL` is a trap and the docs say so: "`NATURAL` is considerably more risky since any schema changes to either relation that cause a new matching column name to be present will cause the join to combine that new column as well." Add a `created_at` column to both tables and every `NATURAL JOIN` between them silently changes meaning. **Never ship it.**

### Gotcha 1 — `ON` vs `WHERE`: the silent inner join

The single highest-yield join gotcha, and the reason it is worth teaching before anything else.

> "A restriction placed in the `ON` clause is processed *before* the join, while a restriction placed in the `WHERE` clause is processed *after* the join. That does not matter with inner joins, but it matters a lot with outer joins."

Take "settlement total per merchant for June — including merchants with no June settlements":

```sql
-- CORRECT: the date test is part of "what counts as a match"
SELECT m.name, COALESCE(SUM(s.amount), 0) AS june_total
FROM merchants m
LEFT JOIN settlements s
       ON s.merchant_id = m.merchant_id
      AND s.settled_on >= DATE '2025-06-01'
      AND s.settled_on <  DATE '2025-07-01'
GROUP BY m.name;

-- WRONG: silently an INNER JOIN
SELECT m.name, COALESCE(SUM(s.amount), 0) AS june_total
FROM merchants m
LEFT JOIN settlements s ON s.merchant_id = m.merchant_id
WHERE s.settled_on >= DATE '2025-06-01'
  AND s.settled_on <  DATE '2025-07-01'
GROUP BY m.name;
```

The second query does produce the padded NULL rows — and then `WHERE` runs and evaluates `NULL >= '2025-06-01'`, which is `NULL`, which is not true, so every padded row is discarded. The `LEFT` keyword is still on the page and has been completely neutralised. A merchant with zero June settlements should show `0`; instead it disappears from the report.

The docs frame the underlying asymmetry precisely: "The `ON` or `USING` clause of an outer join is *not* equivalent to a `WHERE` condition, because it results in the addition of rows (for unmatched input rows) as well as the removal of rows in the final result."

**The rule:** on an outer join, a predicate on the **inner (nullable) side** belongs in `ON`. A predicate on the **preserved side** belongs in `WHERE`. The deliberate exception is the anti-join idiom, where discarding the padded rows is exactly the point:

```sql
-- Anti-join: merchants with NO settlements at all
SELECT m.*
FROM merchants m
LEFT JOIN settlements s ON s.merchant_id = m.merchant_id
WHERE s.merchant_id IS NULL;   -- keep ONLY the padded rows
```

### Gotcha 2 — join fan-out: the double-counting bug

The most damaging join bug in production, because it produces a plausible wrong number instead of an error.

A join is *not* a lookup. If a merchant has 80 transactions and 12 settlements, joining all three tables produces 80 × 12 = 960 rows for that merchant. Every transaction amount is now repeated 12 times.

```sql
-- WRONG: txn_total is inflated by the number of settlement rows
SELECT m.name, SUM(t.amount) AS txn_total, SUM(s.amount) AS settled_total
FROM merchants m
JOIN transactions t ON t.merchant_id = m.merchant_id
JOIN settlements  s ON s.merchant_id = m.merchant_id
GROUP BY m.name;
```

Both sums are wrong, each inflated by the other side's row count. Nothing errors. The report is simply false.

**Fix — aggregate each branch to one row per key *before* joining:**

```sql
SELECT m.name, t.txn_total, s.settled_total
FROM merchants m
LEFT JOIN (SELECT merchant_id, SUM(amount) AS txn_total
           FROM transactions GROUP BY merchant_id) t USING (merchant_id)
LEFT JOIN (SELECT merchant_id, SUM(amount) AS settled_total
           FROM settlements  GROUP BY merchant_id) s USING (merchant_id);
```

Each subquery is now **one row per `merchant_id`**, so neither can fan the other out.

**The detection heuristic:** whenever a query joins two or more independent one-to-many branches off a shared parent *and* aggregates, suspect fan-out. Confirm by running `COUNT(*)` before and after adding a join — if the count grows, every pre-existing `SUM` in that query is now wrong.

### `LATERAL` — the per-row correlated join

A normal subquery in `FROM` is evaluated independently and cannot see its siblings. `LATERAL` removes that restriction: "Subqueries appearing in `FROM` can be preceded by the key word `LATERAL`. This allows them to reference columns provided by preceding `FROM` items."

Evaluation is a loop: "for each row of the `FROM` item providing the cross-referenced column(s) ... the `LATERAL` item is evaluated using that row or row set's values of the columns. The resulting row(s) are joined as usual with the rows they were computed from."

This is the clean answer to **top-N-per-group**:

```sql
-- The 3 most recent transactions for each merchant
SELECT m.name, t.txn_id, t.amount, t.created_at
FROM merchants m
LEFT JOIN LATERAL (
    SELECT txn_id, amount, created_at
    FROM transactions
    WHERE merchant_id = m.merchant_id     -- <-- only legal because of LATERAL
    ORDER BY created_at DESC
    LIMIT 3
) t ON TRUE;
```

Use `LEFT JOIN LATERAL ... ON TRUE` rather than `CROSS JOIN LATERAL` when merchants with zero transactions must still appear. With a composite index on `(merchant_id, created_at DESC)` this becomes an index scan per merchant — see [[composite-indexes]].

---

## Part 2 — Aggregation

### Why: collapsing many rows into one fact

`GROUP BY` is the only clause that changes the **grain** of the result. Before it, one output row means one source row. After it, one output row means one *set* of source rows. Everything confusing about aggregation follows from that change of grain.

> "The `GROUP BY` clause is used to group together those rows in a table that have the same values in all the columns listed... The effect is to combine each set of rows having common values into one group row that represents all rows in the group."

Once the grain has changed, a column that was not grouped no longer has a single value — it has a *set* of values. So the rule is forced, not arbitrary:

> "In general, if a table is grouped, columns that are not listed in `GROUP BY` cannot be referenced except in aggregate expressions."

An aggregate function is precisely a **set → one value** reduction. That is the only legal way to talk about an ungrouped column.

### `WHERE` vs `HAVING`

Straight from evaluation order: **`WHERE` filters rows before grouping. `HAVING` filters groups after.**

```sql
-- Merchants with more than 50 SUCCESS transactions averaging over 500
SELECT merchant_id, COUNT(*) AS n, AVG(amount) AS avg_amt
FROM transactions
WHERE status = 'SUCCESS'          -- row filter: runs FIRST, shrinks the input
GROUP BY merchant_id
HAVING COUNT(*) > 50              -- group filter: needs the group to exist
   AND AVG(amount) > 500;
```

`status = 'SUCCESS'` **must** be in `WHERE`: it is a property of one row, and putting it in `HAVING` would be illegal (it is neither grouped nor aggregated). `COUNT(*) > 50` **must** be in `HAVING`: no single row has a count.

Two supporting rules from the docs. `HAVING` is more permissive than `WHERE` about what it can see: "Expressions in the `HAVING` clause can refer both to grouped expressions and to ungrouped expressions (which necessarily involve an aggregate function)." And aggregation happens even with no `GROUP BY` at all: "If a query contains aggregate function calls, but no `GROUP BY` clause, grouping still occurs: the result is a single group row."

**The performance corollary:** a predicate that could live in either belongs in `WHERE`. `WHERE` runs first and shrinks the input to the grouping step.

### NULL semantics — where wrong numbers come from

Aggregates **skip NULLs**. This is not a footnote; it silently changes results.

```sql
COUNT(*)              -- counts ROWS.        NULLs included.
COUNT(customer_id)    -- counts NON-NULL values of that column.
COUNT(DISTINCT ...)   -- counts distinct non-null values.
```

In the practice schema `transactions.customer_id` is nullable, so `COUNT(*)` and `COUNT(customer_id)` return **different numbers** on the same table. That gap is the anonymous-transaction count.

`AVG` is the dangerous one:

```sql
-- values: 10, 20, NULL, NULL
AVG(x)                    -- = 15   (sum 30 / count 2)  -- NULLs excluded from BOTH
AVG(COALESCE(x, 0))       -- = 7.5  (sum 30 / count 4)  -- NULLs treated as zero
```

Neither is wrong in general. They answer different questions: *"average of the values we have"* versus *"average across everyone, absent counting as zero"*. Choosing without noticing is the bug. `SUM` over an all-NULL set (or zero rows) returns `NULL`, not `0` — which is why `COALESCE(SUM(...), 0)` appears in every one of the report queries above.

`GROUP BY` itself treats NULL as **one group**: all NULL values land together, even though `NULL = NULL` is `NULL`. Grouping uses *not distinct from* semantics, not equality. That inconsistency is deliberate and worth holding onto.

### Conditional aggregation — pivoting without a pivot

The idiom that turns rows into columns, and the highest-value aggregation pattern for real reporting work:

```sql
SELECT merchant_id,
       COUNT(*)                                    AS total,
       COUNT(*) FILTER (WHERE status = 'SUCCESS')  AS succeeded,
       COUNT(*) FILTER (WHERE status = 'FAILED')   AS failed,
       SUM(amount) FILTER (WHERE method = 'UPI')   AS upi_volume,
       ROUND(100.0 * COUNT(*) FILTER (WHERE status = 'SUCCESS')
                   / NULLIF(COUNT(*), 0), 2)       AS success_pct
FROM transactions
GROUP BY merchant_id;
```

`FILTER` is the SQL-standard form and reads better than the portable alternative, `SUM(CASE WHEN status = 'SUCCESS' THEN 1 ELSE 0 END)`. Both work; `FILTER` is Postgres-native.

`NULLIF(COUNT(*), 0)` is the **division-by-zero guard**. It converts a `0` denominator to `NULL`, and `x / NULL` is `NULL` rather than an error. Any percentage computed in SQL should carry it.

### `GROUPING SETS`, `ROLLUP`, `CUBE`

Multiple grouping levels in a single pass over the data — subtotals without a self-union.

```sql
SELECT city, category, SUM(amount)
FROM transactions JOIN merchants USING (merchant_id)
GROUP BY ROLLUP (city, category);
```

`ROLLUP (a, b)` "represents the given list of expressions and all prefixes of the list including the empty list" — so `(a,b)`, `(a)`, and `()`. That yields per-city-per-category rows, a per-city subtotal, and one grand total. `CUBE (a, b)` gives the full power set: every combination. The empty grouping set "means that all rows are aggregated down to a single group (which is output even if no input rows were present)."

The subtotal rows carry `NULL` in the rolled-up columns. Use the `GROUPING()` function to tell a genuine data NULL from a subtotal marker.

---

## Part 3 — Subqueries

Four distinct kinds, distinguished by **where they sit** and **whether they can see the outer row**.

### Scalar subquery — exactly one row, one column

```sql
SELECT name, amount,
       amount - (SELECT AVG(amount) FROM transactions) AS vs_avg
FROM transactions JOIN merchants USING (merchant_id);
```

Uncorrelated, so it runs **once** and the result is reused. If it returns more than one row at runtime, the query errors — this is a runtime failure, not a parse-time one.

### `IN` / `ANY` / `ALL` — set membership

`IN` is equivalent to `= ANY`. `NOT IN` is equivalent to `<> ALL`. `SOME` is a synonym for `ANY`.

### `EXISTS` — does at least one row exist?

> "The subquery is evaluated to determine whether it returns any rows. If it returns at least one row, the result of `EXISTS` is 'true'; if the subquery returns no rows, the result of `EXISTS` is 'false'."

The projected columns are irrelevant: "Since the result depends only on whether any rows are returned, and not on the contents of those rows, the output list of the subquery is normally unimportant. A common coding convention is to write all `EXISTS` tests in the form `EXISTS(SELECT 1 WHERE ...)`."

And it short-circuits: "The subquery will generally only be executed long enough to determine whether at least one row is returned, not all the way to completion."

`EXISTS` is normally **correlated** — it references the outer row, so it is conceptually re-evaluated per outer row (the planner usually turns this into a single semi-join anyway):

```sql
SELECT c.*
FROM customers c
WHERE EXISTS (SELECT 1 FROM transactions t WHERE t.customer_id = c.customer_id);
```

### Gotcha 3 — the `NOT IN` NULL trap

The subquery gotcha most likely to appear in an interview, and it fails **silently and totally**.

```sql
-- Customers who have never transacted.
-- Returns ZERO ROWS if transactions.customer_id contains even one NULL.
SELECT * FROM customers
WHERE customer_id NOT IN (SELECT customer_id FROM transactions);
```

The docs state the rule exactly:

> "Note that if the left-hand expression yields null, or if there are no equal right-hand values and at least one right-hand row yields null, the result of the `NOT IN` construct will be null, not true."

Trace it through three-valued logic. `NOT IN` is `<> ALL`. To return **true**, `customer_id <> NULL` must be true — but it evaluates to `NULL` (unknown). `NULL AND anything` is never true. So no customer ever qualifies, and the query returns an empty set rather than an error. The result looks like a legitimate finding: "no such customers exist."

Three correct rewrites:

```sql
-- 1. NOT EXISTS: correct under NULLs, and usually the best plan (anti-join)
SELECT * FROM customers c
WHERE NOT EXISTS (SELECT 1 FROM transactions t WHERE t.customer_id = c.customer_id);

-- 2. LEFT JOIN ... IS NULL: the same anti-join, spelled as a join
SELECT c.* FROM customers c
LEFT JOIN transactions t ON t.customer_id = c.customer_id
WHERE t.customer_id IS NULL;

-- 3. NOT IN with the NULLs removed explicitly
SELECT * FROM customers
WHERE customer_id NOT IN (
    SELECT customer_id FROM transactions WHERE customer_id IS NOT NULL);
```

**Why `NOT EXISTS` is safe:** it asks "did any row come back?" — a question with only two answers. There is no third value for NULL to leak into.

**Practical rule: prefer `EXISTS`/`NOT EXISTS` over `IN`/`NOT IN` for subqueries.** `IN` is fine over a literal list, where NULLs cannot appear.

### `IN` vs `EXISTS` on performance

Largely a myth in modern Postgres. Both usually compile to the same **semi-join**, and `NOT EXISTS` / `LEFT JOIN ... IS NULL` both compile to an **anti-join**. Choose on *correctness under NULLs* and readability, then confirm with `EXPLAIN` — which is the next topic in this week's sequence.

The one asymmetry worth knowing: `NOT IN` **cannot** be planned as a clean anti-join precisely because of the NULL semantics above. The planner must preserve the three-valued behaviour, so it often falls back to a materialized subplan. Here the correct query really is also the faster one.

---

## Part 4 — Common Table Expressions (CTEs)

### Why: naming an intermediate result

A CTE is a **named subquery**, defined before the query that uses it. Three things it buys:

1. **Readability** — a nested pyramid of subqueries becomes a top-to-bottom pipeline.
2. **Reuse** — one definition referenced several times.
3. **Recursion** — the only way to walk a hierarchy in standard SQL.

```sql
WITH monthly AS (
    SELECT merchant_id,
           date_trunc('month', created_at) AS month,
           SUM(amount) AS volume
    FROM transactions
    WHERE status = 'SUCCESS'
    GROUP BY 1, 2
),
ranked AS (
    SELECT *, RANK() OVER (PARTITION BY month ORDER BY volume DESC) AS rk
    FROM monthly
)
SELECT month, merchant_id, volume
FROM ranked
WHERE rk <= 3
ORDER BY month, rk;
```

Read top to bottom, each step named. The same logic as nested subqueries, but the nesting is gone.

### Gotcha 4 — the optimization fence (and the Postgres 12 change)

**This is version-dependent, and the pre-12 behaviour is still widely repeated as fact.**

Before Postgres 12, a CTE was an **unconditional optimization fence**: always materialized into a temporary result first, never merged into the outer query. Predicates could not be pushed down into it, so `WITH w AS (SELECT * FROM big_table) SELECT * FROM w WHERE key = 123` scanned the entire table, then filtered.

Postgres 12 (2019-10-03) changed it. From the release notes:

> "Allow common table expressions (CTEs) to be inlined into the outer query ... Specifically, CTEs are automatically inlined if they have no side-effects, are not recursive, and are referenced only once in the query. Inlining can be prevented by specifying `MATERIALIZED`, or forced for multiply-referenced CTEs by specifying `NOT MATERIALIZED`. Previously, CTEs were never inlined and were always evaluated before the rest of the query."

The current default rule: "By default, this happens if the parent query references the `WITH` query just once, but not if it references the `WITH` query more than once."

So, on Postgres 12+:

```sql
-- Referenced once -> inlined. Same plan as the plain query. Index on key IS used.
WITH w AS (SELECT * FROM big_table)
SELECT * FROM w WHERE key = 123;

-- Referenced twice -> materialized by default. Temp copy, no index benefit.
-- NOT MATERIALIZED lets the restriction push down to the table scan.
WITH w AS NOT MATERIALIZED (SELECT * FROM big_table)
SELECT * FROM w AS w1 JOIN w AS w2 ON w1.key = w2.ref WHERE w2.key = 123;
```

`MATERIALIZED` remains useful in the opposite direction — to guarantee an expensive expression is computed **once per row** rather than re-evaluated at each of several reference sites:

```sql
WITH w AS MATERIALIZED (
    SELECT key, very_expensive_function(val) AS f FROM some_table
)
SELECT * FROM w AS w1 JOIN w AS w2 ON w1.f = w2.f;
```

**Interview framing:** "CTEs are an optimization fence" was true before Postgres 12 and is false as a blanket claim today. The precise statement is: *inlined when non-recursive, side-effect-free, and referenced exactly once; otherwise materialized; and both are overridable.*

### Recursive CTEs

The only standard-SQL tool for walking a hierarchy of unknown depth — org charts, category trees, bill-of-materials, graph reachability.

```sql
WITH RECURSIVE chain AS (
    -- non-recursive (anchor) term: where the walk starts
    SELECT emp_id, name, manager_id, 1 AS depth
    FROM employees
    WHERE manager_id IS NULL

    UNION ALL

    -- recursive term: references the CTE by name
    SELECT e.emp_id, e.name, e.manager_id, c.depth + 1
    FROM employees e
    JOIN chain c ON e.manager_id = c.emp_id
)
SELECT * FROM chain ORDER BY depth, emp_id;
```

**The evaluation algorithm is iterative, not recursive** — and knowing it is what makes these queries writable rather than magic. Postgres documents it precisely:

1. Evaluate the non-recursive term. For `UNION` (not `UNION ALL`), discard duplicates. Emit those rows, and place them in a temporary **working table**.
2. While the working table is not empty:
   - a. Evaluate the recursive term, **substituting the current working table for the self-reference**. For `UNION`, discard rows duplicating any previous result row. Emit the remainder, and place it in an **intermediate table**.
   - b. Replace the working table with the intermediate table, and empty the intermediate table.

> "While `RECURSIVE` allows queries to be specified recursively, internally such queries are evaluated iteratively."

Two consequences fall straight out of that algorithm:

- **The self-reference sees only the *previous* iteration**, never the full accumulated result. This is why aggregates and `LEFT JOIN` against the recursive term are restricted.
- **Termination is your job.** The loop stops only when an iteration adds no rows. `UNION` deduplicates and so terminates on cyclic graphs; `UNION ALL` does not and will spin forever. For a graph with cycles, carry a path array and stop on revisit:

```sql
WITH RECURSIVE walk AS (
    SELECT id, link, ARRAY[id] AS path, false AS is_cycle
    FROM graph WHERE id = 1
  UNION ALL
    SELECT g.id, g.link, w.path || g.id, g.id = ANY(w.path)
    FROM graph g JOIN walk w ON g.id = w.link
    WHERE NOT w.is_cycle
)
SELECT * FROM walk;
```

Postgres 14+ also offers built-in `SEARCH DEPTH FIRST BY ... SET col` / `SEARCH BREADTH FIRST BY ...` and `CYCLE col SET ... USING path` clauses that generate exactly this bookkeeping.

**Safety net while developing:** `LIMIT` on the outer query genuinely stops the recursion, because "PostgreSQL's implementation evaluates only as many rows of a `WITH` query as are actually fetched by the parent query."

### Data-modifying CTEs

`WITH` can contain `INSERT`, `UPDATE`, `DELETE` and `MERGE`, each with `RETURNING`. This is already familiar from the job-queue pattern in [[select-for-update-skip-locked]].

```sql
-- Archive-and-delete, atomically, in one statement
WITH moved AS (
    DELETE FROM transactions
    WHERE created_at < DATE '2025-02-01'
    RETURNING *
)
INSERT INTO transactions_archive SELECT * FROM moved;
```

Three rules matter, and all three are counter-intuitive:

1. **`RETURNING` is the visible output, not the table.** "It is the output of the `RETURNING` clause, *not* the target table of the data-modifying statement, that forms the temporary table that can be referred to by the rest of the query."
2. **They always run, completely.** "Data-modifying statements in `WITH` are executed exactly once, and always to completion, independently of whether the primary query reads all (or indeed any) of their output." A data-modifying CTE the outer query never references still executes.
3. **They all share one snapshot and cannot see each other.** "The sub-statements in `WITH` are executed concurrently with each other and with the main query. Therefore ... the order in which the specified updates actually happen is unpredictable. All the statements are executed with the same *snapshot*, so they cannot 'see' one another's effects on the target tables."

Rule 3 is a direct consequence of [[mvcc]] — one statement, one snapshot — and it produces this genuinely surprising pair:

```sql
WITH t AS (UPDATE products SET price = price * 1.05 RETURNING *)
SELECT * FROM products;   -- ORIGINAL prices: same snapshot, can't see the UPDATE

WITH t AS (UPDATE products SET price = price * 1.05 RETURNING *)
SELECT * FROM t;          -- UPDATED prices: reads the RETURNING output
```

Also: "Trying to update the same row twice in a single statement is not supported. Only one of the modifications takes place, but it is not easy (and sometimes not possible) to reliably predict which one." And recursive self-references in data-modifying statements are not allowed.

---

## Where this lands in backend work

| Pattern | Where it shows up |
|---|---|
| `ON` vs `WHERE` on outer joins | Any "include the zeroes" report — merchants with no sales, users with no orders |
| Join fan-out | Dashboard totals that are silently k× too large |
| `NOT EXISTS` over `NOT IN` | Anti-joins: churn lists, unmatched records, reconciliation |
| `COUNT(*) FILTER` | Success-rate and funnel metrics in one pass |
| Pre-aggregate then join | The standard fix when a report both joins and sums |
| `LATERAL` | Top-N-per-group: latest N events per entity |
| Recursive CTE | Org charts, threaded comments, category trees, permission inheritance |
| Data-modifying CTE | Atomic archive-and-delete; the `SKIP LOCKED` job-queue claim |

The connecting idea: **SQL is where the work happens or does not.** A query that pulls 10,000 rows into the application to filter them in a loop has moved the join out of the engine — away from the indexes, the buffer pool, and the planner's statistics — and into a language with none of them. That is the N+1 problem, which is the next topic in this sequence.

---

## Sources

- [PostgreSQL Documentation — 7.2. Table Expressions](https://www.postgresql.org/docs/current/queries-table-expressions.html) — fetched 2026-08-24
- [PostgreSQL Documentation — 7.8. WITH Queries (CTEs)](https://www.postgresql.org/docs/current/queries-with.html) — fetched 2026-08-24
- [PostgreSQL Documentation — 9.23. Subquery Expressions](https://www.postgresql.org/docs/current/functions-subquery.html) — fetched 2026-08-24
- [PostgreSQL Documentation — SELECT](https://www.postgresql.org/docs/current/sql-select.html) — fetched 2026-08-24
- [PostgreSQL 12 Release Notes](https://www.postgresql.org/docs/release/12.0/) — fetched 2026-08-24

---

## Clarifications

### The `NOT IN` NULL trap — full three-valued trace

Added after recall showed the outcome was memorable but the mechanism was not. The trace below is the part worth being able to reproduce on a whiteboard.

`NOT IN` is not a primitive. Postgres defines it as `<> ALL`. For a subquery returning `{7, 12, NULL}`:

```
c.customer_id <> 7  AND  c.customer_id <> 12  AND  c.customer_id <> NULL
```

Any comparison against NULL yields **UNKNOWN** — not false. Run two customers through it:

```
-- Customer 99, never transacted: the row we WANT returned
99 <> 7     -> TRUE
99 <> 12    -> TRUE
99 <> NULL  -> UNKNOWN
TRUE AND TRUE AND UNKNOWN  ->  UNKNOWN      -- dropped

-- Customer 7, did transact: the row we want dropped
7 <> 7      -> FALSE
FALSE AND ...              ->  FALSE        -- dropped
```

`WHERE` keeps a row only when the predicate is TRUE. Every row is FALSE or UNKNOWN, so **no row is ever TRUE** and the result set is empty.

The asymmetry lives in the `AND` truth table:

```
FALSE AND UNKNOWN  =  FALSE     <- the matching case still resolves
TRUE  AND UNKNOWN  =  UNKNOWN   <- the non-matching case cannot
```

One NULL poisons exactly the branch that matters. And it does not raise — it returns an empty set that reads as a legitimate finding.

**Why `NOT EXISTS` is structurally immune.** `EXISTS` performs no value comparison. It asks a **cardinality** question: did the subquery return at least one row? The test is `count >= 1`, which has exactly two outcomes. UNKNOWN has nowhere to enter. It is two-valued by construction, not by luck. A `customer_id IS NULL` row inside the subquery fails the `=` test, contributes no row, and correctly does not count as evidence.

**Why plain `IN` is mostly safe.** `IN` is `= ANY`, a chain of `OR`, and `OR` has the mirror asymmetry:

```
TRUE  OR UNKNOWN  =  TRUE      <- a real match short-circuits past the NULL
FALSE OR UNKNOWN  =  UNKNOWN
```

`x IN (7, NULL)` with `x = 7` returns TRUE, correctly. `IN` only degrades to UNKNOWN when there was no match — and `WHERE` discards UNKNOWN and FALSE alike, so the behaviour is indistinguishable from correct.

**The rule underneath: NULL damage only surfaces under negation.** Same NULLs, opposite outcome.

### `IS NOT NULL` in `WHERE` is not a fix for the outer-join trap

A related confusion. On the nullable side of a `LEFT JOIN`:

```sql
WHERE s.merchant_id IS NULL      -- anti-join: keeps ONLY the padded rows
WHERE s.merchant_id IS NOT NULL  -- degrades the join to INNER. Never useful.
```

Every padded row fails `IS NOT NULL` by construction, so that predicate discards exactly the rows the `LEFT` was there to preserve. `IS NULL` / `IS NOT NULL` are the only tests that behave sanely against NULL, because they are two-valued by definition — but only the `IS NULL` direction does useful work here.

### Two rules the recall pass surfaced

- **Fan-out diagnostic:** run `COUNT(*)` before and after adding a join. If the count grows, every `SUM` already in the query is now wrong. General form: *join-then-aggregate is unsafe across two one-to-many branches; aggregate-then-join is safe.*
- **Why `AVG` hides its NULL bug better than `COUNT`:** `COUNT` shows two numbers side by side and the discrepancy is visible. `AVG` returns one number, and it is always plausible.
