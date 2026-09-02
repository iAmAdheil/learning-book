---
slug: covering-indexes
title: Covering Indexes & Index-Only Scans
topic: databases
bloom-level: some
created: 2026-06-03
updated: 2026-09-01
published: 2026-06-09
related: [composite-indexes, btree-indexes, denormalization, clustered-vs-nonclustered-indexes, acid-properties, heap-storage-layout, mvcc, table-bloat-and-autovacuum, buffer-pool, join-algorithms, query-planning, explain-analyze]
tags: [indexes, covering-index, index-only-scan, include-clause, heap-fetch, visibility-map, mvcc, payload-columns, interview-priority]
sources:
  - title: "PostgreSQL Documentation — Index-Only Scans and Covering Indexes"
    url: "https://www.postgresql.org/docs/current/indexes-index-only-scans.html"
  - title: "Use The Index, Luke — Index-Only Scan / Covering Index"
    url: "https://use-the-index-luke.com/sql/clustering/index-only-scan-covering-index"
---

## Answer

A **covering index** contains *every column a query needs* — so the database answers the query from the index alone, never touching the table heap. That table-free execution is an **index-only scan**, and it works by skipping the expensive random I/O of jumping from each index leaf to scattered heap rows. It is the biggest "I tuned a query and it got 10× faster" lever after simply *having* an index.

```sql
-- Plain index: filters on id, then heap-fetches the row to read email
CREATE INDEX ON users (id);

-- Covering index: email rides along in the leaf → index-only scan, no heap
CREATE INDEX ON users (id) INCLUDE (email);
SELECT email FROM users WHERE id = 42;   -- answered from the index alone
```

## Q: What cost does it eliminate? (the heap fetch)

A normal indexed query is two steps: (1) **Index scan** — descend the B-tree to the leaf entry (cheap, ~4 reads); (2) **Heap fetch** — the leaf stores only `(key → row-pointer/TID)`, so to read other columns it follows the TID to the row's physical location in the heap. Step 2 is the killer at scale: index leaves are sorted by key, but heap rows are scattered in insertion order, so fetching 40,000 matches = 40,000 **random** heap jumps (the slowest disk operation). If the needed columns are *in the leaf*, step 2 disappears → index-only scan.

## Q: How do you build one — key column vs INCLUDE?

Two ways to put a column in the index:

- **Key column (composite):** `CREATE INDEX ON users (id, email)` — covers, but also sorts by `email` (space + write cost you don't need if you never search by email).
- **INCLUDE (payload), the right tool:** `CREATE INDEX ON users (id) INCLUDE (email)` (Postgres 11+).

| | Key columns | INCLUDE / payload |
|---|---|---|
| Purpose | search, sort, range | *just stored* for retrieval |
| Sorted in tree? | yes | **no** |
| In upper (branch) nodes? | yes | **no** — leaves only (suffix truncation keeps tree small) |
| Data type | indexable | any |
| Counts toward UNIQUE? | yes | no |

Mental model: **key columns are how you find the row; INCLUDE columns are what you carry back.** Use INCLUDE when you never filter/sort by the column but keep SELECT-ing it.

## Q: How are INCLUDE columns physically stored, and how do updates work?

Physically the leaf holds them together — same as a composite at the leaf level:
```
leaf: [ subsidiary_id=5 | eur_value=200 | TID ]
          key(sorted)      payload(unsorted)  heap pointer
```
Two differences from a composite `(a, b)`: (1) **sort order** — tree sorted by key *only*; the payload has zero effect on ordering; (2) **placement** — payload lives only in leaves, stripped from upper nodes, so the navigational tree stays lean (a composite copies `b` into every level).

Updates: updating a **key** column moves the entry in the sorted tree (delete + insert). Updating a **payload** column still forces index maintenance — because of MVCC the UPDATE writes a new heap row version, which needs a new index entry carrying the new payload value; the old leaf entry lingers until VACUUM. (Nuance for later: Postgres HOT can skip index updates when *no indexed column* changes and the new version fits the same page — but changing an INCLUDE'd column disqualifies HOT.)

## Q: Why can a covering index STILL hit the heap in Postgres? (visibility map + MVCC)

The Postgres-specific gotcha. **MVCC** (Multi-Version Concurrency Control) keeps *multiple versions* of each row so readers and writers don't block each other: an UPDATE writes a new version + marks the old expired; a DELETE marks a version dead; each transaction sees the version valid when it started. Result: the heap holds a mix of live, dead, and not-yet-visible rows, so "is this row visible to *me*?" has a per-transaction answer.

The index leaf stores the value but **not** this visibility bookkeeping. So Postgres consults the **visibility map (VM)** — a tiny bitmap (~4 orders of magnitude smaller than the heap), one bit per heap *page*, set when every row on that page is visible to all transactions:
```
for each matching index entry:
    if VM says its page is all-visible:  return value from index   ✅ no heap
    else:                                heap-fetch to check visibility ⚠️ speedup lost
```
`VACUUM` is what sets VM bits. Consequence: index-only scans shine on **static / read-heavy** tables (VM bits set); on **write-hot** tables version churn clears VM bits → constant fallback → benefit evaporates. An under-vacuumed table won't get index-only scans even with a perfect covering index. (Full MVCC — xmin/xmax, dead tuples, VACUUM — is its own topic; this much suffices for indexes.)

## Q: Trade-offs — when NOT to do it

- **Re-taxes writes:** updating a payload column updates the index too (same read-vs-write trade as B-trees / denormalization).
- **Wide payloads bloat the index** → more pages per scan, more cache. Don't INCLUDE large text/JSON.
- **Don't speculatively cover.** Index first without the SELECT list; add INCLUDE only when a *measured* hot query justifies it.
- **Extending WHERE silently breaks coverage.** `SELECT SUM(eur_value) WHERE subsidiary_id=?` is covered by `(subsidiary_id) INCLUDE (eur_value)`; adding `AND sale_date > ?` un-covers it (sale_date not in index → heap fetch). Always re-check the plan.

## Q: How do you confirm it? (EXPLAIN preview)

- `Seq Scan` — no index (whole table).
- `Index Scan` — index found rows, then heap fetches (two-step).
- `Index Only Scan` — covered, heap skipped; reports `Heap Fetches: N` (VM-forced fallbacks). `Heap Fetches: 0` = perfect.

## Mental model

A plain index is a **library catalog card**: tells you the shelf, then you walk to the book (heap fetch). A covering index **prints the answer on the card** — INCLUDE columns are extra facts on the card. Postgres twist: before trusting the card, glance at a tiny "is this card current?" list (visibility map) — usually instant, but if recently touched you still walk to the shelf.

## Recall questions

1. What two steps does a normal Index Scan perform, which does Index Only Scan eliminate, and why is it expensive at scale?
2. Key column vs INCLUDE column — difference, and when to use INCLUDE?
3. `(subsidiary_id) INCLUDE (eur_value)` covers `SELECT eur_value WHERE subsidiary_id=5`; you add `AND sale_date > '2026-01-01'`. What happens and why?
4. Why can a perfectly covering index still read the heap in Postgres? What structure decides this, and what table type makes index-only scans unreliable?
5. What's the cost of INCLUDE columns and the rule of thumb for adding them?

## Clarifications

### Confirmed answers (learner, 2026-06-03 — graded 5/5)

1. Descend B-tree to leaf (has TID) → follow TID to heap row; index-only eliminates the heap fetch; 40,000 matches = 40,000 random fetches, expensive at scale. ✅
2. Key = search/filter/range + return; INCLUDE = stored only for SELECT, never used to find rows. ✅
3. Drops to Index Scan: index filters on subsidiary_id, sale_date read from heap and applied as filter (not in index → un-covered). ✅
4. MVCC + visibility map (learner flagged not understanding MVCC — taught below). ✅ (after explanation)
5. Writes more expensive (index updated when payload changes); learner asked the right deeper questions about storage + updates — answered below. ✅

### MVCC (pre-taught here so the later MVCC topic can go deeper)

MVCC keeps multiple row versions so readers/writers don't block: UPDATE writes a new version + expires the old; DELETE marks dead; each txn sees the version valid at its start. The index stores values but not version-visibility, so an index-only scan must consult the visibility map (or fall back to the heap) to know its value is from a currently-visible version. Write-hot tables clear VM bits (recent churn) → fallbacks; static tables keep them set → fast index-only scans. VACUUM sets VM bits. (See [[btree-indexes]] write-tax and the future MVCC/autovacuum topics.)

### INCLUDE storage & updates (learner question)

Leaf holds key+payload together (like a composite at leaf level), BUT: tree sorted by key only (payload has no effect on ordering), and payload lives only in leaves (stripped from upper nodes via suffix truncation, keeping navigation lean — a composite copies the second key into every level). So `(a,b)` vs `(a) INCLUDE (b)`: same leaf payload, but INCLUDE is leaner and `b` is unsearchable — use INCLUDE for ride-along, composite to also search/sort by `b`. Updating a payload column still triggers index maintenance via MVCC's new-version-needs-new-index-entry; HOT can skip index work only when no indexed column changes (so changing an INCLUDE'd column disqualifies it).
