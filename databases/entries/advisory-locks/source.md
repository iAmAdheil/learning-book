---
slug: advisory-locks
title: Advisory Locks — Application-Level Coordination Through the Database
topic: databases
bloom-level: some
created: 2026-08-15
updated: 2026-08-23
published: 2026-09-03
related: [select-for-update-skip-locked, two-phase-locking, deadlocks, isolation-levels, optimistic-vs-pessimistic-locking]
tags: [transactions, advisory-lock, pg-advisory-lock, pg-try-advisory-lock, pg-advisory-xact-lock, session-level-lock, transaction-level-lock, mutual-exclusion, distributed-lock, leader-election, cron-singleton, pg-locks, max-locks-per-transaction, pgbouncer, connection-pooling, dangling-lock, interview-priority]
sources:
  - title: "PostgreSQL Documentation — Explicit Locking (13.3.5. Advisory Locks)"
    url: "https://www.postgresql.org/docs/current/explicit-locking.html"
  - title: "PostgreSQL Documentation — System Administration Functions (9.28.10. Advisory Lock Functions)"
    url: "https://www.postgresql.org/docs/current/functions-admin.html"
---

## Answer

An **advisory lock** is a lock on an arbitrary integer that the application invents. It is attached to no row, no table, and no object the database knows about. Postgres maintains a cluster-wide namespace of 64-bit keys and answers exactly one question: *is any other session currently holding this key?*

The word **advisory** is the whole concept. Postgres advises; it does not enforce. The documentation states it plainly: advisory locks are *"locks with application-defined meanings"*, and *"the system does not enforce their use — it is up to the application to use them correctly."*

**The mental model: a sign-up sheet taped to a gym machine.** The sheet does not physically stop anyone from using the bench press. There is no bar, no alarm, no enforcement. It works only because everyone agrees to check the sheet before starting and write their name on it. Someone who ignores the sheet simply uses the machine — nothing errors, nothing blocks; the coordination just silently fails.

Contrast that with a row lock ([[select-for-update-skip-locked]]), where the lock is welded to the data and Postgres *physically refuses* conflicting writes. A row lock guards the thing. An advisory lock guards nothing — it only guards **the code that agrees to check it.**

### The problem it exists to solve

A nightly job emails every customer their invoice. It is deployed on three app servers for redundancy, each with a cron entry at 02:00.

```
02:00:00  server-1 wakes → SELECT * FROM customers → sends 8,000 emails
02:00:00  server-2 wakes → SELECT * FROM customers → sends 8,000 emails
02:00:00  server-3 wakes → SELECT * FROM customers → sends 8,000 emails
```

Every customer receives three invoices.

Now try to fix this with row locking. `SELECT ... FOR UPDATE` on *what?* There is no "nightly invoice run" row. There is no row representing *the act of sending*. The thing that must be made exclusive is not data — it is **a stretch of application code**. Row locks have nothing to grab.

```sql
BEGIN;
SELECT pg_try_advisory_xact_lock(9001) AS got_it;
```

All three servers execute that line at 02:00:00 against the same Postgres:

| Server | `got_it` | Behaviour |
|---|---|---|
| server-1 | `true` | proceeds — sends the 8,000 emails |
| server-2 | `false` | logs "already running", exits |
| server-3 | `false` | logs "already running", exits |

```python
with db.transaction():
    if not db.query("SELECT pg_try_advisory_xact_lock(9001)").scalar():
        log.info("invoice run already in progress, skipping")
        return
    send_all_invoices()          # only ever one server is inside this block
# COMMIT — lock released automatically
```

`9001` means nothing to Postgres. It means "the nightly invoice job" **because the application decided it does** and wrote the same constant into all three servers. Typo it as `9002` on server-3 and server-3 sails straight through and sends its 8,000 emails — no error, no warning. The sign-up sheet again.

**Where advisory locks fit:** mutual exclusion over something with no row to lock — a singleton cron job, a leader election among app instances, a per-user critical section spanning several tables, a non-idempotent call to an external payment API, a one-at-a-time schema migration runner.

## Q: Why not just create a locks table and SELECT FOR UPDATE it?

That instinct is correct, and it identifies exactly what an advisory lock *is*: the lock table you would otherwise have to build, provided by the database for free.

| Roll your own | Advisory lock |
|---|---|
| `CREATE TABLE job_locks (name text PRIMARY KEY)` | — |
| `INSERT` the row before it can be locked | — |
| `SELECT ... FOR UPDATE` the row | `pg_try_advisory_xact_lock(9001)` |
| Locking writes to the tuple → dead tuples → autovacuum churn | no table, no rows, no bloat |
| A crashed holder leaves a stale row; needs lease expiry + a reaper | lock vanishes when the connection dies |

The last row is the underrated one. If the holder is killed mid-run — power loss, OOM, `kill -9` — its connection drops and Postgres releases the advisory lock immediately. The docs guarantee this for session locks: `pg_advisory_unlock_all()` is *"implicitly invoked at session end, even if the client disconnects ungracefully."* A locks table would need timestamp-based lease expiry plus a cleanup job to cover the same case.

The trade is enforcement. A `job_locks` row is real, inspectable data with a readable name; an advisory lock is an integer with no schema, no comment, and no foreign key telling you what it means. That documentation burden moves entirely into your codebase.

## Q: Session-level vs transaction-level — the axis that matters most

This is the distinction that causes real production incidents.

**Transaction-level** (`pg_advisory_xact_lock`) — released automatically at the end of the transaction, commit or rollback. There is no unlock function and none is needed. The docs describe these as behaving *"like regular lock requests"*.

**Session-level** (`pg_advisory_lock`) — held until explicitly released or the session ends. Critically, these **do not honour transaction semantics**:

> *"a lock acquired during a transaction that is later rolled back will still be held, and likewise an unlock is effective even if the calling transaction failed later."*

So `ROLLBACK` does **not** release a session-level advisory lock. That surprises everyone once.

Session locks also **stack** via reference counting: *"a lock can be acquired multiple times by its owning process; for each completed lock request there must be a corresponding unlock request before the lock is actually released."* Acquire the same key three times, and it takes three `pg_advisory_unlock` calls to actually free it.

Session and transaction-level requests for the same key **do block each other** as expected — they share one namespace.

**Default to the `xact` variants.** Reach for session-level only when the critical section genuinely spans multiple transactions, and then treat releasing it as an error-handling obligation, not a happy-path step.

## Q: The full function matrix

Three independent axes — scope, blocking behaviour, and mode — give the complete API:

| | Blocking (waits) | Non-blocking (`→ boolean`) |
|---|---|---|
| **Session, exclusive** | `pg_advisory_lock(key)` | `pg_try_advisory_lock(key)` |
| **Session, shared** | `pg_advisory_lock_shared(key)` | `pg_try_advisory_lock_shared(key)` |
| **Transaction, exclusive** | `pg_advisory_xact_lock(key)` | `pg_try_advisory_xact_lock(key)` |
| **Transaction, shared** | `pg_advisory_xact_lock_shared(key)` | `pg_try_advisory_xact_lock_shared(key)` |

Release functions exist only for the session-scoped variants:

| Function | Returns | Behaviour |
|---|---|---|
| `pg_advisory_unlock(key)` | `boolean` | `true` if released; `false` **plus an SQL warning** if the lock was not held |
| `pg_advisory_unlock_shared(key)` | `boolean` | same, for shared locks |
| `pg_advisory_unlock_all()` | `void` | releases every session-level advisory lock; implicitly called at session end |

**Shared vs exclusive** works the same as row locks: shared conflicts only with exclusive, never with another shared. Useful when many readers may proceed together but a writer must exclude them all — for example, many workers reading a config blob while a reloader rewrites it.

**Blocking vs `try`** is the design decision, and it maps directly onto the wait-vs-skip choice in [[select-for-update-skip-locked]]. For the cron singleton you want `try`: the other four instances should *skip*, not queue up and then each run the report in turn once the lock frees. Choosing `pg_advisory_xact_lock` there would turn a redundancy mechanism into four sequential duplicate runs.

## Q: The key space — bigint or two ints?

Every function has two overloads:

```sql
pg_advisory_lock(key bigint)
pg_advisory_lock(key1 integer, key2 integer)
```

The crucial detail: **these two key spaces do not overlap.** Locking `(1, 1)` does not conflict with locking the `bigint` whose bit pattern is the same. They are separate namespaces.

The two-int form exists to give you a natural **(classifier, identifier)** split, which is how to pick keys in practice:

```sql
-- 1 = "per-user critical section", 48291 = the user id
SELECT pg_advisory_xact_lock(1, 48291);

-- 2 = "per-tenant migration", 77 = the tenant id
SELECT pg_advisory_xact_lock(2, 77);
```

For string-named resources, hash the name — the standard idiom:

```sql
SELECT pg_advisory_xact_lock(hashtext('nightly-invoice-run'));
```

The hazard is **key collision**: two unrelated subsystems that happen to compute the same key will block each other for reasons no one will diagnose quickly. `hashtext` is a 32-bit hash, so collisions are not merely theoretical across a large key set. Mitigations, in order of preference: reserve a distinct first key for each subsystem via the two-int form, keep a single registry of constants in one shared module, and never write a literal key inline at the call site.

## Q: The gotchas

**Dangling locks from query evaluation order.** The lock functions are ordinary functions, evaluated per row, and `LIMIT` is **not guaranteed** to be applied before they run:

```sql
-- OK: exactly one row
SELECT pg_advisory_lock(id) FROM foo WHERE id = 12345;

-- DANGER: may lock far more than 100 rows
SELECT pg_advisory_lock(id) FROM foo WHERE id > 12345 LIMIT 100;

-- OK: LIMIT forced first, inside a subquery
SELECT pg_advisory_lock(q.id) FROM
(
  SELECT id FROM foo WHERE id > 12345 LIMIT 100
) q;
```

The docs warn the middle form *"could cause other advisory locks to be taken"* that the application never releases — **dangling locks**, visible in `pg_locks` and held for the rest of the session.

**Connection poolers.** In PgBouncer transaction pooling, the "session" is a backend connection borrowed for one transaction and handed to someone else afterwards. A session-level advisory lock taken there leaks onto a connection you no longer control, and a later unrelated request may inherit it. Transaction-level advisory locks are safe under transaction pooling; session-level ones require session pooling.

**Shared memory exhaustion.** Advisory locks live in the same shared lock pool as regular locks, sized by `max_locks_per_transaction` × `max_connections`. The docs caution against exhausting it, *"as this will make the server unable to grant any locks at all"*, giving a practical ceiling in the tens to hundreds of thousands. A per-row advisory lock over a million-row table is not a viable design.

**They are invisible to your schema.** Nothing in the database records that `9001` means "nightly invoice run". `pg_locks` shows the number and nothing else — the docs note all advisory locks held by any session are queryable there, which is the only debugging surface you get:

```sql
SELECT pid, mode, granted, classid, objid, objsubid
FROM pg_locks WHERE locktype = 'advisory';
```

## Q: Can advisory locks deadlock?

Yes. They are held in the same lock manager as regular locks — same shared memory pool, same `pg_locks` view — so two sessions that acquire keys in **opposite order** produce the same circular wait as any other deadlock ([[deadlocks]]):

```
session A: lock(1) → then lock(2)
session B: lock(2) → then lock(1)
```

The remedy is identical: a consistent global acquisition order, most simply ascending numeric key order.

The `pg_try_advisory_*` variants sidestep this entirely — a caller that never waits cannot participate in a wait-for cycle. This mirrors the `SKIP LOCKED` property in [[select-for-update-skip-locked]]: refusing to wait structurally removes the hold-and-wait condition rather than requiring discipline to avoid it.
