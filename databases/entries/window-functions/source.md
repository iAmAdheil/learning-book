---
slug: window-functions
title: Window Functions — RANK, ROW_NUMBER, LAG/LEAD, Partitions & Frames
topic: databases
bloom-level: some
created: 2026-08-24
updated: 2026-08-31
published: null
related: [sql-fundamentals, relational-data-model, btree-indexes, composite-indexes, denormalization, heap-storage-layout, join-algorithms, query-planning]
tags: [sql, window-function, over-clause, partition-by, order-by, frame-clause, rows-vs-range, groups-mode, default-frame, peer-group, unbounded-preceding, current-row, unbounded-following, exclude-current-row, row-number, rank, dense-rank, percent-rank, cume-dist, ntile, lag, lead, first-value, last-value, nth-value, running-total, moving-average, top-n-per-group, gaps-and-islands, sessionization, deduplication, named-window, distinct-on, percentile-cont, percentile-disc, logical-evaluation-order, qualify, interview-priority]
sources:
  - title: "PostgreSQL Documentation — 3.5. Window Functions (tutorial)"
    url: "https://www.postgresql.org/docs/current/tutorial-window.html"
  - title: "PostgreSQL Documentation — 4.2.8. Window Function Calls (frame clause syntax)"
    url: "https://www.postgresql.org/docs/current/sql-expressions.html#SYNTAX-WINDOW-FUNCTIONS"
  - title: "PostgreSQL Documentation — 9.22. Window Functions (function reference)"
    url: "https://www.postgresql.org/docs/current/functions-window.html"
  - title: "PostgreSQL Documentation — SELECT (logical processing order, WINDOW clause)"
    url: "https://www.postgresql.org/docs/current/sql-select.html"
---

## Answer

A window function computes an aggregate **without collapsing the rows it aggregated over**.

That single sentence is the entire concept, and Postgres states it precisely:

> "A *window function* performs a calculation across a set of table rows that are somehow related to the current row. This is comparable to the type of calculation that can be done with an aggregate function. However, window functions do not cause rows to become grouped into a single output row like non-window aggregate calls would. Instead, **the rows retain their separate identities**."

### Why this needed to be invented

[[sql-fundamentals]] established that `GROUP BY` is the only clause that changes the **grain** of a result. Before it, one output row means one source row. After it, one output row means one *set* of source rows. That change is destructive: the individual rows are gone, and there is no way to write "this transaction, and also the merchant's total" in a grouped query, because those two facts live at different grains.

The pre-window workaround was to compute the aggregate separately and join it back:

```sql
-- The old way: aggregate in a subquery, join back to recover the rows
SELECT t.txn_id, t.amount, m.merchant_total
FROM transactions t
JOIN (SELECT merchant_id, SUM(amount) AS merchant_total
      FROM transactions GROUP BY merchant_id) m USING (merchant_id);
```

That works, and it costs a second pass over the table plus a join. A window function expresses the same thing in one pass and one clause:

```sql
SELECT txn_id, amount,
       SUM(amount) OVER (PARTITION BY merchant_id) AS merchant_total
FROM transactions;
```

**The mental model:** for each row, the engine looks out of a *window* at a set of related rows, computes something over them, and writes the answer onto that row. The row survives. Nothing is collapsed.

| | `GROUP BY` aggregate | Window function |
|---|---|---|
| Output rows | one per group | one per input row |
| Grain | changed | **unchanged** |
| Can you still see the row's own columns? | only if grouped | always |
| Runs at evaluation step | 4 | after 4, before `DISTINCT`/`ORDER BY` |

---

## Gotcha 1 — you cannot filter on a window function

The first wall everyone hits, and it follows directly from the evaluation order in [[sql-fundamentals]].

> "Window functions are permitted only in the `SELECT` list and the `ORDER BY` clause of the query. They are forbidden elsewhere, such as in `GROUP BY`, `HAVING` and `WHERE` clauses."

The reason is not arbitrary:

> "This is because they logically execute **after** the processing of those clauses. Also, window functions execute after non-window aggregate functions."

So window functions slot into the evaluation order like this:

```
3. WHERE          -> filter rows
4. GROUP BY       -> collapse into groups
   HAVING         -> filter groups
4.5 WINDOW FUNCTIONS   <-- here. The row set is already final.
5. SELECT         -> output expressions
6. DISTINCT   7. UNION   8. ORDER BY   9. LIMIT
```

By the time a window function runs, `WHERE` has finished. There is no way for `WHERE` to see a value that does not exist yet.

```sql
-- ERROR:  window functions are not allowed in WHERE
SELECT merchant_id, txn_id,
       ROW_NUMBER() OVER (PARTITION BY merchant_id ORDER BY amount DESC) AS rn
FROM transactions
WHERE rn <= 3;
```

**The fix is structural, not stylistic: wrap it and filter outside.** The subquery or CTE ends one query's evaluation, so the window result becomes an ordinary column of the next one.

```sql
WITH ranked AS (
    SELECT merchant_id, txn_id, amount,
           ROW_NUMBER() OVER (PARTITION BY merchant_id ORDER BY amount DESC) AS rn
    FROM transactions
)
SELECT * FROM ranked WHERE rn <= 3;
```

This is why almost every real window query is two levels deep. It is a consequence of the evaluation order, not a sign that the query is over-engineered. (Some databases offer a `QUALIFY` clause that filters on window results directly. Postgres does not — the CTE wrapper is the Postgres idiom.)

**One exception is worth knowing:** `ORDER BY` *is* allowed to reference a window function, because it runs at step 8, after them.

```sql
SELECT merchant_id, amount,
       RANK() OVER (PARTITION BY merchant_id ORDER BY amount DESC) AS rk
FROM transactions
ORDER BY RANK() OVER (PARTITION BY merchant_id ORDER BY amount DESC);
```

---

## The `OVER` clause: three independent questions

Every window is defined by answering three things. Each is optional, and each does exactly one job.

```sql
func() OVER (
    PARTITION BY merchant_id      -- 1. WHICH rows are related to me?
    ORDER BY created_at            -- 2. In what ORDER do I see them?
    ROWS BETWEEN 6 PRECEDING AND CURRENT ROW   -- 3. WHICH SLICE of them counts?
)
```

**1. `PARTITION BY` — the grouping that does not group.**

> "The `PARTITION BY` clause within `OVER` divides the rows into groups, or partitions, that share the same values of the `PARTITION BY` expression(s). For each row, the window function is computed across the rows that fall into the same partition as the current row."

Omit it and the whole result set is one partition. It is `GROUP BY`'s selector without `GROUP BY`'s collapse.

**2. `ORDER BY` inside `OVER` — sequence, not output order.**

> "You can also control the order in which rows are processed by window functions using `ORDER BY` within `OVER`. (The window `ORDER BY` does not even have to match the order in which the rows are output.)"

This is a distinct clause from the query's final `ORDER BY`, and confusing them is common. The window's `ORDER BY` decides *what "before me" means* for ranking, `LAG`, and running totals. The query's `ORDER BY` decides how the result is printed. A query can have both, with different keys.

**3. The frame — which slice of the ordered partition.** Covered in depth below. It is the part that is usually left implicit and is the source of the subtlest bugs.

### Naming a window

When several functions share a window, define it once:

```sql
SELECT merchant_id, amount,
       SUM(amount) OVER w  AS running_total,
       AVG(amount) OVER w  AS running_avg,
       RANK()      OVER w  AS rk
FROM transactions
WINDOW w AS (PARTITION BY merchant_id ORDER BY created_at);
```

The `WINDOW` clause sits between `HAVING` and `ORDER BY`. Beyond removing repetition, it guarantees the three functions really do share one window — copy-pasted `OVER (...)` clauses drift.

---

## Part 1 — Ranking functions

### `ROW_NUMBER` vs `RANK` vs `DENSE_RANK`

The three differ **only in how they treat ties**, and picking the wrong one is the classic off-by-one-in-disguise bug.

| Function | Definition (docs) | Ties | Gaps after a tie |
|---|---|---|---|
| `row_number()` | "the number of the current row within its partition, counting from 1" | broken arbitrarily | n/a |
| `rank()` | "the rank of the current row, with gaps; that is, the `row_number` of the first row in its peer group" | share a rank | **yes** |
| `dense_rank()` | "the rank of the current row, without gaps; this function effectively counts peer groups" | share a rank | no |

On salaries `100, 90, 90, 80`:

```
salary   row_number   rank   dense_rank
  100        1          1         1
   90        2          2         2
   90        3          2         2
   80        4          4         3
             ^          ^         ^
        arbitrary    skips 3   counts groups
```

**Choosing between them is a question about the business, not the syntax:**

- **"Give me exactly 3 rows per merchant"** → `ROW_NUMBER`. It is the only one that guarantees a count, because it never repeats a value.
- **"Give me the top 3 salaries, and if two people tie for 3rd, include both"** → `RANK`. Row count becomes variable.
- **"Give me the 3rd-highest *distinct* salary"** → `DENSE_RANK`. This is the one that collapses ties into one rank level, so "3rd distinct value" and "rank 3" mean the same thing.

That last case is exactly practice question 1 in [[10 - SQL Practice Set (Postgres)]], and the whole question turns on picking `DENSE_RANK` over the other two.

**A `ROW_NUMBER` warning:** with no tiebreaker in the window `ORDER BY`, ties are broken *arbitrarily* and the choice is **not stable across runs**. If the result must be reproducible, order by enough columns to be deterministic:

```sql
ROW_NUMBER() OVER (PARTITION BY merchant_id ORDER BY amount DESC, txn_id)
--                                                                ^^^^^^ tiebreaker
```

### Top-N-per-group — the canonical pattern

```sql
WITH ranked AS (
    SELECT merchant_id, txn_id, amount,
           ROW_NUMBER() OVER (PARTITION BY merchant_id
                              ORDER BY amount DESC, txn_id) AS rn
    FROM transactions
    WHERE status = 'SUCCESS'          -- filter FIRST: step 3 beats step 4.5
)
SELECT * FROM ranked WHERE rn <= 3;
```

Note the `WHERE` placement. Filtering inside the CTE shrinks the input *before* ranking, and it also changes the meaning — ranks are computed among successful transactions only. Moving it outside would rank everything and then discard, which is both slower and a different question.

**The alternatives, and when each wins:**

- **`LATERAL`** (see [[sql-fundamentals]]) — usually faster for small N over many groups, because with a composite index on `(merchant_id, amount DESC)` it does an index scan per group instead of sorting the whole table. See [[composite-indexes]].
- **`DISTINCT ON`** — Postgres-specific, unbeatable for N = 1:

  ```sql
  SELECT DISTINCT ON (merchant_id) merchant_id, txn_id, amount
  FROM transactions ORDER BY merchant_id, amount DESC;
  ```

  Terse and fast, but it does not generalise past N = 1 and it does not port to other databases. `ROW_NUMBER` is the portable answer.

### `NTILE`, `PERCENT_RANK`, `CUME_DIST`

- `ntile(n)` — "Returns an integer ranging from 1 to the argument value, dividing the partition as equally as possible." Quartiles, deciles, cohort bucketing.
- `percent_rank()` — `(rank - 1) / (total partition rows - 1)`, ranging 0 to 1 inclusive.
- `cume_dist()` — "(number of partition rows preceding or peers with current row) / (total partition rows)", ranging `1/N` to 1.

All four ranking functions plus `cume_dist` **ignore the frame entirely**: "The four ranking functions (including `cume_dist`) are defined so that they give the same answer for all rows of a peer group." Adding a frame clause to a `RANK()` call changes nothing.

---

## Part 2 — `LAG` and `LEAD`: reaching across rows

```
lag (value [, offset [, default ]])   -- offset rows BEFORE the current row
lead(value [, offset [, default ]])   -- offset rows AFTER  the current row
```

> "Returns *value* evaluated at the row that is *offset* rows before the current row within the partition; if there is no such row, instead returns *default* ... If omitted, *offset* defaults to 1 and *default* to `NULL`."

These solve the problem SQL is otherwise worst at: **comparing a row to its neighbour.** Without them you need a self-join on a computed sequence number, which is verbose and slow.

### Row-to-row deltas

```sql
SELECT customer_id, login_at,
       LAG(login_at) OVER (PARTITION BY customer_id ORDER BY login_at) AS prev_login,
       login_at - LAG(login_at) OVER (PARTITION BY customer_id ORDER BY login_at) AS gap
FROM logins;
```

The first row of each partition has no predecessor, so `gap` is `NULL` there. That is correct, not a bug — but it means downstream arithmetic needs `COALESCE`, and a `WHERE gap > interval '30 min'` will silently drop every first row. Supply the third argument when a sentinel is better than `NULL`.

### Sessionization — the flag-then-running-sum idiom

The highest-value `LAG` pattern, and the one worth memorising whole. Group events into sessions separated by an idle gap:

```sql
WITH gaps AS (
    SELECT customer_id, login_at,
           CASE WHEN login_at - LAG(login_at) OVER w > INTERVAL '30 minutes'
                  OR LAG(login_at) OVER w IS NULL
                THEN 1 ELSE 0 END AS is_new_session
    FROM logins
    WINDOW w AS (PARTITION BY customer_id ORDER BY login_at)
),
sessions AS (
    SELECT *,
           SUM(is_new_session) OVER (PARTITION BY customer_id ORDER BY login_at)
             AS session_id
    FROM gaps
)
SELECT customer_id, session_id, MIN(login_at), MAX(login_at), COUNT(*)
FROM sessions GROUP BY customer_id, session_id;
```

**The trick to understand:** a running `SUM` over a 0/1 flag is a **counter that increments only at the boundaries**. Every row between two boundaries carries the same total, so the running sum *is* the session id. Two window passes, then a normal `GROUP BY`. This is practice question 5.

### Gaps and islands

The same trick in a different disguise, and a genuine interview favourite. Find runs of consecutive days:

```sql
SELECT customer_id, login_date,
       login_date - (ROW_NUMBER() OVER (PARTITION BY customer_id
                                        ORDER BY login_date))::int AS grp
FROM distinct_logins;
```

For **consecutive** dates, the date and the row number both increase by exactly 1, so their difference is **constant** within a run and changes at every break. Group by that constant and you have the islands. Add `HAVING COUNT(*) >= 3` for "3+ consecutive days" — practice question 4.

Both idioms share one shape: **turn a sequential condition into a constant, then group by the constant.** That is the reusable insight, not the specific expressions.

---

## Part 3 — Frames: the subtlest part

The frame answers "which slice of the ordered partition does this row's calculation see?" Most queries never write one, which makes the **default** the highest-leverage thing on this page.

```
{ RANGE | ROWS | GROUPS } BETWEEN frame_start AND frame_end [ frame_exclusion ]

frame_start / frame_end:
    UNBOUNDED PRECEDING | offset PRECEDING | CURRENT ROW
                        | offset FOLLOWING | UNBOUNDED FOLLOWING
```

### The three modes

- **`ROWS`** — counts physical rows. "the frame starts or ends the specified number of rows before or after the current row." Simple and literal.
- **`RANGE`** — counts by **value**. "In `RANGE` mode, these options require that the `ORDER BY` clause specify exactly one column. The *offset* specifies the maximum difference between the value of that column in the current row and its value in preceding or following rows of the frame." For dates the offset is an `interval`, so `RANGE BETWEEN '1 day' PRECEDING AND '10 days' FOLLOWING` is legal and means what it says.
- **`GROUPS`** — counts **peer groups**: "the frame starts or ends the specified number of *peer groups* before or after the current row's peer group, where a peer group is a set of rows that are equivalent in the `ORDER BY` ordering."

**A *peer* is the load-bearing word here.** Peers are rows the window's `ORDER BY` cannot distinguish — rows tied on the ordering key. That definition drives both gotchas below.

### The default frame

> "The default framing option is `RANGE UNBOUNDED PRECEDING`, which is the same as `RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW`. With `ORDER BY`, this sets the frame to be all rows from the partition start up through the current row's last `ORDER BY` peer. Without `ORDER BY`, this means all rows of the partition are included in the window frame, since all rows become peers of the current row."

Two facts to hold:

1. **No `ORDER BY` in `OVER` → the frame is the whole partition.** This is why `SUM(amount) OVER (PARTITION BY merchant_id)` gives a partition **total**, not a running total.
2. **Adding `ORDER BY` silently changes the frame** to "start through current row's last peer", which turns that same total into a **running** total. The `ORDER BY` did two jobs at once, and the second one is invisible.

That is worth stating plainly, because it surprises people:

```sql
SUM(amount) OVER (PARTITION BY merchant_id)                       -- grand total
SUM(amount) OVER (PARTITION BY merchant_id ORDER BY created_at)   -- RUNNING total
```

Nothing about `ORDER BY` announces that it also installed a frame.

### Gotcha 2 — `RANGE` + ties = a running total that stalls

The default is `RANGE`, and in `RANGE` mode:

> "a *frame_start* of `CURRENT ROW` means the frame starts with the current row's first *peer* row ... while a *frame_end* of `CURRENT ROW` means the frame ends with the current row's **last peer row**."

So under the default frame, **every tied row sees the same frame**, and therefore gets the same running total — the total *including all of its ties*.

Two transactions on the same day, ordered by day:

```
day   amount    RANGE (default)     ROWS
d1      100          100             100
d2       50          180   <-        150
d2       30          180   <-        180
d3       20          200             200
```

Both `d2` rows see `100 + 50 + 30 = 180`, because the `RANGE` frame runs through the
current row's *last peer*. The running total **stalls** across the tied rows. Under
`ROWS` it steps one row at a time: 100, 150, 180.

If the intent is "the total as of this row, row by row", that is **wrong**, and it is wrong quietly. Note that the two columns agree on the final row (200): the grand total is always right, so checking the last value never catches the bug.

**The fix is to say `ROWS` explicitly:**

```sql
SUM(amount) OVER (ORDER BY created_at ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
```

In `ROWS` mode, `CURRENT ROW` means literally the current row, peers or not.

**The rule of thumb: if the ordering key can contain duplicates and you want strict row-by-row accumulation, write `ROWS`.** `RANGE` is right when ties genuinely *should* be treated as one instant — an end-of-day balance, for instance. Both are defensible. Getting it by accident is not. This is practice question 6.

### Gotcha 3 — `LAST_VALUE` returns the current row

The same default, in its most confusing costume. The docs flag it directly:

> "Note that `first_value`, `last_value`, and `nth_value` consider only the rows within the 'window frame', which by default contains the rows from the start of the partition through the last peer of the current row. **This is likely to give unhelpful results for `last_value`** and sometimes also `nth_value`."

```sql
-- WRONG: returns the CURRENT row's amount on every row
LAST_VALUE(amount) OVER (PARTITION BY merchant_id ORDER BY created_at)
```

The frame ends at the current row, so "the last row of the frame" *is* the current row. `FIRST_VALUE` looks correct only because the frame's start happens to be the partition start.

**Fix — open the frame at both ends:**

```sql
LAST_VALUE(amount) OVER (PARTITION BY merchant_id ORDER BY created_at
                         ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)
```

Or sidestep it: `FIRST_VALUE(amount) OVER (... ORDER BY created_at DESC)` needs no frame clause and is harder to get wrong.

### Moving averages

The frame's most natural use — a 7-row trailing average:

```sql
AVG(amount) OVER (PARTITION BY merchant_id ORDER BY created_at
                  ROWS BETWEEN 6 PRECEDING AND CURRENT ROW)
```

Note that the first six rows average over a **shorter** frame rather than returning `NULL`. If a partial window should be suppressed, guard it with a `COUNT(*) OVER (same frame) = 7` test.

For a true *time*-based window — "everything in the last 7 days", regardless of how many rows that is — `RANGE` is the correct mode and `ROWS` is wrong:

```sql
AVG(amount) OVER (ORDER BY created_at RANGE BETWEEN INTERVAL '7 days' PRECEDING
                                                AND CURRENT ROW)
```

**That is the real `ROWS` vs `RANGE` decision: "the last 7 rows" is `ROWS`, "the last 7 days" is `RANGE`.** They differ whenever row density varies over time.

### `EXCLUDE`

> "`EXCLUDE CURRENT ROW` excludes the current row from the frame. `EXCLUDE GROUP` excludes the current row and its ordering peers from the frame. `EXCLUDE TIES` excludes any peers of the current row from the frame, but not the current row itself."

Chiefly useful for "compare me against my peers, not including me" — a leave-one-out average.

### Frame restrictions

> "*frame_start* cannot be `UNBOUNDED FOLLOWING`, *frame_end* cannot be `UNBOUNDED PRECEDING`, and the *frame_end* choice cannot appear earlier in the above list ... than the *frame_start* choice does."

The frame must run forwards. Also, window functions **cannot be nested** — the docs define the argument as "any value expression that does not itself contain window function calls." To rank a running total you need two levels, which is the same CTE-wrapping discipline as Gotcha 1.

---

## Practical patterns

| Goal | Pattern |
|---|---|
| Row's share of its group total | `amount / SUM(amount) OVER (PARTITION BY g)` |
| Running total | `SUM(x) OVER (ORDER BY t ROWS UNBOUNDED PRECEDING)` |
| Moving average, N rows | `AVG(x) OVER (ORDER BY t ROWS BETWEEN N-1 PRECEDING AND CURRENT ROW)` |
| Moving average, N days | `AVG(x) OVER (ORDER BY t RANGE BETWEEN 'N days' PRECEDING AND CURRENT ROW)` |
| Top N per group | `ROW_NUMBER()` in a CTE, filter outside |
| Nth distinct value per group | `DENSE_RANK()` in a CTE, filter outside |
| Delta from previous row | `x - LAG(x) OVER (PARTITION BY g ORDER BY t)` |
| Sessionize on idle gap | flag with `LAG`, then running `SUM` of the flag |
| Runs of consecutive values | `value - ROW_NUMBER() OVER (ORDER BY value)` is constant per run |
| Deduplicate, keep newest | `ROW_NUMBER()` per key, keep `rn = 1` |
| Median by hand | `ROW_NUMBER()` + `COUNT(*) OVER ()`, take the middle |
| First/last per group | `FIRST_VALUE` (safe) / `LAST_VALUE` (needs an explicit frame) |

### Deduplication

Worth calling out because it is the most common production use, and it is also how you delete duplicates safely:

```sql
WITH ranked AS (
    SELECT ctid, ROW_NUMBER() OVER (PARTITION BY email ORDER BY id DESC) AS rn
    FROM contact_dumps WHERE email IS NOT NULL
)
DELETE FROM contact_dumps
WHERE ctid IN (SELECT ctid FROM ranked WHERE rn > 1);
```

`ctid` is the physical tuple identifier from [[heap-storage-layout]] — useful precisely when the table has no reliable unique key, which is the situation that produced the duplicates. Note that `ctid` is not stable across `UPDATE` or `VACUUM FULL`, so it is safe inside one statement and unsafe to store.

### Median without `percentile_cont`

```sql
SELECT method, AVG(amount) AS median
FROM (SELECT method, amount,
             ROW_NUMBER() OVER (PARTITION BY method ORDER BY amount) AS rn,
             COUNT(*)     OVER (PARTITION BY method)                 AS n
      FROM transactions) s
WHERE rn IN ((n + 1) / 2, (n + 2) / 2)     -- handles odd AND even n
GROUP BY method;
```

The two expressions collide on the same row when `n` is odd and straddle the middle pair when `n` is even, so one `AVG` covers both cases. Postgres has `percentile_cont(0.5)` (interpolates between the two middle values) and `percentile_disc(0.5)` (returns an actual data value) as ordered-set aggregates — but the manual version is what gets asked. This is practice question 10.

---

## Cost and indexing

A window function needs its partition sorted. `EXPLAIN` shows a `WindowAgg` node, and directly beneath it either a `Sort` or an `Index Scan`.

An index matching `(partition_key, order_key)` can supply the rows pre-sorted and remove the `Sort` entirely — the same leftmost-prefix logic as [[composite-indexes]]. For the ranking query above, an index on `(merchant_id, amount DESC)` is what turns a full sort into an ordered scan.

Two further cost notes:

- **Several functions sharing one window cost one sort, not several.** Different windows each need their own sort, so Postgres adds a `WindowAgg` per distinct window. Reusing a named window is a real optimisation, not only tidiness.
- **Filter inside the CTE, not outside.** `WHERE` runs at step 3 and window functions at step 4.5, so a predicate placed inside shrinks what has to be sorted.

Confirming any of this is the job of `EXPLAIN ANALYZE` — the next topic in this week's sequence.

---

## Clarifications

### The unifying idea behind sessionization and gaps-and-islands

Added after recall showed both idioms were reproducible individually but their shared principle was not. This is the transferable statement.

> **`GROUP BY` can only group on equality of a value. To group by a *relationship between rows*, first compute that relationship into a per-row value that is constant across the rows that belong together — then group by that value.**

| Problem | The relationship | The constant it becomes |
|---|---|---|
| Sessionize on idle gap | "no gap > 30 min since the previous row" | running `SUM` of a boundary flag |
| Runs of consecutive dates | "this date is the previous date + 1" | `date - ROW_NUMBER()` |
| Runs of an unchanged value | "same status as the previous row" | `ROW_NUMBER() - ROW_NUMBER() PARTITION BY status` |

Every one of these conditions is about **adjacency** — a property of a *pair* of rows. `GROUP BY` cannot see pairs. It examines one row at a time and compares values for equality. So the move is always the same: **convert adjacency into equality.**

Window functions are the tool that performs that conversion, because they are the only construct in SQL that computes a per-row value *from that row's neighbours*.

**The third variant, worked.** "Runs of consecutive rows with the same status":

```sql
SELECT status,
       ROW_NUMBER() OVER (ORDER BY created_at)
     - ROW_NUMBER() OVER (PARTITION BY status ORDER BY created_at) AS grp
FROM transactions;
```

```
status        A   A   B   A   A   A
overall rn    1   2   3   4   5   6
per-status rn 1   2   1   3   4   5
difference    0   0   2   1   1   1
              \---/   |   \-------/
              run 1  run2   run 3
```

Both counters advance in lockstep while the status is unchanged, so their difference is frozen. It moves only when a different status interrupts. Group by `(status, grp)` — the difference alone can collide across different statuses, so `status` must stay in the key.

### `LAST_VALUE` — a precision point on the default frame

`FIRST_VALUE` works under the default frame because the frame's **start** is `UNBOUNDED PRECEDING`, the partition start. `LAST_VALUE` fails because the frame's **end** is `CURRENT ROW`. Two different ends of one default.

Strictly, in `RANGE` mode `CURRENT ROW` as a `frame_end` means the current row's **last peer**. So `LAST_VALUE` returns the last peer's value, which coincides with the current row's own value only when the ordering key is unique. The usual shorthand "it returns the current row" is close but not exact.

### Stating the restriction as a consequence, not a rule

"Window functions are only allowed in `SELECT` and `ORDER BY`" is the rule. The reason is the useful form:

```
3.   WHERE              <- runs here
4.5  window functions   <- computed here
```

`WHERE` cannot reference the window result because at step 3 it does not exist yet. A CTE fixes it because the CTE ends one query's evaluation entirely — in the outer query the value is an ordinary materialized column with no window nature remaining.
