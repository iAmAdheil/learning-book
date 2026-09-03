---
slug: table-bloat-and-autovacuum
title: Table Bloat & Autovacuum — Reclaiming What MVCC Leaves Behind
topic: databases
bloom-level: some
created: 2026-06-17
updated: 2026-09-01
published: 2026-06-30
related: [mvcc, heap-storage-layout, covering-indexes, isolation-levels, write-ahead-log, buffer-pool, statistics-cardinality]
tags: [vacuum, autovacuum, table-bloat, dead-tuple, vacuum-full, pg-repack, free-space-map, visibility-map, all-visible, all-frozen, freezing, xid-wraparound, relfrozenxid, oldest-xmin, anti-wraparound, replication-slot, reindex, planner-statistics, analyze, interview-priority]
sources:
  - title: "PostgreSQL Documentation — Routine Vacuuming"
    url: "https://www.postgresql.org/docs/current/routine-vacuuming.html"
  - title: "The Internals of PostgreSQL §6.1 — Vacuum Processing"
    url: "https://www.interdb.jp/pg/pgsql06/01.html"
---

## Answer

Because MVCC ([[mvcc]]) never erases a row in place — DELETE stamps `xmax`, UPDATE writes a new version — every table fills with **dead tuples**: old versions no living snapshot can see. **Bloat** is that accumulated dead space; **VACUUM** is the garbage collector that makes it reusable; **autovacuum** is the daemon that runs VACUUM before the table drowns. The keystone trap: **plain VACUUM does *not* return space to the OS — it makes dead space *reusable* by future rows.** The file stays the same size; that single fact explains most "why is my table still huge after I vacuumed?" confusion.

```sql
SELECT relname, n_dead_tup, n_live_tup, last_autovacuum
FROM pg_stat_user_tables ORDER BY n_dead_tup DESC;
SELECT datname, age(datfrozenxid) FROM pg_database;  -- wraparound fuel gauge
```

## Q: What bloat is?

Two things accumulate: (1) **dead tuples** — old versions whose deleting txn committed *and* sits below the `OldestXmin` horizon ([[mvcc]]); (2) **internal free space** inside pages. A table is bloated when these dominate live data, so 1M live rows may occupy 5M rows' worth of pages → slower seq scans, worse cache hit ratio, bigger backups. A dead tuple is only *removable* when its `xmax` committed **and** `xmax < OldestXmin`.

## Q: Plain VACUUM vs VACUUM FULL?

| | **plain `VACUUM`** | **`VACUUM FULL`** |
|---|---|---|
| Does | marks dead space **reusable**, records it in the **FSM** | **rewrites the whole table** into a new file, zero dead space |
| Returns space to OS? | **No** (can truncate *trailing* empty pages only) | **Yes** (old file dropped) |
| Lock | `SHARE UPDATE EXCLUSIVE` — reads & writes proceed | `ACCESS EXCLUSIVE` — **blocks everything** |
| `relfilenode` | unchanged | **new file** → a *rewrite* op ([[heap-storage-layout]]), needs ~2× disk |
| Use | routine, frequent | emergency only |

Doctrine: run plain VACUUM often enough to never need VACUUM FULL. In production the shrink-job is usually **`pg_repack`** (rebuilds table + indexes with only a *brief* lock) — VACUUM FULL's exclusive lock is an outage.

## Q: How plain VACUUM works mechanically?

Three blocks (interdb), each tied to known structures:
1. **Scan & collect dead TIDs** into `maintenance_work_mem` (if it fills → multiple index passes).
2. **Clean indexes** — remove every index entry pointing at a dead TID (∴ more indexes = costlier VACUUM).
3. **Vacuum heap page-by-page** — remove dead tuples, **defragment** (slide live tuples together = in-page compaction from [[heap-storage-layout]]), update **FSM** + **visibility map**. Finally **truncate trailing empty pages**.

Two precise facts:
- **Line pointers are not freed, only marked `LP_UNUSED`.** Reclaiming a slot would shift offset numbers → change live rows' TIDs → force rewriting every index entry. So slots recycle in place, keeping TIDs stable.
- **The VM lets VACUUM skip all-visible pages** (full scan → targeted), and a **ring buffer** keeps VACUUM from evicting hot pages from `shared_buffers`.

## Q: The visibility map's two bits?

The `_vm` fork stores **two bits per page**:
- **all-visible** → powers **index-only scans** ([[covering-indexes]] — index can't judge visibility, this bit lets it skip the heap fetch) *and* lets *normal* VACUUM skip the page.
- **all-frozen** → all tuples frozen; lets even an **aggressive / anti-wraparound** VACUUM skip the page (the freeze scan is the expensive one, so this is what keeps wraparound vacuums affordable on huge cold tables).

## Q: Freezing & XID wraparound?

`xmin`/`xmax` are **32-bit**, compared **modulo 2³²** — a **circle with no endpoint**: `age = current_xid − xmin (mod 2³²)`; each XID has ~2 billion "older" and ~2 billion "newer." If an old tuple's `xmin` is never handled, once the gap exceeds ~2³¹ it flips from past to **future** → its insert becomes **invisible** → silent data loss.

**Freezing** escapes the circle: VACUUM stamps sufficiently-old tuples `HEAP_XMIN_FROZEN` (a flag since PG 9.4; older clusters set `xmin = FrozenTransactionId = 2`) = "older than every normal XID, forever." Machinery: `pg_class.relfrozenxid` (oldest unfrozen XID; `age()` = txns since), `vacuum_freeze_min_age` (freeze threshold), **`autovacuum_freeze_max_age`** (hard deadline → forces **anti-wraparound autovacuum even on append-only tables and even if autovacuum is off**). Failure ladder: ~40M XIDs left → `WARNING: must be vacuumed within N transactions`; ~3M left → **`ERROR: database is not accepting commands to avoid wraparound data loss`** (refuses all writes until vacuumed). A parallel **multixact ID** wraparound exists for shared row locks.

## Q: Autovacuum — who pulls the trigger?

A **launcher** spawns **workers** (`autovacuum_max_workers`, default 3) every `autovacuum_naptime` (10s). Fires when:
```
vacuum threshold = autovacuum_vacuum_threshold (50)
                 + autovacuum_vacuum_scale_factor (0.1) × n_live_tuples
```
So a 1M-row table waits for **~100,050 dead tuples**. Autovacuum also runs **ANALYZE** to refresh **planner statistics** (histograms, n_distinct). I/O throttled by `autovacuum_vacuum_cost_delay`/`cost_limit` (balanced across workers); overridable **per table**:
```sql
ALTER TABLE events SET (autovacuum_vacuum_scale_factor = 0.02);  -- vacuum a hot big table sooner
```

## Mental model

A **library that never discards old editions**. A revised book's old edition isn't burned — just stamped "withdrawn" on the spine (`xmax`; the dead tuple). **VACUUM is the nightly round:** she pulls withdrawn editions and, instead of demolishing shelving, jots each empty slot on an index card at the desk (the **FSM**) so tomorrow's books refill the gaps. The building never shrinks — only relocating every kept book into a fresh smaller building (**VACUUM FULL**) does, and the library must close its doors while it happens. Quirk: the date stamp is a **circular wheel of ~4 billion positions**; an edition left too long will, once the wheel loops, look like it arrived *tomorrow* and vanish from the catalog — so very old settled books get re-stamped **"ANCIENT — predates everything"** (**freezing**). Fall catastrophically behind and management **locks the front door to new arrivals** (wraparound shutdown). And she can never clear a withdrawn edition early because one scholar dozing with an hours-old ticket (the pinned `OldestXmin`) might still ask for it.

## Recall questions

1. DELETE 9M of 10M rows, then plain VACUUM; file size barely changes. Why is that expected, what *did* VACUUM accomplish, and the two ways to actually shrink the file (with costs)?
2. "Autovacuum is clearly running (visible in `pg_stat_activity`) yet the table keeps bloating." Most likely root cause + exact mechanism (tie to `OldestXmin`), and two specific culprits.
3. What is XID wraparound, why is the comparison *circular*, and what does freezing concretely do? Name the parameter that forces an anti-wraparound vacuum even on an append-only table with autovacuum off.
4. How does each of the VM's two bits pay off — connect one to an earlier-topic feature and the other to making VACUUM cheaper.
5. In plain VACUUM the removed tuples' line pointers are only marked `LP_UNUSED`, not deleted. Why not actually remove them?

## Clarifications

### Confirmed answers (learner, 2026-06-17 — graded ~89%)

1. **VACUUM makes space reusable not OS-returned; FULL takes exclusive lock + new relfilenode. ✅ 4/5.** Fix: **HOT pruning doesn't "mark rows dead"** — DELETE/UPDATE *creates* the dead tuple (xmax commit + below OldestXmin); VACUUM/pruning *reclaim* it. File doesn't shrink because freed slots are **scattered, not trailing** (no all-empty trailing pages to truncate). The "other" shrink method = **`pg_repack`** (brief lock, rebuilds table+indexes; no outage).
2. **Long-open txn pins OldestXmin low → dead tuples not removable. ✅ 4.5/5.** Mechanism: removable needs `xmax < OldestXmin`; a pinned-low horizon fails the test so VACUUM reclaims nothing. Two more culprits: **orphaned replication slot** (`pg_replication_slots.xmin`) and **stuck prepared transaction** (`pg_prepared_xacts`). Debug: `pg_stat_activity` `backend_xmin`/`age(backend_xid)` → slots → prepared xacts.
3. **Limited 32-bit range; old history flips to future → invisible; freeze keeps it always-past; `autovacuum_freeze_max_age`. ✅ 4.5/5.** Sharpen: not an absolute crossing — **relative** `age = current_xid − xmin (mod 2³²)`; flips when the *gap* exceeds ~2³¹. Freeze stamps `FrozenTransactionId` (flag since 9.4) = older than every normal XID forever.
4. **all-visible → skip pages with nothing to delete + index-only scans skip heap. ✅ 4/5.** Both correct but for the **all-visible** bit; missed the distinct **all-frozen** bit → lets *aggressive/anti-wraparound* VACUUM skip already-frozen pages.
5. **Removing slots would shift live rows' ctids → force index updates. ✅ 5/5.** Precisely: offset numbers must stay stable; slots recycle in place as `LP_UNUSED`, keeping every index reference valid.

**Carry-forward into WAL:** VACUUM/freezing emit WAL too; checkpoints flush dirty pages (buffer pool ↔ WAL); full-page writes from [[heap-storage-layout]] are the next bridge.
