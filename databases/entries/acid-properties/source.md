---
slug: acid-properties
title: ACID Properties
topic: databases
bloom-level: some
created: 2026-06-10
updated: 2026-06-30
published: 2026-06-15
related: [covering-indexes, relational-data-model, denormalization, isolation-levels, two-phase-locking, heap-storage-layout, write-ahead-log]
tags: [transactions, acid, atomicity, consistency, isolation, durability, wal, write-ahead-log, mvcc, savepoint, commit, rollback, serializability, interview-priority]
sources:
  - title: "Wikipedia — ACID"
    url: "https://en.wikipedia.org/wiki/ACID"
  - title: "PostgreSQL Documentation — Transactions (tutorial)"
    url: "https://www.postgresql.org/docs/current/tutorial-transactions.html"
---

## Answer

**ACID** is the set of four guarantees a *transaction* (a bundle of operations treated as one logical unit) upholds so that concurrency and crashes can't leave data half-finished or corrupt: **A**tomicity, **C**onsistency, **I**solation, **D**urability. The acronym was coined in 1983 by Härder & Reuter, formalizing Jim Gray's 1981 "transaction concept" (Gray named A, C, D — not isolation).

The canonical example is a bank transfer — two writes that must behave as one:

```sql
BEGIN;
UPDATE accounts SET balance = balance - 100 WHERE name = 'Alice';
UPDATE accounts SET balance = balance + 100 WHERE name = 'Bob';
COMMIT;
```

The key framing most people miss: **the four letters are not peers.** A, I, and D are machinery the *database* provides. **C is mostly the application's job** — the DB only enforces the invariants you *declare*. I is a tunable dial (the isolation-levels topic).

## Q: What is Atomicity and how is it implemented?

All-or-nothing: *"if any of the statements constituting a transaction fails to complete, the entire transaction fails and the database is left unchanged"* (Wikipedia). Postgres: *"from the point of view of other transactions, it either happens completely or not at all."* The unit is the **transaction**, not the statement.

**Mechanism — the Write-Ahead Log (WAL), undo direction.** Before any change touches the data pages, the intended change is appended to a durable log. On `ROLLBACK` or a crash mid-transaction, the engine **undoes** uncommitted changes using the log — it knows what to reverse because it recorded its intentions first. (Alternative: *shadow paging* — write to a copy, atomically swap a pointer at commit. WAL is what Postgres / InnoDB use.)

**Savepoints** give partial rollback — a nested checkpoint inside a transaction:

```sql
BEGIN;
UPDATE accounts SET balance = balance - 100 WHERE name = 'Alice';
SAVEPOINT sp;
UPDATE accounts SET balance = balance + 100 WHERE name = 'Bob';
ROLLBACK TO sp;     -- undo only Bob's line; Alice's debit still pending
UPDATE accounts SET balance = balance + 100 WHERE name = 'Wally';
COMMIT;
```

**Backend connection:** every ORM transaction block (`db.transaction(...)`, `@Transactional`, `BEGIN…COMMIT`) is buying atomicity. The classic bug is doing two related writes *without* a transaction — the request dies between them and leaves an orphaned row.

## Q: What does Consistency actually mean? (the odd one out)

*"A transaction can only bring the database from one consistent state to another, preserving database invariants: any data written must be valid according to all defined rules, including constraints, cascades, triggers"* (Wikipedia). The DB rejects and rolls back any transaction that would violate a **declared** rule (`CHECK`, `NOT NULL`, `FOREIGN KEY`, `UNIQUE`, a trigger).

The critical nuance and #1 interview trap: **C is only as strong as the invariants you declare.** If your transfer debits Alice but skips crediting Bob, the DB is still perfectly "consistent" — money vanished, but no *declared* constraint was broken, so it commits. The DB didn't fail at C; "money is conserved" was an invariant *you never gave it to enforce*. This is why C is called the application's responsibility, and why researchers (Hellerstein and others) argue C "doesn't really belong" in ACID — A, I, D are mechanisms; C is the DB *checking the homework you handed it.*

## Q: What is Isolation, briefly? (full treatment = isolation-levels topic)

*"Concurrent execution of transactions leaves the database in the same state that would have been obtained if the transactions were executed sequentially"* (Wikipedia) — the gold standard, **serializability**. Postgres: *"the updates made so far by an open transaction are invisible to other transactions until the transaction completes, whereupon all the updates become visible simultaneously."* Isolation is *"the main goal of concurrency control."*

But full serializability is expensive, so isolation is a **spectrum of levels** (Read Uncommitted → Serializable), each preventing more anomalies at more cost. Equating "isolation" with "no dirty reads" is wrong — that's just the lowest bar; weaker levels deliberately *allow* some anomalies for speed.

**Two implementation families:** (1) **Locking / 2PL** (pessimistic) — lock touched data, others wait; (2) **MVCC** (optimistic, Postgres) — multiple row versions, each transaction sees the version valid at its start; readers don't block writers and vice versa (see [[covering-indexes]] — this is the same MVCC that forces the visibility-map check).

**Interview gold:** Postgres diverges from the ANSI standard — request "Read Uncommitted" and you get Read Committed (MVCC makes dirty reads impossible), and its Serializable uses **SSI (Serializable Snapshot Isolation)**, not locking.

## Q: What is Durability and where exactly is the data safe?

*"Once a transaction has been committed, it will remain committed even in the case of a system failure"* (Wikipedia). The durability line is the **`COMMIT` acknowledgment** — before it, no promise; after it, ironclad.

**Mechanism — WAL, redo direction.** At commit, the engine **`fsync`s the WAL records to physical disk *before* acknowledging** success. The actual data pages flush lazily later; if a crash happens, restart **replays** the WAL to **redo** committed changes that hadn't reached the data files. So one log powers both A (undo uncommitted) and D (redo committed) — that's why it's *write-ahead*: the log precedes the data pages and is the source of truth for recovery.

**Crucial nuance:** durability means *survives crash*, not *written into the table*. Right after commit a row may live *only* in the WAL on disk, not yet in the heap — and that's fine, the log is durable. What is "not yet on disk" is the **heap copy, never the log**. Durability is only as strong as storage honoring `fsync` (`fsync=off` or lying disk controllers break it), and single-node durability ≠ surviving disk destruction — that needs replication.

## Mental model

A transaction is a **wedding ceremony**:

- **Atomicity** — "I now pronounce you married" is all-or-nothing; nobody ends up half-married. The whole ceremony completes or it's called off and everyone leaves unchanged.
- **Consistency** — the officiant checks the *legal requirements on the books* (consent, age, valid license) and refuses if a declared rule is broken — but won't stop a marriage you'll *regret*. He enforces only the rules you brought, not whether it's a good idea.
- **Isolation** — two weddings in adjacent halls don't bleed into each other; each runs as if it were the only one.
- **Durability** — once signed and filed at the registry, it's official forever; the registry copy survives even if the venue burns down that night. The *filing* is the commit.

The asymmetry: the officiant owns A, I, D (the ceremony machinery); **C is on you** — he only enforces the rules you hand him.

## Recall questions

1. A transfer debits Alice $100 but a bug skips crediting Bob; it commits with no error. Which ACID property is at stake, and why is the answer surprising?
2. Explain how the single WAL mechanism delivers both Atomicity and Durability — name the direction (undo/redo) for each.
3. Correct: "Postgres durability means after COMMIT my row is safely written into the table's data file."
4. In Postgres, where does Isolation come from, and why does that same mechanism explain why an index-only scan sometimes still touches the heap?
5. Why do researchers argue "C" doesn't belong in ACID? Contrast what the DB guarantees for C vs. A, I, D.

## Clarifications

### Confirmed answers (learner, 2026-06-10 — graded ~94%)

1. **C violated. ✅ 5/5.** No declared constraint broken yet not transitioning between *logically* consistent states. Refinement given: C is only as strong as the invariants you *declare* — "money conserved" was never expressed as a constraint, so the DB had nothing to enforce. The DB didn't fail C; C was never given to it. → C is the application's job.
2. **WAL: A = backward/undo, D = forward/redo. ✅ 5/5.** Refinement: redo target is specifically the *gap between WAL and heap* (committed-but-not-yet-flushed changes), not "the whole DB."
3. **"Safe after WAL written to disk." ✅ 4.5/5.** Corrected the right thing (log, not table). Missing piece: the *timing* — `fsync` of WAL happens *at commit, before the ack*; the commit boundary is the durability line.
4. **MVCC. ✅ 5/5 (correctly scoped, deep-dive deferred).** Learner re-derived the core insight: an index-only scan "has no idea whether the row is committed." Brief given: version metadata (`xmin`/`xmax`) lives on the *heap tuple, not the index*; deciding visibility requires reading it, so a pure index-only scan is blind → the visibility map lets Postgres trust the index entry when a page is all-visible, else fall back to the heap. Full `xmin`/`xmax`/snapshots → MVCC topic.
5. **C = app logic + declared constraints; A/I/D = DB-provided. ✅ 4.5/5.** Two fixes: (I) don't equate isolation with "no dirty reads" — that's the lowest bar; isolation = behave as if serial (serializability), a spectrum of levels, weaker ones deliberately allow anomalies. (D) nothing durable is "not on disk" — the *log* is on disk at commit; the *heap copy* is what may lag.

**Carry-forward interview sharpenings:** (1) C = only declared invariants, the DB checks your homework; (2) durability's line is COMMIT-ack, and "not yet on disk" applies to the heap, never the log.
