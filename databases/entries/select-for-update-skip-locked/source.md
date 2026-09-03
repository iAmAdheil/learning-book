---
slug: select-for-update-skip-locked
title: SELECT FOR UPDATE & SKIP LOCKED — Row Locks and the Postgres Job Queue
topic: databases
bloom-level: some
created: 2026-08-15
updated: 2026-08-24
published: 2026-09-03
related: [two-phase-locking, deadlocks, isolation-levels, mvcc, advisory-locks, optimistic-vs-pessimistic-locking, sql-fundamentals]
tags: [transactions, select-for-update, skip-locked, nowait, row-level-lock, for-share, for-key-share, for-no-key-update, job-queue, work-queue, lost-update, read-modify-write, evalplanqual, read-committed, repeatable-read, 40001, pessimistic-locking, interview-priority]
sources:
  - title: "PostgreSQL Documentation — Explicit Locking (13.3. Row-Level Locks)"
    url: "https://www.postgresql.org/docs/current/explicit-locking.html"
  - title: "PostgreSQL Documentation — SELECT (The Locking Clause)"
    url: "https://www.postgresql.org/docs/current/sql-select.html"
  - title: "PostgreSQL Documentation — Transaction Isolation (13.2. Read Committed / Repeatable Read)"
    url: "https://www.postgresql.org/docs/current/transaction-iso.html"
---

## Answer

`SELECT ... FOR UPDATE` takes a **row-level exclusive lock** on every row the query returns, held until the transaction commits or rolls back. It turns a read into "read *and* reserve" — the explicit, pessimistic escape hatch from MVCC ([[mvcc]]), whose snapshot reads never block and therefore never stop two transactions from reading the same row and both acting on it.

Postgres defines it as locking rows *"as though for update"*, which *"prevents them from being locked, modified, or deleted by other transactions until the current transaction ends."*

`SKIP LOCKED` changes only the **contention policy**: instead of waiting for a row another transaction already locked, the scan silently skips it and moves to the next candidate. The docs are blunt that this *"provides an inconsistent view of the data"* and is therefore *"not intended for general purpose work, but is suitable for avoiding lock contention with multiple consumers accessing a queue-like table."*

```sql
BEGIN;
SELECT id, payload FROM jobs
WHERE status = 'pending'
ORDER BY created_at
LIMIT 1
FOR UPDATE SKIP LOCKED;          -- claim a row no other worker holds

UPDATE jobs SET status = 'done' WHERE id = :id;
COMMIT;                          -- lock released here, not before
```

Without `SKIP LOCKED`, ten workers all select the same oldest pending row and nine serialize behind the first — a queue with a concurrency of one. With it, each worker walks past the locked rows and claims the next free job, so throughput scales with worker count.

## Q: Why is FOR UPDATE needed at all — doesn't the transaction protect me?

No. This is the central *why*, and it follows directly from MVCC: **a plain `SELECT` takes no row lock and blocks nobody.** The Postgres docs state the rule as *"row-level locks do not affect data querying; they block only writers and lockers to the same row."*

So the classic **read-modify-write race** (a lost update) is wide open under READ COMMITTED:

```sql
-- T1                                     -- T2
BEGIN;                                    BEGIN;
SELECT balance FROM accounts              SELECT balance FROM accounts
  WHERE id = 1;   -- reads 100              WHERE id = 1;   -- reads 100 too
-- app computes 100 - 30 = 70             -- app computes 100 - 50 = 50
UPDATE accounts SET balance = 70          UPDATE accounts SET balance = 50
  WHERE id = 1;                             WHERE id = 1;   -- blocks, then wins
COMMIT;                                   COMMIT;
-- final balance = 50. T1's withdrawal vanished.
```

Both transactions read the same snapshot, both computed from a stale value, and the last writer silently overwrote the first. Adding `FOR UPDATE` to the `SELECT` fixes it: T2's select now blocks until T1 commits, then re-reads `70` and computes `70 - 50 = 20`.

The decision rule: **if the value you write depends on a value you read, the read must be locked.** A blind write (`SET balance = balance - 30`) doesn't need it, because the arithmetic happens inside the database under the write lock.

## Q: Trace it instant by instant — two users booking the same seat

The lost-update race is easier to believe when traced against a wall clock. One table, one row, two users hitting "Book" on seat 14A simultaneously:

```sql
CREATE TABLE seats (
    id     int PRIMARY KEY,
    label  text,
    status text  -- 'free' | 'booked'
);
-- row: (14, '14A', 'free')
```

**Trace 1 — plain `SELECT`: the seat gets double-booked.**

| Time | Transaction A | Transaction B | Row on disk |
|---|---|---|---|
| t1 | `BEGIN;` | | `free` |
| t2 | `SELECT status FROM seats WHERE id=14;` → **`free`** | | `free` |
| t3 | | `BEGIN;` | `free` |
| t4 | | `SELECT status FROM seats WHERE id=14;` → **`free`** | `free` |
| t5 | *app: "it's free, book it"* | *app: "it's free, book it"* | `free` |
| t6 | `UPDATE seats SET status='booked' WHERE id=14;` | | `booked` (uncommitted) |
| t7 | | same `UPDATE` → **blocks** | `booked` |
| t8 | `COMMIT;` | *unblocks, re-checks `id=14`, still matches, proceeds* | `booked` |
| t9 | | `COMMIT;` | `booked` |

Both committed; both applications reported "confirmed". Two boarding passes, one seat.

The instructive part is that **the write lock worked perfectly** — t7 really did block. But both applications had already decided at t2 and t4, off reads that locked nothing. The race was lost in application memory before the database was ever consulted. **The danger window is between the read and the write, and a plain `SELECT` does not guard it.**

**Trace 2 — `FOR UPDATE`: the block moves earlier.**

| Time | Transaction A | Transaction B | Row |
|---|---|---|---|
| t1 | `BEGIN;` | | `free` |
| t2 | `SELECT ... WHERE id=14 FOR UPDATE;` → `free` **+ lock held** | | `free` 🔒A |
| t3 | | `BEGIN;` | `free` 🔒A |
| t4 | | `SELECT ... FOR UPDATE;` → **blocks here** | `free` 🔒A |
| t5 | `UPDATE seats SET status='booked' WHERE id=14;` | *waiting* | `booked` 🔒A |
| t6 | `COMMIT;` — **lock released** | *waiting* | `booked` |
| t7 | | *unblocks, re-reads current version* → **`booked`** | `booked` 🔒B |
| t8 | | *app: "taken" → return "seat unavailable"* | `booked` |

B blocks at t4 rather than t7. That single shift is the entire fix: the wait now happens *before* the decision instead of after it, so B's read returns the truth and B's application logic reaches the right conclusion unaided. The lock lived t2→t6 — acquired on read, released at commit, with no way to release it early. That is what "held until the transaction ends" means operationally.

**Trace 3 — the same clause, opposite verdict.**

Give B `FOR UPDATE SKIP LOCKED` and replay from t4: B does not block, and B gets **zero rows** — the only candidate was locked, so it was skipped. The application sees an empty result and concludes the seat doesn't exist. Wrong answer, no error, successful query.

The tell is the requirement, not the SQL: B wanted *that specific seat*, and skipping is meaningless when there is nothing to skip to. Change the requirement to "any free aisle seat" and the same clause becomes correct:

```sql
SELECT id, label FROM seats
WHERE status = 'free' AND is_aisle
ORDER BY id
LIMIT 1
FOR UPDATE SKIP LOCKED;      -- A holds 14A, B walks past it and takes 15C
```

**The rule in one line: wait when you need *this* row; skip when you need *a* row.**

## Q: What are the four lock strengths, and how do they conflict?

Postgres has four row-level modes, from weakest to strongest. The two "key" variants exist almost entirely to keep foreign-key checks from blocking ordinary updates.

| Mode | Blocks | Does **not** block | Typical origin |
|---|---|---|---|
| `FOR KEY SHARE` | `FOR UPDATE`, `DELETE`, key-changing `UPDATE` | `FOR NO KEY UPDATE`, `FOR SHARE`, `FOR KEY SHARE` | FK check on the parent row |
| `FOR SHARE` | `UPDATE`, `DELETE`, `FOR UPDATE`, `FOR NO KEY UPDATE` | `FOR SHARE`, `FOR KEY SHARE` | "read this and keep it stable" |
| `FOR NO KEY UPDATE` | `UPDATE`, `DELETE`, `FOR UPDATE`, `FOR SHARE` | `FOR KEY SHARE` | any `UPDATE` not touching a key column |
| `FOR UPDATE` | **everything, including itself** | — | `DELETE`; `UPDATE` of a key column; explicit `FOR UPDATE` |

**Table 13.3 — Conflicting Row-Level Locks** (X = conflict):

| Requested ↓ / Held → | KEY SHARE | SHARE | NO KEY UPDATE | UPDATE |
|---|---|---|---|---|
| **FOR KEY SHARE** | | | | X |
| **FOR SHARE** | | | X | X |
| **FOR NO KEY UPDATE** | | X | X | X |
| **FOR UPDATE** | X | X | X | X |

The shape to remember: the matrix is a staircase. `FOR UPDATE` conflicts with all four (so two `FOR UPDATE`s on one row always serialize — that's what makes the queue pattern correct), while `FOR KEY SHARE` conflicts with only `FOR UPDATE`. This is why an `UPDATE users SET last_seen = now()` doesn't block a concurrent insert into a table that references that user: the insert needs only `FOR KEY SHARE`, the update takes only `FOR NO KEY UPDATE`, and those two don't conflict.

Some of these are acquired **implicitly**: `DELETE` always takes `FOR UPDATE`; an `UPDATE` takes `FOR UPDATE` if it modifies a column covered by a unique index usable in a foreign key, and `FOR NO KEY UPDATE` otherwise.

Two structural notes from the docs:
- Locks are released **at transaction end or on rollback to a savepoint** — never earlier, and never on a per-statement basis. This is the strict-2PL half of Postgres's hybrid ([[two-phase-locking]]).
- There is **no lock-count limit** — *"PostgreSQL doesn't remember any information about modified rows in memory, so there is no limit on the number of rows locked at one time."* The lock lives in the tuple header on the page, which is why *"locking a row might cause a disk write"*: a pure `SELECT FOR UPDATE` dirties pages and generates WAL.

## Q: NOWAIT vs SKIP LOCKED vs plain waiting

One locking clause, three contention policies. This is the actual decision you make at the call site:

| Policy | Row is already locked → | Use when |
|---|---|---|
| *(default)* wait | block until the holder commits/rolls back | you need **this specific row** — bank transfer, inventory decrement |
| `NOWAIT` | raise an error immediately (`55P03 lock_not_available`) | you need this row but would rather fail fast than pile up connections |
| `SKIP LOCKED` | skip it, return the next candidate | any row will do — **queues, work distribution, batch claiming** |

```sql
SELECT * FROM mytable WHERE col = 1 FOR UPDATE NOWAIT;
SELECT * FROM mytable WHERE col = 1 FOR UPDATE SKIP LOCKED;
```

Critical scope limitation from the docs: *"`NOWAIT` and `SKIP LOCKED` apply only to the row-level lock(s) — the required `ROW SHARE` table-level lock is still taken in the ordinary way."* So `SKIP LOCKED` will still block behind a concurrent `ALTER TABLE` or `VACUUM FULL` holding an `ACCESS EXCLUSIVE` table lock. It buys you nothing against DDL.

Syntax, including the `OF` clause for locking only some tables in a join:

```sql
FOR lock_strength [ OF from_reference [, ...] ] [ NOWAIT | SKIP LOCKED ]

SELECT * FROM orders o
JOIN customers c ON o.customer_id = c.id
FOR UPDATE OF o;          -- lock the order rows; read customers normally
```

When several locking clauses hit the same table, the docs say it is *"processed as if it was only specified by the strongest one"*, `NOWAIT` wins over `SKIP LOCKED`, and `SKIP LOCKED` wins over plain waiting.

## Q: The job queue pattern, in full

The complete claim-and-work loop, with the two refinements real workers need — a single-statement claim and a batch size:

```sql
-- Single-statement claim: CTE does the locking, UPDATE marks it, RETURNING hands
-- the payload back. Atomic, one round trip, no open transaction between steps.
WITH claimed AS (
    SELECT id
    FROM jobs
    WHERE status = 'pending'
      AND run_after <= now()
    ORDER BY priority DESC, run_after
    FOR UPDATE SKIP LOCKED
    LIMIT 10
)
UPDATE jobs j
SET status = 'running', started_at = now(), attempts = attempts + 1
FROM claimed c
WHERE j.id = c.id
RETURNING j.id, j.payload;
```

Why each piece is load-bearing:

- **`FOR UPDATE` inside the CTE, not the outer statement.** The docs are explicit: *"these clauses do not apply to `WITH` queries referenced by the primary query. If you want row locking to occur within a `WITH` query, specify a locking clause within the `WITH` query."* Putting `FOR UPDATE` outside would lock nothing useful.
- **`LIMIT 10`, not `LIMIT 1`.** Batching amortises round trips. The docs note *"locking stops once enough rows have been returned to satisfy the limit"*, so a `LIMIT` genuinely bounds the lock set.
- **`ORDER BY` before `FOR UPDATE`.** Gives FIFO/priority semantics. Skipped rows don't break ordering — a worker just gets the next *unclaimed* row in order.
- **Marking `status = 'running'` in the same statement.** The lock disappears at commit; without a durable status flag, a second poll would re-claim the same row. **The lock provides mutual exclusion, the status column provides the state.** Both are required.

**The failure mode this design must answer:** if a worker crashes mid-job, the transaction rolls back — but if it already committed `status = 'running'`, the row is now stranded. Standard fix is a reaper that resets rows where `status = 'running' AND started_at < now() - interval '5 minutes'`, plus an `attempts` cap routing repeat offenders to a dead-letter state. This is why job rows need a heartbeat or lease column, not just a boolean.

## Q: What happens under READ COMMITTED when the row is already locked?

This is the subtlest part of the topic, and it is the direct consequence of READ COMMITTED taking **a fresh snapshot per statement** ([[isolation-levels]]). When `UPDATE`, `DELETE`, `SELECT FOR UPDATE`, or `SELECT FOR SHARE` hits a row a concurrent transaction has locked:

1. It **waits** for the first transaction to commit or roll back.
2. On commit, it **re-evaluates the `WHERE` clause against the *updated* row version** (internally, EvalPlanQual).
3. If the new version **still matches**, it proceeds against that new version.
4. If it **no longer matches**, the row is **silently skipped**.

Step 4 is the surprise. The docs' own example:

```sql
BEGIN;
UPDATE website SET hits = hits + 1;
-- from another session:  DELETE FROM website WHERE hits = 10;
COMMIT;
```

*"the `DELETE` will have no effect even though there is a `website.hits = 10` row before and after the `UPDATE`."* The pre-update row had `hits = 9` and was invisible to the delete's predicate; by the time the `DELETE` acquires the lock, the row reads `11` and no longer matches. **A row that satisfied the condition at snapshot time and at commit time is still not deleted** — because it never satisfied it at the moment the lock was taken.

REPEATABLE READ handles the same collision differently: the transaction cannot re-read a newer version without breaking its snapshot, so instead of re-checking it **aborts**:

```
ERROR:  could not serialize access due to concurrent update   -- SQLSTATE 40001
```

The contract is the same retry loop as [[isolation-levels]]: catch `40001`, abort, retry the whole transaction from the top. On retry the other transaction's change is part of your initial snapshot, so it succeeds. Read-only REPEATABLE READ transactions never hit this.

**Interview framing:** READ COMMITTED trades a stable view for liveness (re-check and continue); REPEATABLE READ trades liveness for a stable view (abort and retry). `FOR UPDATE` behaves differently at each level for exactly that reason.

## Q: The gotchas

**`ORDER BY` results can come back out of order.** Under READ COMMITTED, sorting happens *before* the lock wait, so an ordering column may change while the query is blocked. The docs' workaround:

```sql
-- may return rows out of order:
SELECT * FROM mytable ORDER BY column1 FOR UPDATE;

-- ordered, but locks EVERY row of mytable:
SELECT * FROM (SELECT * FROM mytable FOR UPDATE) ss ORDER BY column1;
```

The docs warn the workaround *"can have significant performance implications, especially if combined with `LIMIT`"* — use it only if you genuinely expect concurrent updates to the ordering column. (At REPEATABLE READ this can't happen: you'd get a `40001` instead.)

**Rows can be locked but not returned.** *"Rows that satisfied the query conditions as of the query snapshot will be locked, although they will not be returned if they were updated after the snapshot and no longer satisfy the query conditions."* Lock set ⊇ result set.

**`OFFSET`-skipped rows are still locked.** `LIMIT` bounds the lock set; `OFFSET` does not — rows stepped past by `OFFSET` get locked anyway. Paginating with `OFFSET ... FOR UPDATE` locks everything up to and including your page.

**Sub-`SELECT` locking is narrower than it looks.** In `SELECT * FROM (SELECT * FROM mytable FOR UPDATE) ss WHERE col1 = 5`, outer conditions may be pushed into the subquery, so *"only rows having `col1 = 5` are locked"* — fewer than reading the subquery alone suggests.

**The clause is simply illegal in several places**, because the output rows can't be mapped back to individual table rows: with `GROUP BY`, `HAVING`, `DISTINCT`, aggregation, or any input or output of `UNION` / `INTERSECT` / `EXCEPT`. And as noted above, it does not reach into a `WITH` query from the outer statement.

**`SKIP LOCKED` is not a general-purpose speedup.** It returns a deliberately incomplete result set. Using it on a `SELECT ... FOR UPDATE` that must see every matching row — an inventory total, a balance sweep, a reconciliation job — silently produces wrong answers with no error. It is correct exactly when "any available row will do" is true of the workload.

## Q: How does this relate to deadlocks?

`FOR UPDATE` is pessimistic locking, so it inherits pessimistic locking's hazard: transactions locking the same rows in **different orders** deadlock ([[deadlocks]]). The fix is the same — a consistent global lock order, most simply `ORDER BY id` on the locking select so every transaction walks the rows in the same direction.

`SKIP LOCKED` is interesting here because it **structurally removes the hold-and-wait condition** for queue workers: a worker never waits on a row lock at all, so a wait-for cycle among workers cannot form. A `SKIP LOCKED` queue is deadlock-free by construction — one of the few places where you get a Coffman condition broken for free rather than by discipline.
