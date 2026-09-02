---
slug: write-ahead-log
title: Write-Ahead Log (WAL) — Crash Recovery & the Durability Guarantee
topic: databases
bloom-level: some
created: 2026-06-30
updated: 2026-06-30
published: 2026-06-30
related: [acid-properties, heap-storage-layout, mvcc, table-bloat-and-autovacuum, isolation-levels, buffer-pool]
tags: [wal, write-ahead-log, durability, crash-recovery, redo, lsn, pd_lsn, checkpoint, redo-point, full-page-write, backup-block, torn-page, synchronous-commit, wal-level, pitr, replication, replication-slot, group-commit, idempotent-recovery, interview-priority]
sources:
  - title: "PostgreSQL Documentation — Reliability and the Write-Ahead Log"
    url: "https://www.postgresql.org/docs/current/wal-intro.html"
  - title: "PostgreSQL Documentation — WAL Configuration"
    url: "https://www.postgresql.org/docs/current/wal-configuration.html"
  - title: "The Internals of PostgreSQL §9.1 — WAL / LSN"
    url: "https://www.interdb.jp/pg/pgsql09/01.html"
  - title: "The Internals of PostgreSQL §9.8 — Database Recovery"
    url: "https://www.interdb.jp/pg/pgsql09/08.html"
---

## Answer

Before any change touches a data page, Postgres first appends a description of it to an **append-only, sequentially-written log** and **flushes *that* to disk**. The data pages may lag indefinitely — after any crash, replaying the log reconstructs every change that hadn't reached them. The redo/durability *why* was introduced in [[acid-properties]] (redo powers Durability; WAL `fsync` happens at commit before the ack); this entry is the *how*. The whole system rests on one rule (PostgreSQL docs):

> *"Changes to data files must be written only after those changes have been logged, that is, after WAL records describing the changes have been flushed to permanent storage."*

**Log first, data later** — everything else is a consequence.

## Q: Why does log-first make commits FASTER, not slower?

You write twice, yet win, because **at commit only the WAL is `fsync`'d** — not the (many, scattered) data pages touched. Three multipliers:
1. **Sequential vs random:** WAL is one append-only file; data pages are random across heap/indexes. One sequential sync ≪ many random syncs.
2. **Deferred:** dirty data pages flush lazily (checkpoint + background writer), not at commit.
3. **Group commit:** one WAL `fsync` hardens many concurrent transactions' commit records at once (`commit_delay`/`commit_siblings`).

**Postgres-specific (extends [[acid-properties]] undo/redo):** Postgres WAL is **redo-only — there is no undo log.** Atomicity's "undo" is done by **MVCC + clog** ([[mvcc]]): `ROLLBACK` just flips the txn to `ABORTED` in the commit log; its tuples become invisible (dead) and get vacuumed. Rollback is cheap *because* undo is handled by MVCC, not the log.

## Q: LSN, pd_lsn, and WAL segment files?

Every WAL record has an **LSN (Log Sequence Number)** = its byte position in the logical WAL stream; LSNs only increase. Each **page's `pd_lsn`** ([[heap-storage-layout]]) = the LSN of the **last WAL record that modified that page** — the pairing that drives recovery. Physically, WAL lives in `pg_wal/` as **16 MB segment files**, recycled/removed once past the last checkpoint (and archived, if enabled). `pg_current_wal_lsn()` shows the write position.

## Q: Checkpoints — bounding recovery & freeing WAL?

A **checkpoint** flushes all currently-dirty data pages to disk and writes a checkpoint record, guaranteeing all changes logged before its **redo point** are now in the data files. Two problems solved: **recovery starts at the redo point** (bounded recovery time), and **WAL before it can be recycled** (`pg_wal` doesn't grow forever). Knobs trade *recovery speed & WAL retention* vs *steady-state I/O*:
- **`checkpoint_timeout`** (5 min) — time trigger.
- **`max_wal_size`** (1 GB) — size trigger.
- **`checkpoint_completion_target`** (0.9) — spread the flush across ~90% of the interval to smooth I/O.

## Q: Crash recovery — replay, idempotency, full-page writes?

On unclean startup (per `pg_control`): find the **redo point** → replay WAL forward → for each record compare its LSN to the page's `pd_lsn`:
- record LSN **>** `pd_lsn` → change hadn't reached the page → **apply**, set `pd_lsn`.
- record LSN **≤** `pd_lsn` → already there → **skip**.

That makes replay **idempotent** (safe to crash mid-recovery and re-run). **Full-page writes / backup blocks** ([[heap-storage-layout]] torn-page defense): the **first modification of a page after each checkpoint** writes the **whole page image** into WAL; during recovery these are applied **unconditionally — overwriting the page regardless of `pd_lsn`** (a torn page's `pd_lsn` is untrustworthy; stamping a whole image is idempotent by construction). This is why **WAL volume spikes right after each checkpoint**, and why more frequent checkpoints inflate WAL.

## Q: The configuration knobs that matter?

- **`synchronous_commit`** — durability/latency dial. `on` (default): commit waits for WAL `fsync` → zero committed-data loss. `off`: returns before the flush → faster, but a crash loses the **last fraction of a second of commits** — **never corrupts** (consistent to a slightly-earlier point). Async moves the *durability boundary* into the past; it does **not** relax the write-ahead ordering, so you lose a consistent *suffix*, never a partial/corrupt transaction.
- **`wal_level`** — `minimal` (crash recovery only) / `replica` (default; archiving, streaming replication, PITR) / `logical` (+ logical decoding).
- **`full_page_writes`** (on) — the torn-page defense; off only safe on storage guaranteeing atomic 8 KB writes.
- **WAL writer** + **`wal_buffers`** — records land in an in-memory ring, flushed in the background so foreground txns don't stall.

## Q: Beyond crash recovery — PITR & replication?

The same log is a change feed. **PITR:** archive each completed segment (`archive_command`); base backup + WAL replay restores to **any point in time** ("3 seconds before the bad DELETE"). **Replication:** a standby streams + replays the primary's WAL to stay in near-real-time sync; `wal_level=logical` adds row-level logical replication.

## Mental model

WAL is a **notary's append-only journal** in front of the ledger. Before a clerk edits the ledger (a data page), they write the intended change in the journal and **wait for the ink to dry** (`fsync`) — only then tell the customer "done" (commit ack). Ledger pages update lazily. If the office burns (crash), fetch the surviving ledger, find the last **"books balanced & photographed" stamp** (redo point), and **replay every journal entry after it** — checking each page's "last-updated" mark (`pd_lsn`) to skip ones already reflected (idempotent). Because a page can be **smudged mid-write** (torn page), the *first* touch after a stamp **photocopies the whole page into the journal** (full-page write), pasted over wholesale during recovery. Writing the journal is one fast sequential motion; editing ledger pages is slow flipping-all-over-the-book — so the bank commits thousands/sec by making the customer wait only for the journal, and never loses a confirmed transaction.

## Recall questions

1. State the write-ahead rule, then the **performance** payoff: why does logging first make commit *faster*? Two distinct reasons.
2. Recovery replays a record only if record LSN **>** page `pd_lsn`. What does this accomplish + why idempotent? Why are full-page-write records applied differently, and what hazard does that defend?
3. A checkpoint and a commit both `fsync` — on what, and for what reason, respectively? What is the redo point and the two problems checkpoints solve?
4. `synchronous_commit=off` for high-volume ingestion: what risk is accepted, what is **not** sacrificed, and why is that distinction safe?
5. WAL is redo-only — no undo log. What happens mechanically on `ROLLBACK`? Tie to MVCC + clog, and contrast with an undo-log system.

## Clarifications

### Confirmed answers (learner, 2026-06-30 — graded ~92%)

1. **Sequential append vs random heap writes; data pages flush lazily. ✅ 4.5/5.** Precise reason 2: at commit you `fsync` **only the WAL** (one sequential sync), not the N scattered data pages. Third multiplier: **group commit** — one WAL `fsync` hardens many txns' commit records.
2. **record LSN > pd_lsn → apply, else skip; idempotent; torn page (8KB=2 sectors) → full-page image. ✅ 4.5/5.** Make explicit: **backup blocks apply *unconditionally*, regardless of `pd_lsn`** — a torn page's `pd_lsn` is untrustworthy, and pasting a whole image is idempotent.
3. **Checkpoint fsyncs dirty data pages; commit fsyncs WAL; redo point bounds recovery + lets old WAL recycle. ✅ 5/5.** Redo point = WAL position at checkpoint start; everything before it is guaranteed in the data files.
4. **Risk = lose last sliver of committed txns; integrity unknown — taught. ✅ 4/5 → closed.** No corruption because: (a) WAL records are written/replayed in LSN order, atomically → recovery gets a **consistent prefix**; (b) incomplete txns roll back → every recovered txn is whole; (c) **async only delays the commit flush — it never relaxes write-ahead ordering**, so a data page never outruns its WAL. Net: durability boundary moves into the past; consistency *at* that boundary holds. Lost suffix, never corruption.
5. **Flip clog to ABORTED, VACUUM reaps later; undo-log system physically reverses. ✅ 5/5.** Tie: clog records `ABORTED`; MVCC visibility Rule 1 (aborted `xmin` → invisible to everyone, *instantly*) makes rollback logically immediate; cleanup deferred to VACUUM. Postgres flips the cost — cheap rollback, pay later in VACUUM; undo-log systems make *rollback* the expensive path (restore before-images).

**Carry-forward into Buffer pool:** checkpoints flush *dirty buffers* from the pool; the WAL-before-data rule is enforced at buffer eviction (a dirty page can't be written until its WAL is flushed); replication slots/failed archiving pin WAL in `pg_wal` (slots also pin `xmin` → bloat, from [[table-bloat-and-autovacuum]]).
