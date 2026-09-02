---
slug: heap-storage-layout
title: How Data Is Stored on Disk — Heap Files, Pages & Slots
topic: databases
bloom-level: some
created: 2026-06-17
updated: 2026-09-01
published: 2026-06-30
related: [covering-indexes, acid-properties, isolation-levels, two-phase-locking, mvcc, table-bloat-and-autovacuum, write-ahead-log, buffer-pool, window-functions, join-algorithms, explain-analyze]
tags: [storage, heap-file, page, block, 8kb-page, line-pointer, slot, item-pointer, tuple, ctid, tid, relfilenode, fork, free-space-map, visibility-map, toast, segment, torn-page, full-page-write, indirection, interview-priority]
sources:
  - title: "PostgreSQL Documentation — Database Page Layout"
    url: "https://www.postgresql.org/docs/current/storage-page-layout.html"
  - title: "PostgreSQL Documentation — Database File Layout"
    url: "https://www.postgresql.org/docs/current/storage-file-layout.html"
  - title: "The Internals of PostgreSQL §1.3 — Internal layout of a heap table file"
    url: "https://www.interdb.jp/pg/pgsql01/03.html"
---

## Answer

A PostgreSQL table is just a **heap file** on disk ("heap" = an unordered pile of rows, *not* a binary heap) cut into fixed **8 KB pages**, and inside each page rows are found indirectly through a small array of **line pointers** (a.k.a. *slots* / item identifiers). That one layer of indirection — an index/`ctid` points at a **slot number**, the slot points at the tuple's current **byte offset** — is the keystone that makes in-page compaction, HOT updates, MVCC, and VACUUM possible. This is the foundation of the whole Storage Internals block.

A row's physical address is a **TID** `(block number, offset number)`, also exposed as the system column `ctid`:
```sql
SELECT ctid, * FROM accounts WHERE id = 7;   --  ctid = (block, slot), e.g. (0,3)
SELECT pg_relation_filepath('accounts');     --  base/<db-oid>/<relfilenode>
```

## Q: From a table to files on disk?

`CREATE TABLE` makes a heap file at `base/<database-oid>/<relfilenode>`. Three backend-relevant facts:

1. **`relfilenode` ≠ table OID (necessarily).** The file is named by `relfilenode`, which often equals the OID but **diverges after a *rewrite*** — `TRUNCATE`, `CLUSTER`, `VACUUM FULL`, `REINDEX`, table-rewriting `ALTER TABLE`. These build a **new file and atomically swap** the table's pointer to it. This is *why* `TRUNCATE` is fast (O(1) in rows, no per-row scan, no per-row WAL, no dead tuples) yet still fully transactional (the swap is one atomic catalog change; `ROLLBACK` works).
2. **1 GB segmentation.** A relation file is capped at 1 GB; beyond that, segments are added: `67890`, `67890.1`, `67890.2`, … (dodges historical filesystem size limits).
3. **Forks** — one table = several files sharing the base name:
   - `<relfilenode>` — **main fork** (the rows)
   - `<relfilenode>_fsm` — **Free Space Map** (which pages have room — used to place new tuples)
   - `<relfilenode>_vm` — **Visibility Map** (which pages are all-visible — the file [[covering-indexes]] index-only scans and VACUUM lean on)
   - `<relfilenode>_init` — **init fork** (unlogged tables only)

**TOAST** (The Oversized-Attribute Storage Technique): a row whose width would exceed ~2 KB (¼ page) gets wide `text`/`jsonb`/`bytea` values compressed and/or pushed **out-of-line** into a companion TOAST table (`pg_class.reltoastrelid`), fetched only when that column is read.

## Q: The layout of one 8 KB page?

The page is the **atomic unit of heap I/O** — Postgres reads/writes a whole 8 KB block, never a fraction. Four regions, two of which **grow toward each other from opposite ends**:

```
 ┌───────────────────────────────┐ byte 0
 │ PageHeaderData      (24 bytes) │  fixed header
 ├───────────────────────────────┤
 │ line pointers (4 B each) ──▶   │  grow DOWN, end marked by pd_lower
 ├───────────────────────────────┤
 │      free space ("the hole")   │
 ├───────────────────────────────┤
 │   ◀── tuples (heap rows)       │  grow UP, start marked by pd_upper
 ├───────────────────────────────┤
 │ special space (empty for heap; │  B-tree pages put sibling links here
 └───────────────────────────────┘ byte 8191
```

PageHeaderData fields that matter: **`pd_lsn`** (LSN of the last WAL record to touch this page — the link between a page and the WAL, used in recovery), **`pd_lower`** (end of line-pointer array = start of free space), **`pd_upper`** (start of tuple data = end of free space), `pd_special`, `pd_checksum`, `pd_prune_xid`. Free space = `pd_upper − pd_lower`; when it hits zero the page is full and the FSM picks another page.

## Q: Line pointers (slots), TID, and why the indirection?

A **line pointer** (`ItemIdData`, 4 bytes) holds `(byte offset within page, length, flags)`. Line pointers form an array numbered from **1** — that index is the **offset number** (the *slot*). A row is addressed by **TID = (block number, offset number)** — never by raw byte position.

Reading a row = go to block *N* → look up slot #*K* → follow its offset to the tuple. **One level of indirection**, and it exists because the **slot number is stable** while the tuple's **byte offset is not**:

- **Compaction:** VACUUM slides surviving tuples together to coalesce the hole. Tuples move; each line pointer is **rewritten to the new offset** — but the **offset numbers stay the same**, so every index entry and `ctid` citing `(N, K)` is still valid.
- If indexes stored the **byte offset directly**, every in-page compaction/prune would have to **find and rewrite every index entry** across *all* indexes on the table (write amplification), and you'd need a nonexistent **reverse map from tuple → indexes**.
- Line pointers also carry states `LP_NORMAL` / `LP_DEAD` / `LP_UNUSED` / `LP_REDIRECT` (redirect → another slot) — the machinery behind HOT chains and pruning (cashed in under MVCC).

**The rule to name: the line pointer is an *indirection layer* decoupling a row's logical address (slot) from its physical address (bytes).** Indexes point at the slot, not the bytes.

## Q: The heap tuple header (preview)?

Each row is a **heap tuple**: ~23-byte header, optional null bitmap, then user data aligned at `t_hoff`. Header fields (dissected fully under MVCC):
- `t_xmin` (4 B) — inserting txn XID
- `t_xmax` (4 B) — deleting/locking txn XID
- `t_cid` / `t_xvac` (4 B, overlaid) — command id
- `t_ctid` (6 B) — TID of this tuple **or of the next, newer version** (forward pointer chaining an UPDATE to its successor)
- `t_infomask2`, `t_infomask` (2 B each) — flags incl. `HEAP_HASNULL`; also cache commit-status **hint bits**
- `t_hoff` (1 B) — offset to user data (MAXALIGN'd)

Headline: **a tuple stores `xmin`/`xmax` and a `ctid` forward pointer in its own on-page header** — that's why row *versions* live physically in the heap, and why DELETE/UPDATE don't free space immediately.

## Q: Pages vs sectors vs files — the torn-page hazard?

Each layer has its own "smallest atom," and they don't match:
```
relation → segment file (1 GB) → Postgres PAGE (8 KB, the DB's atom)
        → filesystem block (~4 KB) → device SECTOR (512 B or 4 KB, the hardware's atom)
```
One 8 KB page = **16 sectors** (512 B) or **2 sectors** (4 KB). The disk only guarantees **one sector** is written all-or-nothing. So a crash mid-write can persist some sectors of the new page and leave others as the old page's bytes → a **torn page** (partial-page write): a single page that's part-new, part-old = corruption.

**Defense — full-page writes (FPW):** the **first** modification of a page **after a checkpoint** copies the **entire 8 KB page into the WAL** before the page may go to disk. On recovery, that known-good full image is stamped back down wholesale, *then* later changes replay on top — so a torn on-disk page can never survive. This is **why WAL is bigger than expected** (`full_page_writes`, on by default) and why the **page**, not the row, is the unit of crash protection. (Bridge into the WAL topic.)

## Mental model

A heap file is a **filing cabinet**; each **page** is one fixed-size **drawer**. Taped to the inside of the drawer face is an **index card array** — the line pointers; card slot #3 says "folder #3 is 4 inches from the back." **Folders (tuples)** pack from the **back** forward; **cards** are added from the **front**; they grow toward each other until full. You cite **(drawer, card slot)** — the TID — never inches-from-the-back, because folders shuffle forward when old ones are cleaned out (VACUUM compaction) but the **slot number never changes**, so cross-references elsewhere in the office (the indexes) stay valid. Updating a document files a **new folder** and marks the old "superseded as of <date>" (`xmax`); a janitor (VACUUM) later tosses superseded folders and re-packs the drawer.

## Recall questions

1. A table's file is named by `relfilenode`, not its OID. Name an operation that changes `relfilenode` and explain why that makes it behave as it does (what `TRUNCATE` gets to skip).
2. Line pointers grow down, tuples grow up. Why is the slot indirection worth it — what breaks/gets expensive if indexes pointed at a tuple's byte offset instead of its slot number?
3. `ctid`/TID is `(block, offset number)`. Why is `ctid` unsafe as a persistent row id — give the two distinct situations that change a row's TID.
4. `UPDATE ... WHERE id = 7`: describe what physically happens to the old and new versions, which header fields are involved, and why space isn't reclaimed immediately.
5. Postgres does heap I/O one 8 KB page at a time though a sector is much smaller. Name the correctness hazard on a crash and the mechanism that defends against it.

## Clarifications

### Confirmed answers (learner, 2026-06-17 — graded ~96%)

1. **`TRUNCATE` creates new empty files and swaps the pointer; that's why it's fast. ✅ 5/5.** Precision: fast because O(1) in rows — no per-row scan, no per-row WAL, no dead tuples (vs `DELETE` O(n)); still transactional (atomic catalog swap, `ROLLBACK` works). Other rewrite ops: `CLUSTER`, `VACUUM FULL`, `REINDEX`, type-changing `ALTER TABLE`. **Rule: these are "rewrite" ops — new file + atomic swap, not in-place edit.**
2. **Slot number is stable; in-page byte moves don't propagate to indexes; indexes store slot positions. ✅ 4.5/5 (right idea, sharpen wording).** Precise framing: the **TID `(block, offset)` is stable across in-page moves**; the byte offset is *not* (compaction slides tuples) — the line pointer is rewritten to the new offset. Direct byte-offset indexing would force rewriting **every index entry across all indexes** on each compaction (write amplification) and need a nonexistent **tuple→index reverse map**. **Rule: indirection layer = logical slot vs physical bytes.**
3. **UPDATE (new version = new TID) and VACUUM FULL/CLUSTER (physical rewrite relocates tuples). ✅ 5/5.** Nuance: on UPDATE the row didn't "move" — a *new version* was written elsewhere. And **ordinary lazy VACUUM does *not* change a live tuple's TID** — only the rewrite ops (VACUUM FULL/CLUSTER) move live tuples across pages.
4. **Old version's `xmax` set, new version inserted; space not freed until VACUUM. ✅ 5/5.** Adds: old tuple's `t_ctid` also set to point at the new version (forward pointer / version chain); new tuple `xmin` = updating txn, `xmax` = 0. Precise reason for deferral: the old version **may still be visible to transactions whose snapshot predates the update** (MVCC) — it's *dead* only when no snapshot can see it. Preview: if no indexed column changed and the page has room → **HOT update** (new version same page, no new index entry).
5. **Knowledge gap — now closed.** Layering: relation → 1 GB segment file → 8 KB Postgres page (DB atom) → filesystem block → device sector (512 B/4 KB, hardware atom). A page spans many sectors; the disk is only atomic per sector, so a crash mid-write yields a **torn page** (part-new/part-old = corruption). Defense: **full-page writes** — first post-checkpoint modification copies the whole 8 KB page into WAL; recovery stamps the good image back wholesale. This is why WAL is large and why the **page** is the unit of crash protection.

**Carry-forward into MVCC:** the tuple header (`xmin`/`xmax`/`t_ctid`/`t_infomask` hint bits) lives physically on the page; UPDATE = new version + `xmax` stamp + `ctid` forward pointer; dead tuples and the visibility map are the bridge to bloat/VACUUM; full-page writes bridge to WAL.
