---
slug: relational-data-model
title: Relational Data Model
topic: databases
bloom-level: some
created: 2026-05-29
updated: 2026-08-24
published: 2026-06-09
related: [data-models-overview, schema-design-normalization, acid-properties, sql-fundamentals, window-functions]
tags: [relational-model, keys, constraints, schema-design, foreign-keys, primary-key, normalization, fundamentals]
sources:
  - title: "A Relational Model of Data for Large Shared Data Banks (Codd, 1970)"
    url: "https://dl.acm.org/doi/10.1145/362384.362685"
  - title: "PostgreSQL Documentation — Data Definition (Constraints)"
    url: "https://www.postgresql.org/docs/current/ddl-constraints.html"
  - title: "Wikipedia — Relational model"
    url: "https://en.wikipedia.org/wiki/Relational_model"
---

## Answer

The relational data model organizes data as **relations** (tables): unordered sets of **tuples** (rows) sharing the same **attributes** (columns). Introduced by E.F. Codd in 1970, it replaced pointer-based navigational databases with two ideas that still define SQL today: **data independence** (logical schema decoupled from physical storage) and **declarative querying** (describe the result, let the optimizer find the path). The mental anchor: *a relation is a set, and SQL is applied set theory.*

```sql
CREATE TABLE users (
    id          BIGINT       PRIMARY KEY,
    email       VARCHAR(255) NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);
```

## Q: Why does the relational model exist — what came before it?

Before 1970, databases were **navigational**: hierarchical (IBM IMS) or network/CODASYL models stored records linked by physical pointers. To read data you had to know the *access path* and walk pointer chains imperatively; changing storage layout broke every application.

Codd's 1970 paper modeled data as mathematical relations and let users query declaratively. Two consequences define modern databases:

- **Data independence** — the logical schema is decoupled from physical storage. The DB can change indexes, file layout, or caching without queries changing.
- **Declarative querying** — you describe the result set; the **query optimizer** chooses the execution strategy. This is why you write `SELECT ... WHERE` instead of pointer-walking loops.

## Q: What is the core structure and vocabulary?

| Formal (relational theory) | SQL / practical term | What it is |
|---|---|---|
| Relation | Table | A set of tuples sharing the same attributes |
| Tuple | Row / record | One data point |
| Attribute | Column / field | A named property |
| Domain | Data type (+ constraints) | The set of allowed values for an attribute |
| Cardinality | Row count | Number of tuples |
| Degree / arity | Column count | Number of attributes |

Three set-derived properties that trip people up:

1. **Row order is not guaranteed.** A table has no inherent order; `SELECT *` can return rows in any order unless you add `ORDER BY`. Practically Postgres returns heap/scan order, which changes after UPDATE or VACUUM — never rely on it.
2. **Column order shouldn't matter logically** — always name columns (`SELECT id, email`, not `SELECT *`).
3. **In pure theory, no duplicate rows** (sets have no duplicates). But **SQL tables are bags/multisets**, not pure sets — SQL allows duplicate rows unless a key/constraint forbids them. This is the single biggest deviation of SQL from the pure relational model, and the reason primary keys matter.

**Atomicity (First Normal Form):** each cell holds a single atomic value — not a list or nested record. `tags = "red,blue,green"` violates this in spirit. Postgres arrays/JSONB deliberately bend it (a denormalization tradeoff).

## Q: Explain the key hierarchy — superkey, candidate, primary, composite, foreign.

- **Superkey** — any set of columns that uniquely identifies a row. May contain redundant columns. `{id}`, `{email}`, `{id, email}` can all be superkeys.
- **Candidate key** — a *minimal* superkey: remove any column and uniqueness breaks. `{id}` and `{email}` are candidate keys; `{id, email}` is not (email alone suffices).
- **Primary key** — the candidate key chosen as canonical row identifier. DB enforces UNIQUE + NOT NULL on it. NOT NULL is the **entity integrity** rule: every entity must be identifiable.
- **Composite key** — a key spanning multiple columns; common in junction tables, e.g. `PRIMARY KEY (student_id, course_id)`.
- **Foreign key** — a column (set) referencing the primary/candidate key of another (or the same) table; the enforcement mechanism for **referential integrity** (you cannot reference a row that doesn't exist).

**Natural vs surrogate keys:** A natural key has business meaning (email, SSN, ISBN); a surrogate key is system-generated and meaningless (BIGINT sequence, UUID). Practitioners favor surrogate primary keys because natural keys change, and changing a PK cascades through every FK that references it. Keep the natural key as a `UNIQUE` constraint instead.

```sql
CREATE TABLE enrollments (
    student_id  BIGINT REFERENCES students(id),
    course_id   BIGINT REFERENCES courses(id),
    PRIMARY KEY (student_id, course_id)   -- composite PK
);
```

## Q: What are the constraint types and why enforce them in the DB rather than the app?

The key shift for backend work: **constraints push correctness down into the engine**, where they hold atomically for *every* writer — your API, a migration, a one-off psql session, a buggy cron. Application validation alone is never enough because there's always another writer, and races slip through "check-then-insert" logic.

| Constraint | Guarantees | Example |
|---|---|---|
| NOT NULL | Value present | `email VARCHAR NOT NULL` |
| UNIQUE | No two rows share value | `email ... UNIQUE` |
| PRIMARY KEY | UNIQUE + NOT NULL (entity integrity) | `PRIMARY KEY (id)` |
| FOREIGN KEY | Referenced row exists (referential integrity) | `REFERENCES users(id)` |
| CHECK | Row satisfies boolean expression | `CHECK (price >= 0)` |
| DEFAULT | Auto-fill when omitted | `DEFAULT now()` |

```sql
CREATE TABLE products (
    id     BIGINT PRIMARY KEY,
    sku    VARCHAR(64)  NOT NULL UNIQUE,
    price  NUMERIC(10,2) NOT NULL CHECK (price >= 0),
    stock  INT NOT NULL DEFAULT 0 CHECK (stock >= 0)
);
```

**Referential actions** (on delete/update of the parent row):
- `ON DELETE RESTRICT` / `NO ACTION` (default) — block delete if children exist.
- `ON DELETE CASCADE` — delete children too. Powerful but dangerous; one delete can wipe large subtrees.
- `ON DELETE SET NULL` — orphan children by nulling the FK.

**NULL gotcha:** In SQL, `NULL` means "unknown," and `NULL = NULL` evaluates to `UNKNOWN`, not true. So a standard `UNIQUE` constraint allows *multiple* NULLs (they're treated as not-equal). Three-valued logic is a recurring interview trap.

## Q: How are relationships between tables modeled?

- **One-to-many (1:N)** — the workhorse (~80% of real relationships). FK lives on the "many" side: `orders.user_id → users.id`.
- **Many-to-many (M:N)** — the relational model has no direct representation; decompose into two 1:N relationships via a **junction/associative table**. Junction tables often gain their own attributes (`enrolled_at`, `grade`), making them first-class entities.
- **One-to-one (1:1)** — rarer; a FK with a UNIQUE constraint, or shared PK. Used to split rarely-accessed or sensitive columns (e.g. `users` vs `user_credentials`) — vertical partitioning.

```sql
-- M:N: students <-> courses via junction
CREATE TABLE enrollments (
    student_id BIGINT REFERENCES students(id),
    course_id  BIGINT REFERENCES courses(id),
    enrolled_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (student_id, course_id)
);
```

## Q: How does this show up in real backend code?

- **ORM models are relations.** A `User` with `has_many :orders` just declares the 1:N FK relationship. Understanding the model lets you predict the SQL an ORM emits and spot the N+1 problem.
- **Constraints are the last line of defense.** Two concurrent API requests can both pass an app-level "is this email taken?" check and both insert; a `UNIQUE` constraint makes the second insert fail at the DB — converting silent corruption into a clean, retryable error. Connects to idempotency and optimistic locking.
- **Schema is a contract.** FKs and CHECKs document and enforce invariants that would otherwise live as tribal knowledge scattered across services.

## Q: Interview-grade summary

- A relation is a set of tuples; SQL relaxes "set" to "bag" (allows duplicates) — which is *why* keys matter.
- Superkey ⊇ candidate key (minimal) → one chosen as primary key (unique + not null = entity integrity).
- Foreign keys enforce referential integrity — no dangling references.
- 1:N = FK on the many side; M:N = junction table; 1:1 = unique FK.
- Constraints move correctness into the engine, where it holds for all concurrent writers.
- Prefer surrogate primary keys; keep natural keys as UNIQUE.

## Clarifications

### How are SQL and the relational model different — "who are they really?"

The **relational model** is a *mathematical theory* of data (Codd, 1970): relations, tuples, relational algebra. **SQL** is a *concrete programming language* (IBM 1970s, later ISO-standardized) that *implements that theory imperfectly*. Analogy: the relational model is the blueprint/physics; SQL is the building that approximately follows it.

SQL deliberately deviates from the pure theory for practical/performance reasons:

| | Relational model | SQL |
|---|---|---|
| Nature | Abstract theory | Practical language over a real engine |
| Duplicates | Forbidden (a relation is a set) | Allowed (tables are bags/multisets) |
| NULLs | Absent from Codd's original model | Allowed, with three-valued logic |
| Column order | Irrelevant | Defined/ordered |

Why duplicates are allowed: enforcing "no duplicate rows ever" would force the engine to compare each insert against every existing row. So SQL defaults to bags; you opt back into set semantics with `PRIMARY KEY`/`UNIQUE` (prevents storing dupes) or `SELECT DISTINCT` (dedups a result set).

**Practical instinct:** nearly every SQL "gotcha" is a spot where SQL bent a relational rule. When SQL surprises you, ask "is this where SQL deviates from the theory?" — usually yes.

## Recall questions

1. Why does SQL allow duplicate rows when the relational model says relations are sets — and what feature prevents them?
2. Model `posts` and `tags` where a post has many tags and a tag has many posts.
3. Why does a UNIQUE column sometimes allow two NULL values?
4. What breaks if you use a natural key (email) as the primary key and a user changes their email?
