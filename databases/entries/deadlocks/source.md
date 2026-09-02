---
slug: deadlocks
title: Deadlocks — Detection, Prevention & the Coffman Conditions
topic: databases
bloom-level: some
created: 2026-06-15
updated: 2026-08-23
published: 2026-06-15
related: [two-phase-locking, isolation-levels, acid-properties, select-for-update-skip-locked, advisory-locks, optimistic-vs-pessimistic-locking]
tags: [transactions, deadlock, coffman-conditions, mutual-exclusion, hold-and-wait, no-preemption, circular-wait, wait-for-graph, deadlock-detection, deadlock-timeout, 40P01, lock-ordering, livelock, conservative-2pl, interview-priority]
sources:
  - title: "Wikipedia — Deadlock (computer science)"
    url: "https://en.wikipedia.org/wiki/Deadlock_(computer_science)"
  - title: "PostgreSQL Documentation — Explicit Locking (Deadlocks)"
    url: "https://www.postgresql.org/docs/current/explicit-locking.html"
---

## Answer

A **deadlock** is a cycle of waiting — a set of transactions where each holds a lock another needs and waits for a lock another holds, so none can proceed. It is the dark side of pessimistic locking ([[two-phase-locking]]): once transactions can *block* each other, they can block each other *in a circle*. > *"Deadlock is any situation in which no member of some group of entities can proceed because each waits for another member… to take action, such as… releasing a lock."* (Wikipedia)

Canonical DB example (Postgres) — two transactions locking the same two rows in **opposite order**:
```sql
-- T1                                          -- T2
UPDATE accounts SET ... WHERE acctnum = 11111; -- locks 11111
                                               UPDATE accounts SET ... WHERE acctnum = 22222; -- locks 22222
UPDATE accounts SET ... WHERE acctnum = 22222; -- BLOCKS (T2 holds it)
                                               UPDATE accounts SET ... WHERE acctnum = 11111; -- BLOCKS (T1 holds it)
-- "T1 is blocked on T2, and T2 is blocked on T1: a deadlock condition."
```

## Q: The four Coffman conditions?

A deadlock requires **all four** simultaneously (Coffman, 1971); **break any one and deadlock is impossible** — this is the master key to the whole topic:

1. **Mutual exclusion** — *"only one process at a time may use each resource."* (The X lock; S locks are shareable, so pure reads don't deadlock.)
2. **Hold and wait** — *"holding at least one resource and requesting additional resources held by others."*
3. **No preemption** — *"a resource can be released only voluntarily by the process holding it."* (The DB can't yank a lock.)
4. **Circular wait** — *"each process waits for a resource held by another, which in turn waits for the first."* A cycle.

Every deadlock strategy = attack one condition:

| Attack | How | Note |
|---|---|---|
| Mutual exclusion | lock-free structures / MVCC reads (no read locks) | not possible for writes |
| Hold-and-wait | grab **all** locks atomically upfront = **Conservative 2PL** | kills concurrency, needs predeclared set |
| No preemption | abort + roll back a victim (steal its locks) | wasted work — **what real DBs do** |
| Circular wait | global **lock ordering** (always lock 11111 before 22222) | the practical app-level fix |

The canonical example deadlocks *only* because the rows are locked in opposite order — consistent ordering removes circular wait and it's gone.

## Q: The four handling strategies?

1. **Prevention** — structurally deny one Coffman condition by design (e.g., resource-hierarchy ordering kills circular wait). Strong but rigid.
2. **Avoidance** — analyze each request at runtime, grant only if the system stays in a "safe state" (**Banker's algorithm**). Needs max needs known in advance → almost never used in real DBs.
3. **Detection + recovery** — let deadlocks happen, maintain a **wait-for graph** (nodes = transactions; edge T1→T2 = "T1 waits for a lock T2 holds"); **a cycle = a deadlock**. On detection, **abort a victim** (breaks no-preemption) so others proceed. **What Postgres / MySQL do.**
4. **Ignore (Ostrich algorithm)** — *"assume a deadlock will never occur."* Some OSes; not databases.

## Q: How does Postgres handle deadlocks?

Detection + recovery: > *"PostgreSQL automatically detects deadlock situations and resolves them by aborting one of the transactions involved, allowing the other(s) to complete. (Exactly which transaction will be aborted is difficult to predict.)"*

Mechanics (standard PG defaults):
- A blocked transaction waits **`deadlock_timeout`** (default **1s**) before detection runs — cycle-checking is expensive and most waits are ordinary contention that clears on its own, so PG optimizes for the common case. Only if still blocked does it build the wait-for graph and look for a cycle.
- A cycle → pick a victim, abort with **SQLSTATE `40P01`** (`deadlock_detected`): `ERROR: deadlock detected`.
- **The app must catch `40P01` and retry** — same retry discipline as the `40001` serialization failures in [[isolation-levels]] (different code, same pattern).

Two crucial facts:
1. > *"Deadlocks can also occur as the result of row-level locks (and thus, even if explicit locking is not used)."* Two plain `UPDATE`s in opposite order suffice.
2. > *"The best defense… is being certain that all applications acquire locks on multiple objects in a consistent order."* The break-circular-wait strategy at the app level — the single most practical takeaway.

**Livelock** (the cousin): transactions aren't frozen but keep *retrying-and-colliding* forever — *"the states of the processes constantly change… none progressing."* A naive no-delay retry loop turns a deadlock into a livelock; fix with **randomized exponential backoff** (jitter breaks symmetry, backoff spreads load).

## Mental model

Two people in a narrow one-person hallway, each holding the doorway the other needs and refusing to back up. The four Coffman conditions are the four things that must *all* be true for the freeze: hallway fits one (mutual exclusion), each stands in one doorway reaching for the next (hold and wait), neither can be shoved (no preemption), they face each other in a loop (circular wait). Remove any one — widen the hall, grab both doorways before entering, let a bouncer pull one out, or post "always pass on the right" — and the freeze can't happen. Postgres is the **bouncer**: waits ~1s (`deadlock_timeout`), sees the loop, drags one out (abort → `40P01`); the app sends that person back to retry, ideally after agreeing on consistent lock ordering.

## Recall questions

1. Name the four Coffman conditions and the headline rule. In the two-UPDATE deadlock, which does "consistent lock ordering" eliminate?
2. What is a wait-for graph and what signals a deadlock in it? Which Coffman condition does detect-and-abort break?
3. Why does Postgres wait `deadlock_timeout` (1s) before running detection?
4. Conservative 2PL is deadlock-free — which Coffman condition does it eliminate, and how?
5. A no-delay retry loop makes two txns spin forever without committing. What is this called, and what's the fix?

## Clarifications

### Confirmed answers (learner, 2026-06-15 — graded ~98%)

1. **Four conditions correct; consistent ordering → circular wait. ✅ 5/5.** Why: if all txns lock in the same global order, a cycle is impossible (a cycle needs someone holding a higher lock while waiting for a lower one — forbidden).
2. **Wait-for graph + cycle = deadlock; abort breaks no-preemption. ✅ 5/5.** Precision: nodes are **transactions** (edge T1→T2 = T1 waits for a lock T2 holds); the resource-allocation graph is the version that also has resource nodes — DBs use the transaction-only wait-for projection.
3. **Detection is expensive; most waits are ordinary contention that clears on its own. ✅ 5/5.** Optimize for the common case.
4. **Hold-and-wait — acquire all locks atomically upfront, never hold some while waiting for others. ✅ 5/5.**
5. **Livelock; randomized retry. ✅ 4.5/5.** Full fix = **randomized exponential backoff** (jitter breaks symmetry so they stop colliding in lockstep; backoff spreads retries). Distinction: deadlock = frozen (no state change); livelock = active but no progress.

**Carry-forward:** every deadlock strategy = break one Coffman condition — consistent lock ordering → circular wait; Conservative 2PL → hold-and-wait; detect-and-abort → no preemption; MVCC reads / lock-free → mutual exclusion.
