---
slug: mvcc
title: MVCC — How Postgres Implements Multi-Version Concurrency Control
topic: databases
bloom-level: some
created: 2026-06-17
updated: 2026-08-24
published: 2026-06-30
related: [heap-storage-layout, covering-indexes, isolation-levels, two-phase-locking, acid-properties, table-bloat-and-autovacuum, write-ahead-log, buffer-pool, select-for-update-skip-locked, optimistic-vs-pessimistic-locking, sql-fundamentals]
tags: [mvcc, multi-version, xmin, xmax, cmin, cmax, t_ctid, version-chain, snapshot, xip-list, visibility-check, commit-log, clog, pg_xact, hint-bits, t_infomask, hot-update, heap-only-tuple, lp-redirect, dead-tuple, oldest-xmin, xmin-horizon, snapshot-isolation, interview-priority]
sources:
  - title: "PostgreSQL Documentation — Introduction to MVCC"
    url: "https://www.postgresql.org/docs/current/mvcc-intro.html"
  - title: "The Internals of PostgreSQL §5.2 — Tuple Structure"
    url: "https://www.interdb.jp/pg/pgsql05/02.html"
  - title: "The Internals of PostgreSQL §5.4 — Commit Log (clog)"
    url: "https://www.interdb.jp/pg/pgsql05/04.html"
  - title: "The Internals of PostgreSQL §5.5 — Transaction Snapshot"
    url: "https://www.interdb.jp/pg/pgsql05/05.html"
  - title: "The Internals of PostgreSQL §5.6 — Visibility Check Rules"
    url: "https://www.interdb.jp/pg/pgsql05/06.html"
  - title: "The Internals of PostgreSQL §7.1 — Heap-Only Tuples (HOT)"
    url: "https://www.interdb.jp/pg/pgsql07/01.html"
---

## Answer

Instead of locking a row so readers and writers take turns, Postgres keeps **multiple physical versions of every row** on the heap, each stamped with the transaction IDs that created and destroyed it (`xmin`/`xmax`). A transaction carries a **snapshot** — a frozen notion of "who had committed when I started" — and at read time walks the version chain showing exactly the version its snapshot may see. Hence the headline: **reading never blocks writing and writing never blocks reading** ([[two-phase-locking]] adds: MVCC removes *read* locks, not the write-write X lock). Multi-version rows / readers-don't-block-writers were introduced in [[covering-indexes]]; snapshot *timing* in [[isolation-levels]]; this entry assembles the full machine.

```sql
SELECT ctid, xmin, xmax, * FROM accounts WHERE id = 7;  -- inspect the version stamps
SELECT pg_current_snapshot();                            -- 100:104:100,102  (xmin:xmax:xip_list)
```

## Q: The version IS the tuple — header fields & lifecycle?

Every heap tuple ([[heap-storage-layout]]) carries MVCC bookkeeping physically on the page:

| Field | Holds |
|---|---|
| `t_xmin` | txid that **inserted** this version ("born at") |
| `t_xmax` | txid that **deleted/updated** it ("died at"); `0` = still live |
| `t_cid` | **command id** — overlay of `cmin` (insert cmd) and `cmax` (delete cmd); disambiguates visibility across commands *within one transaction* |
| `t_ctid` | TID pointing to **itself** or to the **newer version** (the version-chain forward link) |
| `t_infomask` | flags incl. cached commit-status **hint bits** |

Lifecycle — the whole of write DML at storage level:
- **INSERT** → `xmin =` my txid, `xmax = 0`, `ctid →` self.
- **DELETE** → target's `xmax =` my txid. **Bytes stay** — only a "died at" stamp is written.
- **UPDATE = DELETE + INSERT atomically** → old version: `xmax =` my txid **and `t_ctid` → new version**; new version: `xmin =` my txid, `xmax = 0`. Never edits in place — the seed of bloat.

```
row id=7:  (0,1) xmin=100 xmax=104 ctid→(0,2)     ← superseded by txn 104
           (0,2) xmin=104 xmax=0   ctid→(0,2)     ← current version
```

## Q: The snapshot — xmin:xmax:xip_list?

A transaction reads against a **snapshot**, not "latest":
- **`xmin`** — lowest txid **still active**; everything below is resolved (committed-done or aborted).
- **`xmax`** — first **not-yet-assigned** txid; everything `≥ xmax` started after the snapshot → **invisible**.
- **`xip_list`** — txids **in progress** at snapshot time (between xmin and xmax).

`100:104:100,102` = "100 and 102 in flight; 101,103 done; 104+ don't exist to me." **Crucial:** a txid in `xip_list` is treated as in-progress for the snapshot's *entire life*, even if it commits a microsecond later — that frozen world *is* Snapshot Isolation.

This is the *only* difference between isolation levels ([[isolation-levels]]): **READ COMMITTED** takes a **fresh snapshot per statement**; **REPEATABLE READ / SERIALIZABLE** take **one snapshot at the first statement**. Same engine, different snapshot timing.

## Q: The visibility check?

For each version, given my snapshot: **visible iff (A) `xmin` is committed-and-visible-to-me AND (B) no `xmax` that is committed-and-visible-to-me deleted it.** "Committed-and-visible-to-me" for a txid:
1. **aborted** (per clog) → never happened.
2. **≥ snapshot `xmax`** or **in `xip_list`** → treated as **in progress** → not visible.
3. otherwise (committed before snapshot, not in flight) → **committed & visible**.

Plus self-rules via `t_cid` (see my own earlier-command inserts, not my current command's effects).

Worked: tuple `xmin=100,xmax=104`, snapshot `100:104:100,102` → 100 is in `xip_list` → insert not visible → **tuple invisible**. Same tuple, snapshot `105:110:` → 100 & 104 both committed-before → deleter visible → **invisible, follow `ctid` to newer version**.

Commit status comes from the **Commit Log (clog / `pg_xact`)** — a shared-memory array indexed by txid storing `IN_PROGRESS` / `COMMITTED` / `ABORTED`.

## Q: Hint bits — why a read can write to disk?

Hitting the clog for every tuple on every read is expensive, so the first time a tuple's commit status is resolved, Postgres caches it in `t_infomask`: `HEAP_XMIN_COMMITTED` / `HEAP_XMIN_INVALID` / `HEAP_XMAX_COMMITTED` / `HEAP_XMAX_INVALID`. Next reader sees the bit, skips the clog.

**Gotcha:** setting a hint bit **modifies the page → marks it dirty → it gets flushed.** So a plain `SELECT` right after a bulk `COPY` resolves thousands of tuples against the clog, stamps hint bits, dirties pages, and triggers writebacks — **a read causing writes & I/O.** First query slow, later ones fast.

## Q: HOT updates — dodging index write-amplification?

Naively, a new version at a new TID forces **every index** to add an entry — even indexes on unchanged columns (6 indexes → 6 writes per updated row). **HOT (Heap-Only Tuple)** avoids it when **both**:
1. **no indexed column changed**, and
2. the new version **fits on the same page**.

Then: old line pointer becomes `LP_REDIRECT` → new tuple's slot; old tuple flagged `HEAP_HOT_UPDATED`, new flagged `HEAP_ONLY_TUPLE`; **no new index entry** — the index keeps pointing at the original slot, which redirects to the current version. The slot-indirection layer from [[heap-storage-layout]] doing exactly its job.

```
index ──▶ slot (0,1)[LP_REDIRECT] ──▶ slot (0,2) HEAP_ONLY  (current)
```
HOT also enables **pruning**: ordinary SELECT/UPDATE/INSERT can remove dead versions and collapse redirects **within a page, touching no index** — reclaiming space between VACUUMs.

## Q: Why does one idle transaction bloat the whole DB? (the xmin horizon)

VACUUM does **not** use the per-snapshot visibility check; it uses a stricter **global** test. It computes a cluster-wide **xmin horizon** (`OldestXmin`) = the **smallest `xmin` across every active transaction**. A dead tuple is reclaimable only if its `xmax` is committed **and** `xmax < OldestXmin` — i.e. older than the oldest surviving snapshot, so no one can see the pre-delete version.

An idle-in-transaction connection pins a **low `xmin`**, dragging `OldestXmin` down for hours. Every version deleted after that txn began is now unreclaimable — **across unrelated tables**, because the horizon is global. One forgotten `BEGIN` → unbounded, DB-wide bloat. Hence `idle_in_transaction_session_timeout`. (Bridge to bloat/autovacuum.)

## Mental model

MVCC is a **ledger you never erase**, plus a **time-stamped reading glass**. Every change is a new line stamped "**valid from** txn X" and, when superseded, "**valid until** txn Y," with an arrow to its replacement. A "delete" just writes the until-stamp. Each transaction holds a **reading glass frozen to one instant** (the snapshot): it reads only lines whose `[from, until)` window contains its instant, and treats anyone mid-write at that instant as if their ink never dried — invisible forever, for this glass. Two readers at different frozen instants see different "current" lines and never wait on each other. A **status board** (clog) says which scribes finished; once checked, you pin a sticky note (hint bit) so nobody re-checks. A janitor (VACUUM) tears out lines no living glass can reach — but cannot tear anything inside the oldest active reader's window, which is why one dozing reader jams all cleanup.

## Recall questions

1. UPDATE = "delete + insert." Name every header field that changes on the old and new versions, and explain how a concurrent transaction with an older snapshot still finds the old version.
2. Snapshot `150:155:150,153`; tuple `xmin=152, xmax=0`; txn 152 already committed in wall-clock. Visible? Walk it, and name the property.
3. A read-only SELECT right after a bulk load causes disk writes. Explain the mechanism — what is written, why, and the clog's role.
4. Table has indexes on `email`, `created_at`, `status`. `UPDATE users SET last_seen=now() WHERE id=7` (no index on `last_seen`). HOT-eligible? What happens to line pointers and index entries, and why does it matter for write amplification?
5. An idle `BEGIN` is held open for hours. Why does this block VACUUM from reclaiming dead tuples elsewhere in the DB? Tie it to `xmin`.

## Clarifications

### Confirmed answers (learner, 2026-06-17 — graded ~93%)

1. **Old → `xmax` + `ctid`; new → `xmin` + `ctid`. ✅ 4.5/5.** Sharpen the "why finds old version": not merely "still on disk" — the **updating txn is *not visible* to the reader's snapshot** (in `xip_list`, `≥ xmax`, or aborted), so the old tuple's `xmax` "doesn't count" and the version stays visible. Enrichment: `t_cid` is an overlay of **`cmin`/`cmax`**.
2. **Visible — 152 not in `xip_list`, `< xmax`, `xmax=0`. ✅ 4.5/5.** Name precisely: **visibility is decided by snapshot membership, not wall-clock commit time** (umbrella = Snapshot Isolation). Mirror case: a txid that *was* in `xip_list` but has since committed stays invisible the whole snapshot life — same principle, opposite outcome.
3. **Hint bits cache commit status to avoid re-hitting clog. ✅ 4/5 (missed the write link).** The "why disk writes": **setting a hint bit modifies the heap page → marks it dirty → it's flushed.** What's written = heap pages carrying the new `HEAP_XMIN_COMMITTED`/`HEAP_XMAX_COMMITTED` bits; first reader resolves status against clog once, stamps, dirties, writeback. **A hint-bit read is a storage-layer write.**
4. **Same-page → old slot redirects to newer version's slot; index unchanged. ✅ 4.5/5.** Add the **second condition** (no indexed column changed — satisfied because `last_seen` is unindexed) and the count: without HOT, all **3 indexes** get a new entry though unchanged → 3 wasted writes + bloat; HOT → **0 index writes** via `LP_REDIRECT`.
5. **Deferred; intuition correct — VACUUM uses a stricter-than-per-snapshot test. ✅ (taught).** Mechanism: cluster-wide **xmin horizon (`OldestXmin`)** = smallest `xmin` across all active txns; a dead tuple is reclaimable only if `xmax` committed **and** `xmax < OldestXmin`. An idle txn pins a low `xmin`, dragging the global horizon down → versions deleted after it began are unreclaimable **across unrelated tables**. Hence `idle_in_transaction_session_timeout`.

**Carry-forward into bloat/autovacuum:** dead tuples (un-erased old versions) + the **`OldestXmin` horizon** are the bloat story; HOT pruning and the visibility map are partial reclamation; freezing defends the 32-bit txid wraparound.
