---
slug: isolation-levels
title: Isolation Levels & Read Anomalies
topic: databases
bloom-level: some
created: 2026-06-10
updated: 2026-08-24
published: 2026-06-15
related: [acid-properties, covering-indexes, two-phase-locking, deadlocks, heap-storage-layout, mvcc, table-bloat-and-autovacuum, write-ahead-log, select-for-update-skip-locked, advisory-locks, optimistic-vs-pessimistic-locking, sql-fundamentals]
tags: [transactions, isolation-levels, read-uncommitted, read-committed, repeatable-read, serializable, dirty-read, non-repeatable-read, phantom-read, write-skew, serialization-anomaly, mvcc, snapshot-isolation, ssi, predicate-locks, 40001, interview-priority]
sources:
  - title: "PostgreSQL Documentation — Transaction Isolation"
    url: "https://www.postgresql.org/docs/current/transaction-iso.html"
  - title: "Wikipedia — Isolation (database systems)"
    url: "https://en.wikipedia.org/wiki/Isolation_(database_systems)"
---

## Answer

An **isolation level** is the dial that trades correctness-under-concurrency for speed. Raising it eliminates more **anomalies** (ways concurrent transactions corrupt each other's view) at higher cost — more locks, more aborts-and-retries, less throughput. The four ANSI levels are defined *entirely* by which anomalies they forbid. The whole topic is one table: anomalies across the top, levels down the side. This is the **I** in [[acid-properties]], made tunable.

## Q: What are the three classic read anomalies?

All three are read anomalies — a reader sees something wrong because a concurrent writer is in flight.

**Dirty read** — reading *uncommitted* data. > *"A transaction reads data written by a concurrent uncommitted transaction."* (PG)
```
T1: UPDATE accounts SET balance = 0 WHERE id = 1;   -- not committed
T2: SELECT balance FROM accounts WHERE id = 1;       -- reads 0  ← DIRTY
T1: ROLLBACK;                                        -- that 0 never existed
```

**Non-repeatable read** — the *same row* changes value if re-read. > *"A transaction re-reads data it has previously read and finds that data has been modified by another transaction (that committed since the initial read)."* (PG) Note: the writer **committed** — the data is real, but the reader got two answers for one question inside one transaction.

**Phantom read** — the *same range query* returns a different set of rows. > *"…the set of rows satisfying the condition has changed due to another recently-committed transaction."* (PG) New rows appear/vanish via INSERT/DELETE.

**The precise distinction:** non-repeatable read = an *existing row you already read* changes (UPDATE/DELETE of a specific row). Phantom = the *set membership / WHERE-clause population* changes (INSERT/DELETE). They need different defenses: locking rows you've read is **row-level locking** (cheap); preventing phantoms needs **predicate / range / gap locking** — you must lock a *condition*, because you can't lock a row that doesn't exist yet.

## Q: What are the four levels, and the ANSI table?

Each level = "which anomaly columns are forbidden." Weakest → strongest (ANSI standard, Wikipedia):

| Level | Dirty read | Non-repeatable read | Phantom read |
|---|---|---|---|
| **Read Uncommitted** | allowed | allowed | allowed |
| **Read Committed** | prevented | allowed | allowed |
| **Repeatable Read** | prevented | prevented | allowed |
| **Serializable** | prevented | prevented | prevented |

A staircase: each step forbids one more anomaly. Read Committed = "never read uncommitted data" (default in most DBs). Repeatable Read = "rows I've read won't change." Serializable = "outcome as if transactions ran one-at-a-time."

## Q: How does MVCC deliver each level?

The level is essentially *when the snapshot is taken* and *how aggressively conflicts are checked* (builds on the MVCC snapshots in [[covering-indexes]]):

- **Read Committed** — a **fresh snapshot per statement**: *"a SELECT… sees only data committed before the query began."* Each statement sees the latest committed data → exactly why non-repeatable and phantom reads slip through (statement 2 has a newer snapshot than statement 1).
- **Repeatable Read** — **one snapshot, taken at the first (non-transaction-control) statement, frozen for the whole transaction**: *"successive SELECT commands within a single transaction see the same data."* Same snapshot → stable reads → no non-repeatable, no phantom (in PG). This is textbook **Snapshot Isolation**.
- **Serializable** — RR's frozen snapshot **plus** runtime monitoring for serialization anomalies (SSI).

Because dirty reads mean "reading uncommitted versions" and MVCC *only ever shows committed versions*, **dirty reads are structurally impossible under MVCC.**

## Q: How does Postgres diverge from the ANSI standard? (interview gold)

PG implements only **three** distinct levels internally. Its table differs:

| Level | Dirty | Non-rep | Phantom | Serialization anomaly |
|---|---|---|---|---|
| Read Uncommitted | **allowed, but not in PG** | poss | poss | poss |
| Read Committed | no | poss | poss | poss |
| Repeatable Read | no | no | **allowed, but not in PG** | poss |
| Serializable | no | no | no | **no** |

1. **No real Read Uncommitted** — *"PostgreSQL's Read Uncommitted mode behaves like Read Committed… the only sensible way to map the standard levels to PostgreSQL's MVCC architecture."* There's no machinery that *could* show uncommitted data.
2. **Repeatable Read is stronger than the standard requires** — it also prevents phantoms. *"The standard specifies which anomalies must not occur… higher guarantees are acceptable."* ANSI levels are a *floor*, not an exact spec.
3. There's a **4th column ANSI omits — the serialization anomaly** — and it's why RR isn't always enough.

## Q: What does Repeatable Read still let through? (write skew)

Snapshot Isolation prevents all three *read* anomalies but permits **write skew**: two transactions read an overlapping set, each makes a decision valid on its *own* snapshot, both commit, and the *combination* breaks an invariant neither broke alone.

```
Invariant: COUNT(on_call) >= 1.   Alice & Bob both on call.
T1 (Alice): SELECT count(*) WHERE on_call;  -- sees 2, "safe to leave"
T2 (Bob):   SELECT count(*) WHERE on_call;  -- sees 2, "safe to leave"
T1: UPDATE … SET on_call=false WHERE me=Alice; COMMIT;
T2: UPDATE … SET on_call=false WHERE me=Bob;   COMMIT;
-- Zero doctors on call. Each transaction was individually fine.
```

Crucially the two transactions **write *different* rows** — so simple write-write conflict detection (what RR does) misses it. PG's term: > *"Serialization anomaly: the result of successfully committing a group of transactions is inconsistent with all possible orderings of running those transactions one at a time."* Only **Serializable** prevents it.

## Q: How does Serializable (SSI) work, and what's the application contract?

PG's Serializable is **SSI — Serializable Snapshot Isolation**: > *"builds on Snapshot Isolation by adding checks for serialization anomalies."* It uses **predicate locks** (`SIReadLock` in `pg_locks`) to track *what each transaction read*, then detects **read/write dependency** cycles — when T1 read data T2 wrote *and* vice versa, a "dangerous structure" corresponding to no serial order. It catches write skew precisely because it tracks **rw-dependencies, not write-write conflicts on the same row.**

It is **optimistic / non-blocking**: > *"these locks do not cause any blocking and therefore can not play any part in causing a deadlock."* Transactions run full speed; one is **aborted at commit** if the interleaving wasn't serializable:
```
ERROR:  could not serialize access due to read/write dependencies among transactions   -- SQLSTATE 40001
```

**The contract (most-forgotten point):** any app using Repeatable Read or Serializable **must catch SQLSTATE `40001` and retry the whole transaction.** RR also throws `40001` ("could not serialize access due to concurrent update") on a concurrent update to a row it read. No retry loop = broken under concurrency. Tradeoff: optimistic detection can't deadlock on these locks, but can waste work (run to completion, then abort).

## Mental model

A photographer handling a moving crowd:
- **Read Uncommitted** — watch the live scene; people half-out-of-frame, some who'll walk away (rolled back).
- **Read Committed** — a **new photo per shot**; each is of settled people, but two photos seconds apart differ (non-repeatable / phantom).
- **Repeatable Read** — **one photo at the start**, work from that print; people never move or multiply. But the real room changed, so filing a change from a stale print may be rejected (`40001` → retry).
- **Serializable** — same single photo **plus a referee** who checks, after everyone files, whether all edits could have happened in *some* sequential order; if two assumed incompatible worlds (write skew), one is torn up (`40001`).

Cost ladder: more isolation → fewer anomalies → more snapshots invalidated → more retries your app must handle.

## Recall questions

1. Distinguish non-repeatable read from phantom read precisely. Which SQL operations cause each, and why does that difference make phantoms harder to prevent?
2. Why is a dirty read structurally impossible in Postgres even at Read Uncommitted? Tie it to MVCC.
3. In MVCC terms, the one mechanical difference between Read Committed and Repeatable Read that explains why RR prevents non-repeatable reads?
4. The "doctors on call" write-skew scenario commits with zero on call, yet no dirty/non-repeatable/phantom read occurred. What anomaly is this, which level prevents it, and by what mechanism?
5. What must any app using RR or Serializable in Postgres do, what signal triggers it, and why is Serializable "non-blocking"?

## Clarifications

### Confirmed answers (learner, 2026-06-10 — graded ~96%)

1. **Non-rep = same read differs within a txn; phantom = same predicate returns different row count. ✅ 5/5.** Non-rep needs row-level locking (cheap); phantom needs **predicate / range / gap locking** — you must lock the *condition* because you can't lock a not-yet-inserted row.
2. **Uncommitted rows are inaccessible — only visible after parent txn commits. ✅ 5/5.** This is *why* PG collapses Read Uncommitted into Read Committed: no MVCC machinery could show uncommitted data.
3. **RC = snapshot per statement; RR = one snapshot frozen at txn start. ✅ 5/5.** Precision: the RR snapshot is taken at the **first non-transaction-control statement**, not literally at BEGIN.
4. **Serialization anomaly; Serializable via predicate locks. ✅ 4.5/5.** Correction: it is **NOT** "two txns update the same rows" — write skew writes **different** rows, which is why write-write detection (RR) misses it. SSI tracks **read/write dependencies** (T1 read what T2 wrote and vice versa = dangerous rw-structure with no serial order). rw-conflict across the read set, not ww-conflict on a row.
5. **Handle aborts + retry; `40001` triggers it; predicate locks (SIReadLock) are detection-only so non-blocking. ✅ 5/5.** Nuance: optimistic detect-and-abort can't deadlock on these locks but can waste work (run to completion then abort).

**Carry-forward interview sharpening:** write skew = read/write dependency conflict across an overlapping read set, NOT a write-write conflict on the same row — that's exactly why Snapshot Isolation / Repeatable Read permits it and only SSI / Serializable catches it.
