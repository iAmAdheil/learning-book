---
slug: clustered-vs-nonclustered-indexes
title: Clustered vs Non-clustered Indexes
topic: databases
bloom-level: some
created: 2026-06-06
updated: 2026-09-01
published: 2026-06-09
related: [covering-indexes, btree-indexes, composite-indexes, join-algorithms, statistics-cardinality]
tags: [indexes, clustered-index, non-clustered-index, secondary-index, index-organized-table, heap, clustering-factor, innodb, postgres-cluster, uuid, interview-priority]
sources:
  - title: "Wikipedia — Database index"
    url: "https://en.wikipedia.org/wiki/Database_index"
  - title: "PostgreSQL Documentation — CLUSTER"
    url: "https://www.postgresql.org/docs/current/sql-cluster.html"
  - title: "Use The Index, Luke — Index-Organized / Clustered Tables"
    url: "https://use-the-index-luke.com/sql/clustering/index-organized-clustered-index"
---

## Answer

A **clustered index** stores the actual table rows inside the index's leaf nodes, so the table is physically ordered by that key (the table *is* the index — an "index-organized table"). A **non-clustered (secondary) index** stores only keys + a pointer back to the row. A table can have at most **one** clustered index (rows can only be physically sorted one way) but many non-clustered indexes. Postgres uses heap + separate (non-clustered) indexes; MySQL InnoDB always clusters on the primary key; SQL Server makes it optional.

```sql
-- MySQL InnoDB: table is ALWAYS clustered on the PK (rows live in the PK B-tree leaves)
-- Postgres: heap + secondary indexes; CLUSTER is a one-time, decaying reorder:
CLUSTER users USING users_pkey;   -- physically reorder heap to match this index, ONCE
```

## Q: What are the two storage models?

**Non-clustered (Postgres default):** two separate structures. Index leaf holds a **TID pointer** to the row in the heap; reading the full row needs the heap fetch. Physical row order is unrelated to any index.

**Clustered (InnoDB PK, SQL Server optional):** no separate heap — the B-tree leaf nodes *are* the rows, physically stored in key order. "A B-tree index without a heap table."

## Q: Why is every clustered-key lookup an index-only scan?

Because the row data lives *in* the clustered leaf, a lookup by the clustering key returns the whole row with **zero heap fetch** — automatically index-only. PK lookups in InnoDB are maximally fast, and range scans on the clustering key are excellent (rows physically adjacent + sorted → sequential sweep). This is why "a table with only one index is best as a clustered/index-organized table."

## Q: What's the secondary-index problem? (the key nuance)

In a clustered table, secondary indexes **can't store physical pointers** because rows move (clustered B-tree page splits shift positions). So a secondary index stores the **clustering key** instead:

```
SECONDARY INDEX on (email), table clustered by id:
  a@..  → id=3   (the PK, not a TID)
```

So `WHERE email='a@..'` is a **double lookup**: (1) search secondary index → get `id=3`; (2) search the clustered index for `id=3` to get the row. **Two B-tree descents per row**, vs a heap's one index descent + one direct heap jump. Also: the clustering key is embedded in *every* secondary index, so a fat PK bloats them all.

## Q: Is a Postgres table clustered on its PK? (Postgres vs InnoDB)

**No.** Postgres has no permanently clustered index — always heap + secondary indexes. `CLUSTER table USING index` physically rewrites the heap into *that index's* sorted order, but it is a **one-time operation that is NOT maintained** — new/updated rows go wherever there's free space, so ordering **decays**; you must periodically re-run it. `CLUSTER` takes an `ACCESS EXCLUSIVE` lock (blocks all reads + writes) → maintenance-window op.

| | Postgres | MySQL InnoDB |
|---|---|---|
| Default storage | heap + separate indexes | clustered on PK, always |
| Clustering | manual `CLUSTER`, one-time, decays | permanent + auto-maintained |
| Secondary index points via | physical TID | the PK (clustering key) |
| PK lookup | index descent + heap fetch | rows in the leaf (index-only) |
| `CLUSTER` lock | ACCESS EXCLUSIVE | n/a |

## Q: What is the clustering factor (and why it matters even in Postgres)?

How well the heap's physical order matches an index's logical order:
- **Well-correlated** (e.g. `created_at` index on append-only table): index range scan touches physically adjacent rows → few heap pages → fast.
- **Poorly correlated** (e.g. random UUID index): consecutive index entries → scattered heap rows → one random heap page per row → slow; planner may Seq Scan instead.

Real-world reason to prefer **sequential/ordered keys** (BIGINT sequence, time-ordered UUIDv7) over **random UUIDv4** for PKs: random keys collapse the clustering factor and (in clustered tables) force mid-tree page splits.

## Q: Gotchas & the practical rule

- One clustered index per table, max (one physical order).
- In InnoDB, choose a compact monotonic PK — it's embedded in every secondary index.
- Rule: single-index tables → clustered/index-organized; multi-index tables → heap + covering indexes. Postgres's heap model bets most tables have many access paths.
- Don't say "Postgres tables are clustered on the PK" — wrong; `CLUSTER` is a one-shot reorder that decays.

## Mental model

Non-clustered index = textbook back-index: terms sorted, each with a page number you flip to (heap fetch). Clustered index = dictionary: entries *are* the content in sorted order — find the word, definition is right there, no flipping. But a dictionary sorts only one way; to find words by another property you need a small back-index giving the *word* (clustering key), which you look up in the dictionary again = the secondary-index cost.

## Recall questions

1. What lives in the leaf of a clustered vs non-clustered index?
2. Why only one clustered index but many non-clustered?
3. In InnoDB, why does a secondary index store the PK instead of a physical pointer, and what does it cost on a secondary lookup?
4. Is a Postgres table clustered on its PK? What does `CLUSTER` do, vs InnoDB?
5. Why might random UUIDv4 PKs hurt vs sequential keys (clustering), and which operations suffer most?

## Clarifications

### Confirmed answers (learner, 2026-06-06 — graded 5/5 on understanding)

1. Clustered → rows; non-clustered → keys + TIDs. ✅
2. The clustered index defines physical row order; rows can only be stored in one order. ✅
3. Clustered stores rows (avoids heap fetch) → row addresses become dynamic (shift on page splits) → secondary indexes store the clustering key, not a physical pointer → 2 B-tree traversals per row on a secondary lookup. ✅ (strongest answer)
4. No, not permanent. `CLUSTER table USING index` reorders the heap to *that index's* sorted order — **one-time, decays, must re-run, takes ACCESS EXCLUSIVE lock**. InnoDB keeps PK order permanently + automatically. (Correction: the learner phrased it as "match index order OR match sorted key order" — those are the same thing, not alternatives.) ✅
5. Random keys collapse the **clustering factor** (consecutive index entries → scattered physical rows). Heap (Postgres): the problem isn't where the row lands but that index order no longer correlates with physical order → range scans do random I/O per row. Clustered (InnoDB): worse — random key forces mid-tree inserts → page splits + fragmentation. Suffering most: **range scans** (scattered pages) and **insert throughput** in clustered tables; point lookups are fine. ✅
