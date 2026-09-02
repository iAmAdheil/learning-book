---
slug: two-phase-locking
title: Two-Phase Locking (2PL)
topic: databases
bloom-level: some
created: 2026-06-12
updated: 2026-08-23
published: 2026-06-15
related: [isolation-levels, acid-properties, covering-indexes, deadlocks, heap-storage-layout, mvcc, select-for-update-skip-locked, advisory-locks, optimistic-vs-pessimistic-locking]
tags: [transactions, two-phase-locking, 2pl, strict-2pl, ss2pl, conservative-2pl, shared-lock, exclusive-lock, lock-compatibility, lock-point, serializability, pessimistic-concurrency, cascading-aborts, lock-upgrade, mvcc, interview-priority]
sources:
  - title: "Wikipedia — Two-phase locking"
    url: "https://en.wikipedia.org/wiki/Two-phase_locking"
  - title: "PostgreSQL Documentation — Explicit Locking"
    url: "https://www.postgresql.org/docs/current/explicit-locking.html"
---

## Answer

**2PL** is a **pessimistic** concurrency-control protocol that guarantees serializability via one rule: **once a transaction releases its first lock, it may never acquire another.** All lock acquisition happens *before* any release — that single constraint makes concurrent transactions equivalent to *some* serial order. It is the lock-based counterpart to the optimistic MVCC/SSI approach in [[isolation-levels]]: where SSI runs freely and aborts conflicts at commit, 2PL acquires a lock before touching data and *blocks* anyone who conflicts. Most textbook RDBMS serializability is 2PL; Postgres is the unusual hybrid (MVCC + strict-2PL writes).

## Q: The two lock modes and compatibility matrix?

- **Shared (S)** — "I'm reading; others may read too." Many transactions can hold S on one item.
- **Exclusive (X)** — "I'm writing; nobody else touches this." One holder, incompatible with everything.

| Held → / Requested ↓ | Shared | Exclusive |
|---|---|---|
| **Shared** | ✅ | ❌ |
| **Exclusive** | ❌ | ❌ |

One-liner: **reads don't conflict with reads; writes conflict with everything.**

**Lock upgrade (S→X):** a transaction holding S that decides to write requests an upgrade. Classic deadlock source: if T1 and T2 both hold S on a row and both upgrade to X, each waits for the other's S to drop → deadlock. (This is why `SELECT FOR UPDATE` takes the X-intent upfront.)

## Q: The two phases and why it gives serializability?

Lock count over time forms a single mountain — up, then down, never up again:

- **Growing (expanding) phase:** *"locks are acquired and no locks are released."*
- **Shrinking (contracting) phase:** *"locks are released and no locks are acquired."*

Hard rule (Wikipedia): *"each transaction must never acquire a lock after it has released a lock."* The **lock point** = the moment of the last acquisition (peak / max locks held), i.e. just before the first release.

**Why serializable:** every transaction has a single instant (its lock point) where it holds all its locks. Order transactions by their lock points — that order is a valid serial order, because no transaction can grab a conflicting lock another already passed its lock point on. No conflict cycles (T1-before-T2 on A *and* T2-before-T1 on B) can form → the schedule is **conflict-serializable**.

## Q: The variants?

Basic 2PL allows releasing locks *before commit* → another txn reads that data → original aborts → **cascading aborts**. Variants fix this by delaying releases:

| Variant | Release X (write) locks | Release S (read) locks | Property |
|---|---|---|---|
| **Basic 2PL** | anytime in shrinking phase | anytime in shrinking phase | serializable; allows cascading aborts |
| **Strict 2PL (S2PL)** | **at commit/abort** | shrinking phase | recoverable; no cascading aborts |
| **Strong Strict / Rigorous (SS2PL)** | **at commit/abort** | **at commit/abort** | simplest; what real systems use |
| **Conservative (Static)** | acquire **all** locks before start | — | **deadlock-free**; needs predeclared set |

- **Strict 2PL** — hold all X locks until commit; shrinking phase for writes collapses to a single instant (commit). The practical standard.
- **Conservative 2PL** — grab everything upfront; the only deadlock-free variant (no hold-and-wait), but you must predeclare every lock, killing concurrency.

## Q: How are locks acquired, and a step-by-step trace across all four variants?

Locks are acquired **on demand by the lock manager, automatically, just before a statement touches each item**: read → request S; write → request X (or upgrade S→X); conflicting lock held → **block and wait**. The variants differ *only in when locks release* — except Conservative, which acquires everything upfront.

Trace transaction (A, B read-only; C written):
```sql
BEGIN;
SELECT balance FROM accounts WHERE id = 1;                 -- ① read A  → S(A)
SELECT balance FROM accounts WHERE id = 2;                 -- ② read B  → S(B)
UPDATE accounts SET balance = balance - 100 WHERE id = 3;  -- ③ write C → X(C)  ← LOCK POINT
COMMIT;                                                    -- ④
```

- **Basic 2PL:** acquire S(A)①, S(B)②, X(C)③ (lock point); then in shrinking phase release S(A), S(B), **X(C) — possibly before COMMIT**. ⚠️ If another txn reads C in that window and this one aborts → dirty read + cascading abort.
- **Strict 2PL:** acquire same; release **S(A), S(B) early** (reads done), but **X(C) held until COMMIT④**. ✅ No dirty reads of C.
- **SS2PL (real systems / Postgres):** acquire same; **release nothing early — S(A), S(B), X(C) all drop at COMMIT④**. ✅ Simplest to reason about (locks only grow until commit, then all drop together).
- **Conservative 2PL:** **acquire S(A), S(B), X(C) all at once at BEGIN** (block until all free); ①②③ already held; release all at COMMIT. ✅ Deadlock-free (never waits holding a lock). ❌ Must predeclare the full set.

Picture (locks held over time): Basic `▁▂▃███▁▁▁` (release after lock point, even pre-commit) · Strict `▁▂▃███▃▃▃` (S early, X to commit) · SS2PL `▁▂▃██████` (all to commit) · Conservative `████████` (all from BEGIN). The one knob: **how long after acquiring you hold before releasing** — tighter holding = fewer anomalies/deadlocks, less concurrency.

## Q: Postgres readers don't block writers, yet it uses "strict 2PL" — reconcile?

**Postgres uses MVCC for read visibility and strict-2PL-style locking for writes/explicit locks — a hybrid.**

- **MVCC governs reads:** a plain `SELECT` takes **no lock at all** — it reads a snapshot version. That is *why* readers don't block writers (and vice versa). Pure-2PL systems take an S read lock that blocks writers' X locks → reader-writer blocking that Postgres avoids.
- **Strict 2PL governs writes:** an `UPDATE`/`DELETE` takes a row-level **X lock held until end of transaction** — *"once acquired, a lock is normally held until the end of the transaction"* (= strict 2PL). `SELECT FOR UPDATE` opts a *read* into that same write-lock discipline. Table-level locks (8 modes, e.g. `ACCESS SHARE` for SELECT vs `ACCESS EXCLUSIVE` for DROP/TRUNCATE) and DDL follow the same S/X principle: *"two transactions cannot hold locks of conflicting modes on the same table at the same time."*

## Mental model

A **buffet with a strict rule: once you put a plate back, you can't pick up a new one.** Growing phase = collect every dish you'll need (each exclusive while held; others wait behind you). Lock point = the instant you set your *first* plate down. Shrinking phase = you can only return plates now. It works because everyone must collect-all-then-return, so you can line people up by *when they stopped collecting* — no two can claim they went first on different dishes. **Strict 2PL** adds: hold your dirty plates (write locks) until you've paid and left (commit), so nobody eats off your unfinished plate.

## Recall questions

1. State the single defining rule of 2PL and explain mechanically why it produces serializability. What is the lock point?
2. Give the S/X compatibility matrix in one sentence, then explain why two txns each holding S and upgrading to X on the same row deadlock.
3. What does Strict 2PL add to basic 2PL, what problem does it solve, and what happens to the shrinking phase for write locks?
4. Why is Conservative 2PL deadlock-free, and why is it impractical?
5. Postgres readers don't block writers yet it uses "strict 2PL" — what does it use MVCC for vs strict-2PL-style locking?

## Clarifications

### Confirmed answers (learner, 2026-06-12 — graded ~96%)

1. **No acquire after first release; lock point = last acquisition / just before first release. ✅ 4.5/5.** Sharpened the *why* (was slightly circular): transactions can be **ordered by their lock points**, and that order is a valid serial order because no txn can grab a conflicting lock another already passed its lock point on → no conflict cycles → conflict-serializable.
2. **"Readers allow readers, writers block everything." ✅ 5/5.** Upgrade deadlock: both hold S (compatible), each upgrade waits on the other's S, neither releases → deadlock. Key insight: the very compatibility that let both hold S concurrently is what traps them on upgrade.
3. **X held to commit/abort; solves cascading aborts; write shrinking phase = single instant (commit). ✅ 5/5.**
4. **All locks at start → no hold-and-wait → breaks circular wait → deadlock-free. ✅ 5/5.** Impractical: kills concurrency AND must predeclare the full lock set (often impossible when target rows depend on values read mid-txn).
5. **MVCC for reads, strict 2PL for w-w + table locks. ✅ 4.5/5.** Precision: a plain SELECT takes **no lock** (reads a snapshot) — that's *why* readers don't block writers; X lock from UPDATE/DELETE is held to commit (strict 2PL); `SELECT FOR UPDATE` opts a read into the write-lock discipline; table/DDL locks follow the same S/X principle.

**Carry-forward:** (1) 2PL → serializability because txns can be ordered by their lock points (conflict-acyclic). (2) Postgres = MVCC for read visibility (plain reads take *no* lock) + strict 2PL for write locks held to commit (incl. `FOR UPDATE` and table/DDL).
