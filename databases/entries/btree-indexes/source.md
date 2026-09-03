---
slug: btree-indexes
title: B-tree Indexes — Structure & How Range/Equality Queries Use Them
topic: databases
bloom-level: some
created: 2026-05-31
updated: 2026-09-01
published: 2026-06-09
related: [denormalization, relational-data-model, schema-design-normalization, composite-indexes, partial-and-expression-indexes, sql-fundamentals, window-functions, join-algorithms, query-planning, explain-analyze, statistics-cardinality]
tags: [indexes, b-tree, b+tree, query-performance, sequential-scan, range-query, expression-index, disk-io, interview-priority]
sources:
  - title: "PostgreSQL Documentation — B-Tree Indexes"
    url: "https://www.postgresql.org/docs/current/btree.html"
  - title: "Wikipedia — B-tree"
    url: "https://en.wikipedia.org/wiki/B-tree"
  - title: "Use The Index, Luke — Anatomy of an Index"
    url: "https://use-the-index-luke.com/sql/anatomy/the-tree"
---

## Answer

An **index is a separate, sorted data structure that lets the database find rows by value without scanning the whole table** — turning an O(n) "look at every row" into an O(log n) "walk down a shallow tree." A **B-tree** is the structure that makes this work *on disk*, for both equality *and* range queries, while keeping data sorted (so it also serves `ORDER BY` for free). It is the default and most common index type in relational databases.

```sql
-- Without an index: Seq Scan reads all 10M rows
SELECT * FROM comments WHERE post_id = 42;

CREATE INDEX idx_comments_post_id ON comments(post_id);
-- Now: ~4–5 page reads via the tree, regardless of table size
```

## Q: What problem does an index solve?

A table is a heap — an unordered pile of rows. With no index, `WHERE post_id = 42` forces a **sequential scan (Seq Scan)**: read every row and check it (O(n)). The naive fix is "keep data sorted and binary-search it," but you can't keep the table itself sorted (constant inserts; you'd need a different order per column). So the DB builds a **separate sorted structure that points back to the rows** — the B-tree.

## Q: Why a B-tree and not a binary search tree?

Database indexes live **on disk**, read in fixed **pages** (8 KB in Postgres). The bottleneck is **disk reads**, not comparisons (a disk fetch is ~10,000× slower than an in-memory compare). A binary tree (2 children/node) is tall and thin → many disk fetches. A B-tree packs **many keys into each node (sized to one page)** → wide and shallow → few disk fetches. **Node count ∝ disk fetches**, so minimizing nodes visited is the whole game.

```
Binary tree (10M rows): depth ~23  → up to 23 disk reads
B-tree   (10M rows):    depth 4–5  → 4–5 disk reads     (each level ~100× capacity)
```

Three defining properties: **balanced** (all leaves at same depth → every lookup costs the same, no slow path), **sorted** (keys ordered), **multi-way** (high fanout, not just 2 children).

## Q: What's the anatomy on disk?

Production DBs use a **B+ tree**. Three layers:

- **Leaf nodes** — hold the actual entries `(indexed value → pointer to table row)`. In a B+ tree *all* data is in the leaves, and **leaves are chained in a doubly-linked list in sorted order**. (This chain is why range queries are fast.) The row pointer is a **TID/RID** (physical row location in the heap).
- **Branch nodes** — pure navigation: each entry stores the *max value* of the child below + a pointer down. No row data, just signposts.
- **Root** — a single page at the top.

## Q: How does an equality query use it?

`WHERE post_id = 42`: start at **root**, scan for first key ≥ 42, follow pointer → **branch**, repeat → **leaf**, find `42`, read its row pointer (TID), jump to the heap row. **~4–5 page reads total, regardless of table size.** This is why adding `comments(post_id)` can make a denormalized counter column unnecessary — it turns "scan 10M rows" into a 4-hop tree walk.

## Q: How does a range query use it? (what equality-only structures can't do)

```sql
SELECT * FROM orders WHERE created_at BETWEEN '2026-01-01' AND '2026-03-31';
```

1. Traverse root→branch→leaf **once** to find the first entry ≥ lower bound.
2. **Walk the leaf linked-list sideways**, reading in order, until past the upper bound.

One descent, then a sequential sweep along already-sorted leaves — no re-traversal per row. B-tree supports the full `<, <=, =, >=, >` family (hence `BETWEEN`, `IN`, ranges) because leaves are sorted + linked.

**ORDER BY for free:** `SELECT ... ORDER BY created_at LIMIT 10` reads the first 10 leaf entries in order — no separate sort step. (Postgres docs call sorting B-tree's primary use case.)

## Q: When does a B-tree index NOT get used? (gotchas / interview traps)

- **`<>` / `NOT IN`** — "everything except 42" isn't a contiguous range → Seq Scan.
- **Leading wildcard** — `LIKE 'abc%'` works (a range); `LIKE '%abc'` can't (no known prefix → no start point).
- **Function/expression on the column** — `WHERE lower(email) = 'a@b.com'` won't use a plain index on `email`. Fix: expression index `CREATE INDEX ON users(lower(email))`. (See clarification below — this is the deepest point.)
- **NULLs** — operators require comparable values and `NULL` isn't; Postgres stores NULLs separately so `IS NULL` can use the index, but `= NULL` is always a logic error.
- **Write tax** — every INSERT/UPDATE/DELETE must incrementally maintain *every* index (insert/remove leaf entry, occasionally split a page to rebalance). Same trade as denormalization: faster reads paid for at write time. Don't index columns you never filter/sort by.
- **Planner may choose Seq Scan anyway** — if a query returns a large fraction of rows (>~5–10%), index + scattered heap jumps is slower than a linear heap scan. Indexes help **selective** queries (few matches). Estimated via statistics (later topic).

## Q: Why does f(column) defeat the index — and why does lower(email)=... match all casings?

Key correction many people hit: **`lower()` is applied to the stored COLUMN value, not to your search string.** `WHERE lower(email) = 'a@b.com'` means, per row: "take this row's `email`, lowercase it, compare *that* to `'a@b.com'`." So a row stored as `A@b.com` evaluates `lower('A@b.com') = 'a@b.com'` → **TRUE**. Every casing variant (`a@b.com`, `A@b.com`, `A@B.COM`, …) collapses to `a@b.com` and matches.

A plain index on `email` is a tree sorted by the **raw stored strings** (ASCII: uppercase before lowercase), so those matching variants are **scattered across the whole index** — there is no single contiguous span to descend to. The planner does a **syntactic** match: it looks for an index *defined on* the exact expression in the predicate (`lower(email)`), finds only one on `email`, and gives up — it will **not** apply `lower()` to stored entries on the fly, because doing so would require visiting every entry (= a full scan, defeating the point of sortedness).

`CREATE INDEX ON users(lower(email))` computes `lower()` at write time and stores *those* values sorted — now all casing variants collapse to one adjacent value, and the target is a locatable position. **Rule: a B-tree is usable only when the query filters by the exact expression the tree is sorted on.** (Same reason `WHERE age + 1 = 30` won't use an index on `age`, but `WHERE age = 29` will.)

Contrast: `WHERE email = 'a@b.com'` (no `lower()`) compares the raw value, matches only the literal `a@b.com`, and **can** use a plain index on `email` — predicate dimension matches sort dimension.

## Mental model

A B-tree is a **phone book**. Equality = flip straight to the name. Range = find the first name, then read forward (pages already in order). Fast on disk because each page holds hundreds of names → any name in 4–5 flips. Keeping it sorted costs effort on every insert/delete = the write tax.

## Recall questions

1. Why a B-tree (high fanout, shallow) over a binary tree for an on-disk index? What's the real bottleneck?
2. Step through how `WHERE id = 42` finds its row.
3. Why can a B-tree serve `BETWEEN` and `ORDER BY` efficiently but an equality-only structure can't? Which leaf property enables it?
4. Which can use a B-tree index on `email`: `email = 'a@b.com'`, `LIKE 'a%'`, `LIKE '%@b.com'`, `lower(email) = 'a@b.com'`? Why each?
5. You add 5 indexes to a write-heavy table for read speed. What got worse and why? Connect it to a prior topic.

## Clarifications

### Confirmed answers (learner, 2026-05-31 — graded 5/5 on understanding)

1. Minimize disk fetches; node count ∝ fetches; nodes sized to one page, >2 keys/children → wide & shallow. ✅
2. Range-narrow through internal nodes, find value at leaf, follow row pointer. (Each hop = one page read; ~4–5 total.) ✅
3. Leaves are sorted and doubly-linked → one descent then walk sideways for ranges/ORDER BY. ✅
4. `=` and `LIKE 'a%'` → yes (known prefix = range). `LIKE '%@b.com'` → no (unknown start). `lower(email)=` → no on plain index; needs expression index on `lower(email)`. ✅
5. Write tax: each write incrementally maintains all 5 indexes (insert/remove leaf + page splits), hurting write throughput — same read-vs-write trade as denormalization. ✅

### Why f(column) defeats the index — the "does it match all casings?" confusion

Resolved misconception: `lower()` transforms the **stored column value** before comparison, not the search literal. So `lower(email) = 'a@b.com'` matches every casing variant (each lowercases to `a@b.com`). Those variants are scattered across a tree sorted by raw `email`, so no contiguous span exists to descend to; the planner matches indexes syntactically against the exact predicate expression and won't evaluate the function across stored entries on the fly. Expression index on `lower(email)` stores the transformed, sorted values and fixes it.
