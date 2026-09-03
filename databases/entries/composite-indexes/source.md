---
slug: composite-indexes
title: Composite Indexes — Column Order & the Leftmost-Prefix Rule
topic: databases
bloom-level: some
created: 2026-06-03
updated: 2026-09-01
published: 2026-06-09
related: [btree-indexes, denormalization, relational-data-model, covering-indexes, sql-fundamentals, window-functions, join-algorithms, query-planning, explain-analyze, statistics-cardinality]
tags: [indexes, composite-index, multicolumn-index, leftmost-prefix, column-order, equality-before-range, selectivity, bitmap-scan, skip-scan, interview-priority]
sources:
  - title: "PostgreSQL Documentation — Multicolumn Indexes"
    url: "https://www.postgresql.org/docs/current/indexes-multicolumn.html"
  - title: "Use The Index, Luke — Concatenated Keys (column order)"
    url: "https://use-the-index-luke.com/sql/where-clause/the-equals-operator/concatenated-keys"
  - title: "Use The Index, Luke — Indexing range conditions"
    url: "https://use-the-index-luke.com/sql/where-clause/searching-for-ranges/greater-less-between-tuning-sql-access-filter-predicates"
---

## Answer

A **composite (multicolumn) index** is a single B-tree built over two or more columns. It sorts rows by the **first column, then by the second within each first-column value, and so on** — exactly like a phone book sorted by `(last_name, first_name)`. This one fact dictates the **leftmost-prefix rule**: the index can only be used for queries that constrain a *leading prefix* of its columns. Column order is therefore not cosmetic — it decides which queries the index can serve at all.

```sql
CREATE INDEX ON employees (last_name, first_name);
-- usable: WHERE last_name='Adams'           (leading col)
-- usable: WHERE last_name='Adams' AND first_name='Bob'
-- NOT efficiently usable: WHERE first_name='Bob'  (leading col missing → scattered)
```

## Q: How does the sort actually work?

`(last_name, first_name)` produces leaves like:
```
Adams, Alice
Adams, Bob
Baker, Alice    <- first_name ordering restarts within each last_name
Baker, Carl
Clark, Dan
```
`first_name` is only sorted *within* a single `last_name`. Globally the second column is scattered (all "Alice"s spread across the index). That scattering is the root cause of every rule below.

## Q: What is the leftmost-prefix rule? (the heart)

An index on `(A, B, C)` can efficiently serve a query only if it constrains a **leftmost prefix**:

| Query filters on | `(A, B, C)` usable? | Why |
|---|---|---|
| A | ✅ | leading column |
| A, B | ✅ | prefix |
| A, B, C | ✅ full | whole key |
| A, C (B skipped) | ⚠️ partial | seek on A, then *filter* for C |
| B alone | ❌ | scattered (phone book by first name) |
| C alone | ❌ | worse |
| B, C | ❌ | no leading A → can't start descent |

Postgres rule: *"Equality constraints on leading columns, plus any inequality on the first column without an equality constraint, will always be used to limit the portion of the index scanned."* The phone-book test: "find everyone with first name = Alice" in a book sorted by (last, first) forces flipping every page → Seq Scan. Most common production indexing bug.

## Q: Why isn't one composite index the same as two single-column indexes?

- `INDEX (a, b)` serves `WHERE a=...` and `WHERE a=... AND b=...` — but **not** `WHERE b=...`.
- It doubles as a usable index on `a` alone (the prefix), so a separate `INDEX (a)` is usually **redundant — drop it.**
- It does nothing for `WHERE b=...`; that needs its own `INDEX (b)`.

So the design question is never "which columns" but **"what order, given actual query patterns."** The leading column should be one you filter on in (almost) every query.

## Q: How do you choose column order? (three rules)

**Rule 1 — Equality columns before range columns (the big one).**
```sql
WHERE status = 'active' AND created_at > '2026-01-01';
```
- `(status, created_at)` ✅ — seek `status='active'`, then walk the `created_at` range *within* that status. Both narrow.
- `(created_at, status)` ❌ — range on the leading column gives a big date span; `status` is scattered within it → can only **filter**, not seek.

Mechanism: a range scan "uses up" the index ordering — **every column after a range column can only be filtered, not seeked.** Put range columns last among the columns you want to narrow on.

**Rule 2 — Most-frequently-queried column leads.** If half your queries don't filter on A, A shouldn't lead — those queries can't use the index at all.

**Rule 3 — Selectivity as a tiebreaker.** Among equality columns, the more selective one (eliminates more rows, e.g. `user_id` over `is_deleted`) first narrows faster. Secondary to query patterns.

## Q: What does the DB do when you skip the leading column?

1. **Bitmap index scan** — with *separate* single-column indexes on `a` and `b`, Postgres scans both and combines results (bitmap AND/OR). Why "several single-column indexes + bitmap scans" can beat one rigid composite when query patterns are unpredictable.
2. **Skip scan** (Postgres 18+, long in Oracle) — for `INDEX (a, b)` and `WHERE b=7`, the planner loops over each distinct `a` and seeks `(a=N, b=7)`. Only worthwhile when `a` has **few distinct values** (e.g. boolean); otherwise degrades to a full scan.

## Q: Gotchas

- **Don't over-index.** Postgres: indexes beyond ~3 columns rarely help unless usage is "extremely stylized." Each column adds write cost + size.
- **Redundant-prefix trap.** Both `INDEX (a)` and `INDEX (a, b)` → `(a)` is usually dead weight. Audit and drop.
- **ORDER BY must match the prefix.** `INDEX (a, b)` satisfies `ORDER BY a, b` or `WHERE a=... ORDER BY b` for free — but not `ORDER BY b, a`.
- **A range in the middle kills the tail.** `WHERE a=1 AND b>5 AND c=9` on `(a,b,c)`: seek a, range b, but c only **filtered** (the b-range broke ordering for c). If c-equality matters more, reorder to `(a, c, b)`.

## Mental model

A composite index is a **phone book sorted by (last, first)**. Look up by last name, or last+first — never first name alone (scattered across every page). Column order = which name comes first. A range query = "everyone Adams→Clark": once that range is open, the second name is no longer in usable order, so you can only filter, not seek.

## Recall questions

1. `INDEX (a, b, c)` — prefix-usable or not: `WHERE a=1`; `WHERE b=2`; `WHERE a=1 AND c=3`; `WHERE a=1 AND b=2 AND c=3`; `WHERE b=2 AND c=3`.
2. Phone-book analogy: why can't `WHERE b=2` use `INDEX (a, b)`?
3. `WHERE tenant_id = 42 AND created_at > now() - interval '7 days'` — which order and why?
4. You have `INDEX (user_id, created_at)`; a teammate adds `INDEX (user_id)`. What's wrong, what to do?
5. `INDEX (a, b, c)` with `WHERE a=1 AND b>100 AND c=5` — which columns narrow the scan, which becomes a filter, why?

## Clarifications

### Confirmed answers (learner, 2026-06-03 — graded 5/5 on answers)

1. works / does not / partially / fully / does not. ✅
2. Index sorted by A then B-within-A; B alone is unsorted globally → Seq Scan, or skip-scan search within each A value only if A has few distinct values. ✅
3. `(tenant_id, created_at)` — equality before range. Seek tenant_id=42, walk created_at range within it. (Precision note the learner needed: in the *bad* order `(created_at, tenant_id)`, it's **tenant_id** that degrades to a filter, because it follows the range column — attach "falls back to filter" to the column *after* the range, in the layout being critiqued.) ✅
4. Both cover `WHERE user_id=...`; the composite also covers user_id+created_at; standalone `(user_id)` is redundant → drop it. ✅
5. a = seek, b = seek+walk (range), c = filter — the range on b breaks ordering for c so c can't be seeked. ✅
