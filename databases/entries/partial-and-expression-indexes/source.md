---
slug: partial-and-expression-indexes
title: Partial & Expression Indexes
topic: databases
bloom-level: some
created: 2026-06-06
updated: 2026-06-06
published: 2026-06-09
related: [btree-indexes, covering-indexes, composite-indexes, clustered-vs-nonclustered-indexes]
tags: [indexes, partial-index, expression-index, functional-index, unique-constraint, soft-delete, case-insensitive, write-tax, interview-priority]
sources:
  - title: "PostgreSQL Documentation — Partial Indexes"
    url: "https://www.postgresql.org/docs/current/indexes-partial.html"
  - title: "PostgreSQL Documentation — Indexes on Expressions"
    url: "https://www.postgresql.org/docs/current/indexes-expressional.html"
---

## Answer

A **partial index** indexes only the rows matching a `WHERE` predicate (a *horizontal slice* of the table); an **expression index** indexes the result of a function instead of the raw column (a *vertical transform*). Both make the index smaller and more specialized — faster scans and a lower write tax (partial) or read speedup at extra write cost (expression). They are orthogonal and combine.

```sql
-- Partial: index only active users
CREATE INDEX idx_active_users ON users (email) WHERE deleted_at IS NULL;
-- Expression: index the transformed value for case-insensitive search
CREATE INDEX idx_lower_email ON users (lower(email));
```

## Q: What is a partial index and when do you use it?

Indexes only rows satisfying a predicate. If 90% of a soft-delete table is deleted rows you never query, a full index wastes 90% of its space + write effort; the partial index is ~10% the size and writes to excluded rows don't touch it. Three canonical uses:

1. **Soft deletes / active rows (most common):** `CREATE INDEX idx_orders_pending ON orders (created_at) WHERE status = 'pending';` — index only what you query.
2. **Exclude common values:** the planner won't use an index for a value matching a large fraction of rows anyway, so don't index them: `CREATE INDEX ON orders (order_nr) WHERE billed IS NOT TRUE;`
3. **Partial UNIQUE (powerful):** `CREATE UNIQUE INDEX one_primary ON cards (user_id) WHERE is_primary;` — "at most one primary card per user" while allowing unlimited non-primary. A plain `UNIQUE (user_id)` can't express this (it would forbid more than one card *at all*). The predicate scopes the uniqueness to the subset.

## Q: The critical rule — when can the planner use a partial index?

Only if it can **prove at planning time** that the query's WHERE guarantees the index predicate.
```sql
-- Index: WHERE status = 'pending'
WHERE status = 'pending' AND created_at > '...'  -- ✅ matches
WHERE created_at > '...'                          -- ❌ no status filter
```
- Simple inequality implication works (`x < 1` implies `x < 2`); subtle implications don't.
- **Parameterized queries break it:** `WHERE status = $1` can't match `WHERE status = 'pending'` because `$1` is unknown at planning time. Common cause of "why isn't my partial index used?" with ORMs/prepared statements.

## Q: Expression indexes (formalized from the lower(email) deep-dive)

The index stores `f(column)` instead of `column`:
```sql
CREATE INDEX ON users (lower(email));
SELECT * FROM users WHERE lower(email) = 'a@b.com';   -- ✅ uses it
```
- The query must use the **exact same expression** as the index; the planner treats it like a normal `indexedcol = const` lookup.
- The expression is computed **at write time, stored, never recomputed on read** — that's the read benefit.
- Cost: heavier **write tax** — the function is *recomputed on every insert and non-HOT update* (the distinguishing cost over a plain index, which also updates but doesn't recompute an expression).
- Multi-column: `CREATE INDEX ON people ((first_name || ' ' || last_name))` (double parens required for general expressions).
- Expression UNIQUE: `CREATE UNIQUE INDEX ON users (lower(email))` enforces case-insensitive uniqueness — a plain UNIQUE can't.

## Q: Combining them (production power move)

```sql
CREATE UNIQUE INDEX uniq_active_email
  ON users (lower(email))      -- expression: case-insensitive
  WHERE deleted_at IS NULL;    -- partial: only active users
```
"Case-insensitive-unique email, but only among non-deleted users" → a soft-deleted user frees their email for reuse. Encodes a business rule that would otherwise need app logic + risk a race. Great answer to "enforce unique active emails with soft deletes."

## Q: Gotchas

- Partial predicate must be in/implied by the query, provably (bound parameters defeat it).
- Don't fake partitioning with many partial indexes (one per category) — planner tests each; use real table partitioning.
- Expression index needs the *exact* expression (`lower(email)` ≠ `email` ≠ `upper(email)`).
- Write tax direction: partial *lowers* it (fewer rows), expression *raises* it (recompute per write).

## Mental model

Normal index = full guest list, names as given. Partial index = VIP-only list — shorter/faster, useless for non-VIPs (query must be about VIPs). Expression index = list sorted by *nickname* — perfect if you always search by nickname, useless by legal name. A VIP list sorted by nickname = both combined.

## Recall questions

1. Partial vs expression index in one line each — which dimension does each shrink?
2. Partial index for "at most one primary email per user, many non-primary allowed" — and why can't plain UNIQUE do it?
3. Index `(status) WHERE status='pending'`; ORM emits `WHERE status = $1` with `$1='pending'`. Used? Why?
4. Why does an expression index *raise* write cost while partial *lowers* it?
5. One index enforcing case-insensitive unique emails only among non-deleted users — and the rule it encodes.

## Clarifications

### Confirmed answers (learner, 2026-06-06)

1. ✅ Partial = subset of rows matching a predicate (lowers read+write tax); expression = indexes function values (raises write tax). (Refinement: predicate is any condition, not only a "category".)
2. ⚠️ CORRECTION: learner wrote `UNIQUE ON users(email) WHERE is_primary` — wrong column. Must be UNIQUE on **user_id**: `CREATE UNIQUE INDEX ON emails (user_id) WHERE is_primary;`. Rule = uniqueness applies to the column that must be unique *within the predicate subset*. Plain `UNIQUE(user_id)` fails because it forbids more than one email at all; the partial predicate scopes uniqueness to primary rows only.
3. ✅ Not used — planner must prove/match the predicate at planning time; bound parameter `$1` unknown then.
4. ✅ Right direction. Sharpen: ALL indexes update on writes to the column; the *expression-specific* extra cost is recomputing the function each write. Partial lowers cost because writes to rows outside the predicate skip the index.
5. ✅ `CREATE UNIQUE INDEX ON users(lower(email)) WHERE deleted_at IS NULL;` — case-insensitive unique among active users; soft-deleted user frees email for reuse.
