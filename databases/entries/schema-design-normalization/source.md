---
slug: schema-design-normalization
title: Schema Design — ER Diagrams & Normalization (1NF → BCNF)
topic: databases
bloom-level: some
created: 2026-05-31
updated: 2026-08-24
published: 2026-06-09
related: [relational-data-model, data-models-overview, denormalization, sql-fundamentals]
tags: [schema-design, normalization, er-diagram, 1nf, 2nf, 3nf, bcnf, functional-dependency, anomalies, fundamentals]
sources:
  - title: "Wikipedia — Database normalization"
    url: "https://en.wikipedia.org/wiki/Database_normalization"
  - title: "Wikipedia — Third normal form"
    url: "https://en.wikipedia.org/wiki/Third_normal_form"
  - title: "Wikipedia — Boyce–Codd normal form"
    url: "https://en.wikipedia.org/wiki/Boyce%E2%80%93Codd_normal_form"
  - title: "Wikipedia — Entity–relationship model"
    url: "https://en.wikipedia.org/wiki/Entity%E2%80%93relationship_model"
---

## Answer

**Normalization is the process of structuring tables so that every fact is stored exactly once.** Every normal form is just a different way of saying "this column is in the wrong table." Schema design has two halves: **ER modeling** (the design-time sketch of entities, attributes, relationships) and **normalization** (the formal rules — 1NF→BCNF — that keep the design free of redundancy and the three anomalies it causes).

```
-- The mnemonic that covers 1NF→3NF (William Kent):
-- Every non-key attribute must depend on
--   THE KEY        (1NF — there is a key; rows are identifiable)
--   THE WHOLE KEY  (2NF — no dependence on PART of a composite key)
--   NOTHING BUT    (3NF — no dependence on another non-key column)
--   THE KEY
```

## Q: What is an ER diagram and what is it actually for?

An **Entity-Relationship (ER) diagram** is a sketch of the domain *before* writing `CREATE TABLE`. Three primitives, mapping cleanly to SQL:

| Primitive | Part of speech | Becomes |
|---|---|---|
| **Entity** | noun (`User`, `Order`) | a table |
| **Attribute** | adjective (`email`, `price`) | a column |
| **Relationship** | verb (*places*, *owns*) | a foreign key (or junction table) |

The real payoff is being forced to decide **cardinality** — how many of each side relate — because cardinality dictates FK placement:

- **1:1** — FK on either side + `UNIQUE`. Used to split sensitive/rarely-read columns off (vertical partitioning).
- **1:N** — FK goes on the **many** side (`orders.user_id`). ~80% of real relationships.
- **M:N** — no direct representation; you **must** create a junction table.

**Crow's foot notation** reads the symbols at each line end as "min, max": `|` = one (mandatory), `o` = zero (optional), `<` (crow's foot) = many. So `USER ||──o< ORDER` reads "one user places zero-or-many orders; each order belongs to exactly one user." The `o` vs `|` on the near side is exactly whether the FK column is `NULL`-able.

**Weak entity:** an entity that can't be identified on its own — it only exists in a parent's context (an `order_line_item` is meaningless without its `order`). Its primary key *includes* the parent's key:

```sql
CREATE TABLE order_items (
    order_id    BIGINT REFERENCES orders(id),
    line_no     INT,
    product_id  BIGINT REFERENCES products(id),
    quantity    INT NOT NULL CHECK (quantity > 0),
    PRIMARY KEY (order_id, line_no)   -- identity borrowed from the parent
);
```

## Q: Why normalize at all? The three anomalies.

See the disease before the cure. A table that stores everything about enrollments in one place:

```
enrollments_bad
student_id | student_name | course_id | course_title | instructor
1          | Abhishek     | CS101     | Databases    | Dr. Codd
1          | Abhishek     | CS102     | Networks     | Dr. Cerf
2          | Maria        | CS101     | Databases    | Dr. Codd
```

Three structural bugs — each normal form exists to kill one:

1. **Update anomaly** — "Databases" is stored twice. Rename the course → update N rows; miss one → data contradicts itself. *The same fact lives in more than one place.*
2. **Insertion anomaly** — can't add a new course (`CS103`) until a student enrolls, because there's no row to put it in without a `student_id`. *Forced to invent fake data to record a real fact.*
3. **Deletion anomaly** — if Maria (the only `CS101` student) drops it, deleting her row also erases that CS101 exists and who teaches it. *Deleting one fact destroys an unrelated one.*

Root cause of all three is identical: facts about different *things* (students, courses, enrollments) crammed into one table. Normalization splits them so each fact has exactly one home.

## Q: What is a functional dependency, and why is it the engine of normalization?

A **functional dependency** `X → Y` means "if you know X, you know exactly one Y."

- `student_id → student_name` ✅ (one student, one name)
- `course_id → course_title, instructor` ✅
- `student_id → course_id` ❌ (a student takes many courses — not a function)

Two terms interviewers test by name:
- **Prime attribute** — part of *some* candidate key.
- **Non-prime attribute** — part of *no* candidate key (just data).

Normalization is mechanically just: examine every functional dependency and check whether its **left side (determinant) is a proper key**. If a non-key column determines another column, something is misplaced.

## Q: Walk through 1NF → BCNF with the violation in each.

Each form assumes the previous and adds one rule.

| Form | Rule | Kills |
|---|---|---|
| **1NF** | cells are atomic — no lists / repeating groups | unqueryable data |
| **2NF** | no non-key column depends on *part* of a composite key | partial dependency |
| **3NF** | no non-key column depends on *another non-key* column | transitive dependency |
| **BCNF** | *every* determinant is a superkey (no exceptions) | the 3NF edge case |

**1NF — atomic values.** Broken: `phone_numbers = "555-1234, 555-9999"`. Can't index, JOIN, or constrain it. Fix: a `phones` table, one row per number. (Postgres arrays/JSONB deliberately relax 1NF — a denormalization choice.)

**2NF — the whole key (only bites with composite keys).**
```
enrollments  PK = (student_id, course_id)
student_id | course_id | grade | course_title
```
`(student_id, course_id) → grade` ✅ (full key). But `course_id → course_title` ❌ — depends on **only part** of the key = **partial dependency**. Fix: `course_title` moves to a `courses` table keyed by `course_id`.

**3NF — nothing but the key.**
```
employees  PK = employee_id
employee_id | name | dept_id | dept_name
```
`employee_id → dept_id` ✅, but `dept_id → dept_name` ❌ — a non-key column determines another non-key column = **transitive dependency** (`employee_id → dept_id → dept_name`). Fix: split into `departments(dept_id, dept_name)`; `employees` keeps `dept_id` as FK.

**BCNF — the strict version.** 3NF has a loophole: it permits `X → Y` when `Y` is a *prime* attribute even if `X` is not a superkey. BCNF closes it: **every determinant must be a superkey.** Canonical example — court bookings:
```
court_bookings
candidate keys: (court, start_time) AND (rate_type, start_time)
court | start_time | rate_type
```
`rate_type → court`, but `rate_type` is not a superkey → **violates BCNF**, even though it passes 3NF (because `court` is a prime attribute, 3NF lets it slide). BCNF violations are rare and appear mostly when a table has **multiple overlapping composite candidate keys**.

## Q: How do you actually do this in practice (the mental algorithm)?

You don't recite forms — you run a loop:

1. List the real-world **things** (entities). One table per thing.
2. For each column ask: **"What does this fact depend on?"**
3. If a column depends on something *other than the table's full primary key*, move it to a table keyed by that something.
4. Replace the moved column with a foreign key.
5. Repeat until every column depends on the key, the whole key, and nothing but the key.

That question in step 2 *is* normalization. The formal forms just name which way the answer came out wrong.

## Q: Gotchas and the real-world counterweight.

- **3NF is the sweet spot.** Production schemas target 3NF (occasionally BCNF). 4NF/5NF are mostly academic.
- **Normalize first, denormalize later — deliberately.** A fully normalized schema means more JOINs. When reads demand it, you selectively reintroduce redundancy (cached `dept_name`, a denormalized count) as a *conscious* tradeoff — you now own keeping the copy in sync. (See the denormalization topic.)
- **"Atomic" is judgment, not law.** Is `address` one column or five? Depends on whether you query *by city*. Normalization serves access patterns, not the reverse.
- **Interview trap: name the violation.** "That's a transitive dependency → breaks 3NF"; "partial dependency on a composite key → breaks 2NF." Knowing the fix isn't enough — name the disease.

## Recall questions

1. A `books` table has `(book_id, author_id, author_name)` with a single author per book. Which normal form is violated and why?
2. Why does 2NF only matter when a table has a composite primary key?
3. Give the FK placement for a 1:N relationship vs an M:N relationship.
4. What's the difference between 3NF and BCNF in one sentence — and when does it actually bite you?
5. Pick one anomaly and explain how splitting a table eliminates it.

## Clarifications

### Confirmed answers (learner, 2026-05-31 — graded 5/5)

1. `book_id → author_id → author_name` is a **transitive dependency**; the second FD's determinant `author_id` is not a superkey and `author_name` is non-prime → violates **3NF**. ✅
2. A partial dependency requires the determinant to be a *proper subset* of a candidate key, which is only possible when the key has ≥2 attributes; a single-column PK is in 2NF for free. ✅
3. 1:N → FK on the many side; M:N → junction table. ✅
4. 3NF tolerates a non-superkey determinant if the dependent attribute is prime; BCNF requires the determinant to be a superkey regardless. Bites when a table has multiple overlapping composite candidate keys. ✅
5. Update anomaly: a duplicated value must be updated across every row holding it; splitting the table makes the fact live in one cell, so there is one place to update. ✅
