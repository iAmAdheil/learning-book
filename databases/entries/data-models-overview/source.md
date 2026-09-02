---
slug: data-models-overview
title: Data Models Overview — Relational vs Document vs Key-Value vs Columnar vs Graph
topic: databases
bloom-level: some
created: 2026-05-29
updated: 2026-05-29
published: 2026-06-09
related: [relational-data-model, schema-design-normalization]
tags: [data-models, nosql, document, key-value, columnar, graph, mongodb, polyglot-persistence, fundamentals, system-design]
sources:
  - title: "Designing Data-Intensive Applications (Kleppmann) — Ch. 2, Data Models and Query Languages"
    url: "https://dataintensive.net/"
  - title: "Mongoose Docs — Query.prototype.populate()"
    url: "https://mongoosejs.com/docs/api/query.html"
  - title: "MongoDB Docs — $lookup (aggregation)"
    url: "https://www.mongodb.com/docs/manual/reference/operator/aggregation/lookup/"
---

## Answer

A data model is the shape your data takes in your head and on disk; that shape decides what is cheap, expensive, or even possible. The relational model is one option among five common ones. Production engineers pick the model to match the **access pattern** (how you read and write), not the other way around.

The unifying tension behind all five: **do you store data the way it's logically true (normalized, no duplication → flexible queries, but reads reassemble via joins), or the way it's physically read (denormalized/aggregated → fast for the target pattern, worse at everything else)?**

## Q: What are the five models, and when does each fit?

| Model | Data shape | Built for | Killer weakness | Reach for it when |
|---|---|---|---|---|
| **Relational** | Tables + relations | Flexible ad-hoc queries, joins, transactions | Joins/sharding at scale | **Default.** Transactions, integrity, varied queries |
| **Document** | Nested aggregates (JSON) | Read/write a whole object by id | Cross-doc joins, duplication | Hierarchical data, fast-evolving schema |
| **Key-Value** | `key → opaque blob` | Get/put by exact key | Can't query the value | Caching, sessions, counters |
| **Columnar** | Columns stored contiguously | Aggregations over few columns, huge scans | Single-row ops/updates | Analytics / OLAP / warehousing |
| **Graph** | Nodes + edges | Deep relationship traversal | Tabular data, scaling | Networks, recommendations, fraud |

**Relational** (PostgreSQL, MySQL): normalized tables connected by FKs, queried with SQL. Flexible queries, ACID, integrity constraints; joins/sharding get hard at scale. The correct default for most apps.

**Document** (MongoDB, Firestore, Couchbase): self-contained JSON documents; aggregate-oriented — store together what you read together. One read, no joins; maps to objects in code; flexible schema; shards cleanly. But duplication (a user's name copied into every order), weak cross-document joins, no global integrity by default.

**Key-Value** (Redis, Memcached, etcd): a giant distributed hash map; the DB knows nothing about the value. Blazingly fast, trivially scalable, O(1) — but you can ONLY query by key. A document store is essentially a key-value store that understands and can index the value's contents.

**Columnar** (ClickHouse, Redshift, Snowflake, Parquet, DuckDB): logically tables, but stored column-by-column. `SELECT AVG(salary)` touches one column instead of reading every full row → far less I/O; one-type columns compress 10x+. Terrible for OLTP (single-row fetch/insert touches every column file).

**Graph** (Neo4j, Neptune): nodes + edges where relationships are first-class stored objects. Wins at deep traversal via index-free adjacency. Niche; hard to shard.

## Q: Why is columnar storage fast for analytics but bad for single-row operations?

Row store keeps each row's columns contiguous; column store keeps all values of one column contiguous.

- `SELECT AVG(salary) FROM employees` (50-column table): column store reads ONLY the salary column — ~50x less I/O than a row store, which must read every row (all columns) to extract one. Plus single-type columns compress extremely well, cutting I/O further.
- Fetching/updating a single full row is the opposite: the column store must visit every column file to reassemble or write one row. So columnar = analytics/OLAP; row = OLTP.

## Q: What is index-free adjacency and why do graph DBs beat relational at "friends-of-friends-of-friends"?

**Analogy:** Relational = a giant phone book; to find a friend's friends you go back to the front and look each one up again — every hop is a fresh search through the entire book. Graph = a contacts app where each person's card has direct tappable links to their friends' cards; you just follow the links attached to each node.

**Index-free adjacency** = a node stores its own edges, so traversing to neighbors is following a pointer, not consulting a global index.

Trace (10 friends each, 100M people total):
- Relational `friendships` table — Hop1: lookup me → 10 (1 index lookup into 100M rows). Hop2: 10 lookups → 100. Hop3: 100 lookups → 1,000. Every lookup pays the cost of indexing the whole 100M-row table, and lookups explode with depth.
- Graph — Hop1: follow 10 pointers. Hop2: follow 100. Hop3: follow 1,000. You touch only nodes/edges on your path; **cost is independent of total dataset size.**

Takeaway: relational = each hop is a fresh lookup against the entire dataset; graph = each hop follows a pointer stored on the node. For one hop relational is fine — the gap opens with depth.

## Q: Three principles to state in an interview / design review

1. **Model follows access pattern.** Decide how you read/write first, then pick the model. Picking trendy tech then discovering you need joins is the classic mistake.
2. **"NoSQL" is not one thing.** It's an umbrella over document + key-value + columnar + graph — models that gave up something relational (joins, strict schema, strong consistency) to gain something (scale, flexibility, speed for one pattern). Ask "which model, and what did it trade away?"
3. **Polyglot persistence is normal.** Real systems mix: Postgres (core transactional) + Redis (cache/sessions) + ClickHouse (analytics) + maybe Neo4j (a recommendation feature). One app, several models, each matched to its access pattern.

## Q: How do I actually decide between Relational and Document? Can't any data go in either?

Yes — both are general-purpose; you can model almost anything in either. So the question is never "which CAN store this?" but **"which makes my dominant access pattern cheap, and my critical invariants safe?"** Data shape matters less than how you read, write, and protect it.

Same blog domain, both ways:
- Relational: `authors`, `posts(author_id)`, `comments(post_id, author_id)`, `tags`, `post_tags` (M:N). Every fact stored once.
- Document: a `post` doc embeds author (name copied in), tags array, and comments (each with author name copied in). Whole post page = one read.

How the same operations feel:

| Operation | Relational | Document |
|---|---|---|
| Render one post page | joins across 5 tables | one read by id ✅ |
| All posts by author a_9 | `WHERE author_id` ✅ | hard — author buried in docs |
| All comments Sam made anywhere | `WHERE author_id` ✅ | brutal — scattered across docs |
| Sam changes his name | update one row ✅ | update every doc he appears in ❌ |
| Top 10 tags by count | one `GROUP BY` ✅ | awkward cross-doc aggregation |
| New unplanned query | just write SQL ✅ | often reshape docs |

Document is spectacular for the access pattern it was designed around and clumsy for everything else. Relational is mediocre at nothing and flexible for queries not yet imagined.

**Four decision tests:**
1. **Natural aggregate?** A chunk always loaded/saved/deleted as a unit (cart, order+items, profile)? → document fits. No clean boundary, everything connects → relational.
2. **Read one way or many ways?** Document forces committing to one access pattern up front. Many slices / ad-hoc / future-unknown queries → relational.
3. **How many-to-many / shared are relationships?** "Contains" / one-to-many living inside the parent → document. Shared, independently-queried, many-to-many entities → relational.
4. **Who guarantees consistency?** Need engine-enforced FKs, multi-entity transactions, uniqueness → relational. Document pushes that into app code.

**Rule of thumb:** Document = read/write a self-contained aggregate by id, the same way every time, accept duplication. Relational = same facts queried many ways, shared/many-to-many relationships, DB guards integrity. **Senior default: when unsure, choose relational** — it adapts to query patterns you didn't anticipate; you can always denormalize later (harder to un-bake a wrong document model).

Footnote: the boundary is genuinely blurring — Postgres `JSONB` stores documents inside a relational DB; MongoDB added transactions and `$lookup`. Models are converging, but the default cost profile still holds: relational makes joins/integrity cheap and aggregate-reads need assembly; document makes aggregate-reads cheap and joins/integrity expensive. Pick the one whose cheap things are the things you do most.

## Q: Does MongoDB support joins? What is Mongoose `ref`/`populate` really doing?

**Mongoose `ref` + `.populate()` is NOT a database join — it's an application-level join.** Per the Mongoose docs: paths are populated *after* the query executes; *a separate query is then executed for each path*. What happens on `Post.find().populate('author')`:

1. Query #1: `db.posts.find(...)` → posts, each with an author ObjectId.
2. Mongoose collects the author ids.
3. Query #2: `db.authors.find({_id: {$in: [...]}})` → those authors.
4. Mongoose stitches them together **in your Node.js process**, replacing each id with the full doc.

The join happens in app memory, not the DB. It's **one extra query per populated path** (batched via `$in`), not per document — so `populate('author')` over 100 posts = 2 queries, not 101. But chaining `.populate('author').populate('comments').populate('tags')` = 4 queries. Naive populate-in-a-loop is exactly how the N+1 problem arises.

**MongoDB itself does have a real server-side join: `$lookup`** (aggregation stage, v3.2). That runs inside the DB like a SQL `LEFT JOIN`.

| | What it is | Where the join runs |
|---|---|---|
| Mongoose `populate` | ODM convenience | Your app (multiple queries, stitched in Node) |
| MongoDB `$lookup` | Aggregation-pipeline join | The database |
| SQL `JOIN` | Native, optimizer-planned | The database, decades of optimization |

**Capability vs cost profile:** relational joins are native, indexed, optimizer-planned (it picks nested-loop/hash/merge). In MongoDB, `populate` runs outside the DB and `$lookup` is a bolt-on that's generally less efficient and historically limited (e.g. in sharded setups); guidance still favors embedding over `$lookup` on hot paths. So MongoDB *can* join, but joining isn't what the document model is good at.

> Diagnostic: if you reach for `populate`/`$lookup` on most queries, your access pattern is relational — you picked document and are fighting it. If you mostly read self-contained docs by id and rarely join, document is earning its keep.

## Q: How does this show up in real backend work?

- Systems mirror data across models: source of truth in Postgres (relational), cached in Redis (key-value), streamed into a columnar warehouse for analytics. Keeping them in sync is what CDC/outbox and cache-invalidation patterns solve.
- Choosing document-vs-relational early is high-cost; migrating models later is painful. Senior move: default to relational, justify any deviation with a concrete access-pattern pressure.

## Recall questions

1. One sentence: difference between a document store and a key-value store?
2. Why is columnar fast for `SELECT AVG(salary)` but worse for fetching one full row?
3. What is index-free adjacency and why does it beat relational at friends-of-friends-of-friends?
4. A teammate says "use MongoDB, it scales better" — what's your first question?
5. Name one app using three data models and what each is for.
6. Is `populate` a database join? Where does the work happen?
