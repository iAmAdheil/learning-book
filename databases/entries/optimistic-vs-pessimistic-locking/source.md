---
slug: optimistic-vs-pessimistic-locking
title: Optimistic vs Pessimistic Locking — Choosing by Conflict Rate and Window Length
topic: databases
bloom-level: working
created: 2026-08-23
updated: 2026-08-23
published: 2026-09-03
related: [select-for-update-skip-locked, mvcc, isolation-levels, two-phase-locking, deadlocks, advisory-locks]
tags: [transactions, optimistic-locking, pessimistic-locking, occ, optimistic-concurrency-control, lost-update, read-modify-write, conflict-window, version-column, compare-and-swap, validation, evalplanqual, read-committed, repeatable-read, 40001, serialization-failure, retry, exponential-backoff, starvation, livelock, write-skew, phantom, aba-problem, atomic-update, kung-robinson, jpa-version, sqlalchemy-version-id-col, connection-pool-exhaustion, idempotency, interview-priority]
sources:
  - title: "Kung & Robinson, On Optimistic Methods for Concurrency Control, ACM TODS 6(2), June 1981, pp. 213-226"
    url: "https://dl.acm.org/doi/10.1145/319566.319567"
  - title: "PostgreSQL Documentation — Explicit Locking (13.3. Row-Level Locks)"
    url: "https://www.postgresql.org/docs/current/explicit-locking.html"
  - title: "PostgreSQL Documentation — Application-Level Data Integrity Checks (13.4)"
    url: "https://www.postgresql.org/docs/current/applevel-consistency.html"
  - title: "Jakarta Persistence 3.2 — @Version"
    url: "https://jakarta.ee/specifications/persistence/3.2/apidocs/jakarta.persistence/jakarta/persistence/version"
  - title: "SQLAlchemy 2.0 — Configuring a Version Counter"
    url: "https://docs.sqlalchemy.org/en/20/orm/versioning.html"
---

## Answer

Pessimistic and optimistic locking are two answers to one problem that the database's own isolation machinery does **not** solve: the read-modify-write cycle that runs in *application* code.

```
t0   app:  SELECT balance FROM accounts WHERE id=42   ->  1000
t1   app:  compute in Go/Python: 1000 - 100 = 900
t2   app:  UPDATE accounts SET balance = 900 WHERE id=42
```

Between `t0` and `t2` the row is unguarded. A second request runs the same three steps, both read 1000, both write 900, and one withdrawal disappears. This is the **lost update**.

MVCC does not prevent it, and the reason is the reason MVCC is fast: readers do not block writers, and a plain `SELECT` takes no lock at all. The snapshot was correct when taken. It was stale by the time the application acted on it. See [[mvcc]] and [[isolation-levels]].

**The load-bearing insight:** the hazard is not the write, it is the *duration of the gap*. That gap is measured in application time, not database time — 2 ms for a service call, 20 minutes for a human with an edit form open. Every trade-off below follows from the length of that window and the probability someone else enters it.

| | Pessimistic | Optimistic |
|---|---|---|
| Assumption | A conflict **will** happen | A conflict **will not** happen |
| Action | Prevent it — lock first | Detect it — validate at write time |
| Cost with no conflict | Wait + lock overhead, paid always | Nothing |
| Cost on conflict | Nothing extra — the other party waited | The whole transaction is discarded and redone |
| Failure mode | Blocking, deadlock, pool exhaustion | Retry storms, starvation |

### Pessimistic — lock before you look

`SELECT ... FOR UPDATE` takes a row-level exclusive lock at read time and holds it until `COMMIT`. See [[select-for-update-skip-locked]] for the full treatment.

```sql
BEGIN;
SELECT balance FROM accounts WHERE id = 42 FOR UPDATE;  -- others block HERE
UPDATE accounts SET balance = balance - 100 WHERE id = 42;
COMMIT;                                                  -- lock released
```

The lock converts the conflict window from a race into a queue.

Postgres row-lock conflict matrix, from the documentation:

| Requested / Held | KEY SHARE | SHARE | NO KEY UPDATE | UPDATE |
|---|---|---|---|---|
| FOR KEY SHARE | — | — | — | X |
| FOR SHARE | — | — | X | X |
| FOR NO KEY UPDATE | — | X | X | X |
| FOR UPDATE | X | X | X | X |

`FOR KEY SHARE` is what a foreign-key check takes. That is why an `INSERT` into a child table does not block an unrelated `UPDATE` on the parent row.

**The two costs, one of them non-obvious.** The obvious cost is waiting. The non-obvious cost is *what waiting holds*: a blocked transaction still owns a pooled connection. Twenty workers contending on one hot row is twenty pooled connections doing nothing, which is how a single popular row exhausts a pool and fails requests that never touch it.

The second cost is deadlock. From the docs:

> The best defense against deadlocks is generally to avoid them by being certain that all applications using a database acquire locks on multiple objects in a consistent order.

In practice: `... WHERE id IN (11111, 22222) ORDER BY id FOR UPDATE`. The `ORDER BY` is the deadlock fix, not decoration. See [[deadlocks]].

### Optimistic — do not lock, prove nothing changed

From Kung & Robinson (ACM TODS, June 1981), the paper that named the technique:

> The methods used are "optimistic" in the sense that they rely mainly on transaction backup as a control mechanism, "hoping" that conflicts between transactions will not occur.

Their argument against locking has five parts. Part 5 is the thesis:

> Most important for the purposes of this paper, locking may be necessary only in the worst case.

If two transactions collide once in a thousand requests, a lock taxes all thousand to fix one.

They split a transaction into **three phases**:

> During the read phase, all writes take place on local copies of the nodes to be modified. Then, if it can be established during the validation phase that the changes the transaction made will not cause a loss of integrity, the local copies are made global in the write phase.

Read -> validate -> write. Application code already does the read phase. What must be added is validation.

```sql
ALTER TABLE accounts ADD COLUMN version integer NOT NULL DEFAULT 1;
```

```sql
-- read phase: no lock, no open transaction, no held connection
SELECT balance, version FROM accounts WHERE id = 42;   -- -> 1000, 7

-- ... application computes 900. Minutes may pass. ...

-- validation AND write, in one statement
UPDATE accounts
   SET balance = 900, version = version + 1
 WHERE id = 42 AND version = 7;
```

- **1 row affected** — nobody moved. Validation passed.
- **0 rows affected** — someone committed since the read. Validation failed. Discard and retry.

The `AND version = 7` predicate *is* the validation phase, at the cost of one integer comparison and no lock.

### Why the version column is airtight — the EvalPlanQual mechanism

Two writers both read `version = 7` and both fire the UPDATE. Exactly one wins, although neither took an explicit lock. Why:

1. A bare `UPDATE` is **not** lock-free internally — it takes a `FOR NO KEY UPDATE` row lock on every row it touches.
2. Writer A locks the row, sets `version = 8`, is still in its transaction.
3. Writer B's UPDATE reaches the row and **blocks** on A's lock.
4. A commits.
5. B unblocks. Under READ COMMITTED, Postgres runs **EvalPlanQual**: it fetches the *newest committed* version of the row and **re-evaluates the WHERE clause against it**.
6. The newest row has `version = 8`; the predicate demands `version = 7`. The row drops out of the update set.
7. B reports 0 rows.

The version column converts the database's internal row lock into an application-visible **compare-and-swap**. Locking was not avoided — the lock was shrunk to the duration of one statement instead of one transaction. That is the entire win, because the conflict window was never the statement. It was the minutes before it.

Sequence worth memorising: **block -> winner commits -> re-fetch newest row -> re-evaluate predicate -> 0 rows.**

### The third option: do not read at all

If the new value is a *function of* the old value rather than a *decision based on* it, express it as a delta and the race disappears:

```sql
UPDATE accounts SET balance = balance - 100 WHERE id = 42;
```

One statement, atomic under the row lock the database takes anyway. No version column, no `FOR UPDATE`, no retry loop. Two concurrent runs correctly produce -200.

The condition can often go into the predicate too:

```sql
UPDATE accounts SET balance = balance - 100
 WHERE id = 42 AND balance >= 100;
-- 0 rows = insufficient funds, with no window between check and debit
```

Django: `F('balance') - 100`. SQLAlchemy: `Account.balance - 100`. Reach for this first. Optimistic or pessimistic locking is only needed when the decision cannot be pushed into the `WHERE` clause — when it needs application logic, an external call, or a human.

### Choosing — the decision framework

Work down the list. The first rule that fires decides it.

1. **Does the conflict window span human think time?** A user opens a form and saves eleven minutes later. -> **Optimistic, always.** A transaction and its pooled connection cannot stay open across a coffee break. This is not a preference; the pessimistic option does not exist here.
2. **Can it be expressed as an atomic in-place update?** -> Do that instead.
3. **Is contention on a single row high?** Last unit of stock, global counter, leaderboard row. -> **Pessimistic.** Optimistic degrades badly here: everyone computes, one commits, the rest discard the work. A queue beats a stampede.
4. **Is the work between read and write expensive to redo?** Long computation, paid API call, large transform. -> **Pessimistic**, or restructure so the expensive part is outside the transaction.
5. **Otherwise — rare conflicts, cheap redo.** -> **Optimistic.** This is most CRUD.

One-line crossover: **optimistic wins while `P(conflict) x cost(retry)` stays below `cost(waiting)`.** Both sides are measurable — ship optimistic with a retry counter in metrics and read the conflict rate after a week.

### Real code

```go
func withdraw(ctx context.Context, db *sql.DB, id int64, amt int) error {
    const maxAttempts = 5
    for attempt := 0; attempt < maxAttempts; attempt++ {
        var balance, version int
        err := db.QueryRowContext(ctx,
            `SELECT balance, version FROM accounts WHERE id = $1`, id,
        ).Scan(&balance, &version)
        if err != nil {
            return err
        }

        if balance < amt {
            return ErrInsufficientFunds   // decided in app code — which is why
        }                                 // the WHERE-clause trick is not enough

        res, err := db.ExecContext(ctx,
            `UPDATE accounts SET balance = $1, version = version + 1
              WHERE id = $2 AND version = $3`,
            balance-amt, id, version)
        if err != nil {
            return err
        }

        if n, _ := res.RowsAffected(); n == 1 {
            return nil                    // validation passed
        }
        sleepWithJitter(attempt)          // 0 rows: someone else won. redo.
    }
    return ErrTooManyRetries
}
```

There is no `BEGIN`. Two autocommit statements with a gap, and the gap is safe. No transaction is held open and no connection is pinned, so the function stays correct even if the statements run minutes apart.

**In ORMs this is usually built in.** Jakarta Persistence `@Version`:

> An optimistic lock failure occurs when verification of the version or timestamp fails during an attempt to update the entity, that is, if the version or timestamp held in the database changes between reading the state of an entity instance and attempting to update or delete the state of the instance.

SQLAlchemy's `version_id_col` emits exactly the SQL above and raises `StaleDataError` on a zero rowcount. Django has no built-in version column — use `F()` expressions or a manual `filter(version=n).update(...)` and check the return value.

### The interview answer, compressed

> It depends on the conflict rate and how long the read-to-write window is. Pessimistic pays a fixed cost on every access to avoid a rare failure, and it holds a transaction — and therefore a pooled connection — open for the whole window, so it does not work at all when a human is in the loop. Optimistic pays nothing on the happy path but discards the work on conflict, so it degrades under contention. Rare conflicts or a long window: optimistic. Hot contended row or expensive-to-redo work: pessimistic. And first check whether the update can be expressed atomically in one statement, because then neither is needed.

---

## Q: Under READ COMMITTED the loser is silent, under REPEATABLE READ it errors — why, and what must retry code do differently?

Under READ COMMITTED the losing UPDATE **does not abort and raises no exception**. It returns `rowcount = 0` and the program continues as if nothing happened. Nothing appears in the logs.

Under REPEATABLE READ there is no EvalPlanQual re-check, and Postgres raises:

```
ERROR:  could not serialize access due to concurrent update
SQLSTATE 40001
```

The reason is forced. The snapshot says `version = 7`; the row on disk says `version = 8`. Postgres has three options:

1. Update anyway — silently overwrites a committed change. A lost update. Unacceptable.
2. Skip it and return 0 rows (the READ COMMITTED behaviour) — but that requires looking at the *newer* row, and REPEATABLE READ has promised the transaction it will never see anything committed after it began. This would break the isolation guarantee.
3. Refuse — abort and hand the problem to the application.

Postgres takes option 3.

| | How the loser finds out | What the code must do |
|---|---|---|
| **READ COMMITTED** | Silence — `rowcount = 0` | Check the rowcount. Re-run from the read. |
| **REPEATABLE READ / SERIALIZABLE** | Loud — SQLSTATE `40001` | Catch `40001`. Restart the **whole transaction** from `BEGIN`. |

The second column difference matters more than it looks. Under READ COMMITTED the UPDATE alone can be retried. Under REPEATABLE READ the **snapshot is poisoned** — every value read in that transaction is frozen at a moment now invalidated, so re-running only the UPDATE would validate against stale reads. The retry must return to `BEGIN` and read everything again.

This is why the Postgres docs treat the retry framework as infrastructure rather than an optimization:

> it will avoid creating an unnecessary burden for application programmers if the application software goes through a framework which automatically retries transactions which are rolled back with a serialization failure.

At SERIALIZABLE, `40001` is normal operation, not an error condition. Code that does not retry it is broken.

## Q: Why is a timestamp a bad version token?

Three distinct failure modes, and the third is the one that actually happens.

**(a) The clock is coarser than the write rate.** MySQL `DATETIME` and `TIMESTAMP` store whole seconds by default — `DATETIME(6)` is required for microseconds.

```
10:00:00.100  reader reads  updated_at = '2026-08-23 10:00:00'
10:00:00.400  writer 1 commits, sets updated_at = '2026-08-23 10:00:00'   <- same value
10:00:00.900  reader:  UPDATE ... WHERE updated_at = '2026-08-23 10:00:00'
              -> matches. 1 row updated. Writer 1's change is gone.
```

The token did not change, so validation could not fail. Postgres microsecond timestamps make this rarer, not impossible — and "rarer" means under load, never in tests. Note also that `now()`/`CURRENT_TIMESTAMP` in Postgres returns *transaction start time*, so two concurrent transactions can legitimately share the value exactly.

**(b) The clock moves backwards.** If the application generates the timestamp and runs on more than one instance, NTP correction and clock skew mean node B's "now" can precede node A's. A previously seen token can be written again. This is the **ABA problem**: the value returns to an earlier observed state, so an equality check reports "unchanged" when two changes occurred. A monotonic counter cannot do this. This also kills the tempting `WHERE updated_at <= $1` variant, which looks more robust and is strictly worse.

**(c) Something changed the row without bumping the column.** A migration, a manual `psql` fix, a backfill job, an admin tool, or a new code path whose author did not know the convention. The row changed, the token did not, and every future validation passes against stale data.

A version column is not immune to (c) but is far more defensible: `version = version + 1` can be enforced in a `BEFORE UPDATE` trigger, making bypass structurally impossible. No equivalent guarantee can be placed on a column that callers may set explicitly.

## Q: Throughput collapses under a flash sale with no errors and no slow queries — what is happening?

**Livelock / starvation** on the hot row. Not deadlock: nothing waits, no cycle exists. Every transaction runs at full speed — they are running backwards. Everyone reads the same token, one wins, the rest discard their work and re-enter the same race.

Kung & Robinson flagged this in the original paper. Their method is deadlock-free by construction, but starvation is a separate problem they had to address explicitly.

**The diagnostic detail is the "no errors, no slow queries" part.** Every individual statement is fast and succeeds. `pg_stat_statements` looks healthy, the slow-query log is empty, no locks are waiting. The entire monitoring stack reports a healthy database while useful throughput is zero, because *doing work and throwing it away* is indistinguishable from *doing work* at every layer that measures queries.

There is also a fairness property. A lock queue is roughly FIFO — wait long enough and a turn arrives. Optimistic retry has **no queue**. A transaction with a longer compute phase has a proportionally wider window to lose in, so it is repeatedly beaten by faster newcomers and may never commit. That is starvation in the strict sense, and it worsens as load rises.

Fixes in order:

1. **Move the hot row to pessimistic.** `FOR UPDATE` turns the stampede into a queue — slower per request, but throughput becomes non-zero and latency becomes bounded.
2. **Better: remove the read-modify-write.** For inventory it collapses to `UPDATE items SET stock = stock - 1 WHERE id = $1 AND stock > 0`, with rowcount 0 meaning sold out.
3. **Instrument regardless.** Emit a retry-attempt counter. It is the only signal that would surface this, because no query-level metric can.

## Q: When does a version column give no protection at all?

One sentence with two faces: **a version column protects a row, so it is blind to any invariant defined over a set of rows.**

**Face 1 — the invariant spans multiple rows.** "The sum of line items must equal the order total." Transaction A edits item 1, transaction B edits item 2. Each validates perfectly — neither row was touched by anyone else. Both commit, and the order total is now wrong. Every individual check passed and the system is inconsistent, because no single row was ever in a bad state.

This is **write skew**, and it fails here for exactly the reason it fails under snapshot isolation ([[isolation-levels]]): the conflict is *between* rows, not *on* one. Optimistic locking inherits that blind spot precisely.

**Face 2 — the conflict involves a row that does not exist yet.** Two requests both check "is room 4 free at 3pm?", both find nothing, both `INSERT`. There is no row to carry a version, so there is nothing to validate against. Optimistic locking cannot protect an invariant about **absence**. This is a phantom.

Fixes all operate above the row:

- a **unique or exclusion constraint** — pushes the invariant into the database where it holds regardless of concurrency (the right answer for the booking case);
- **SERIALIZABLE**, whose predicate locks catch exactly these read-write dependencies;
- an explicit lock on a **parent row** — lock the order, then edit its items — manufacturing a single serialization point for a multi-row invariant. An [[advisory-locks]] key can serve the same role when no natural parent row exists.

Compressed: *"Optimistic locking is per-row compare-and-swap. It is precise about the row and blind to the set. If correctness spans rows — or depends on rows not existing — you need a constraint, SERIALIZABLE, or a lock on something that represents the whole set."*

## Q: What else breaks in production?

- **The rowcount check is not defensive programming — it is the concurrency control.** An UPDATE matching 0 rows is a success to the driver. Code that ignores the rowcount has a scheme that detects nothing, with no symptom. SQLAlchemy notes the same limit from the other side: `version_id_col` "does not take effect when performing a multirow UPDATE or DELETE" via `Query.update()`, because the per-row rowcount check is gone.
- **Retry needs idempotency.** The transaction rolled back cleanly; the `stripe.charge()` call did not. Anything with an external side effect must move outside the retry boundary or carry an idempotency key. Optimistic locking is what *creates* the retries that idempotency exists to make safe.
- **Retry needs a cap and jittered backoff.** An uncapped loop under contention is a self-inflicted denial of service: failures cause retries, retries raise contention, contention causes failures. Cap at 3–5 attempts, then surface the failure.
- **Never hold a pessimistic lock across a network call.** `SELECT ... FOR UPDATE`, then call the payment gateway, then `UPDATE`, then `COMMIT` locks the row for the gateway's latency — and for the full statement timeout when the gateway hangs. This is the most common way `FOR UPDATE` causes an outage.
- **`FOR UPDATE` on multiple rows without `ORDER BY`** deadlocks when two transactions lock the same set in different orders.

## Clarifications

**READ COMMITTED does not take a fresh snapshot for the whole statement.** When a transaction blocks on a row lock and then unblocks, it re-reads *only the row it blocked on*. The rest of its view stays at the older snapshot. This asymmetry is why READ COMMITTED can return a result set that never existed at any single instant.
