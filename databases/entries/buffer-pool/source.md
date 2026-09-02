---
slug: buffer-pool
title: Buffer Pool / Page Cache — How a DB Manages Memory
topic: databases
bloom-level: some
created: 2026-06-30
updated: 2026-09-01
published: 2026-06-30
related: [heap-storage-layout, write-ahead-log, mvcc, table-bloat-and-autovacuum, covering-indexes, join-algorithms, query-planning, explain-analyze]
tags: [buffer-pool, shared-buffers, page-cache, buffer-manager, buffer-tag, buffer-descriptor, clock-sweep, usage-count, pin, refcount, eviction, dirty-page, bgwriter, checkpointer, ring-buffer, buffer-access-strategy, double-buffering, effective-cache-size, work-mem, pg-buffercache, interview-priority]
sources:
  - title: "The Internals of PostgreSQL §8.1 — Buffer Manager Structure"
    url: "https://www.interdb.jp/pg/pgsql08/01.html"
  - title: "The Internals of PostgreSQL §8.4 — Buffer Manager Working (Clock-Sweep)"
    url: "https://www.interdb.jp/pg/pgsql08/04.html"
  - title: "PostgreSQL Documentation — Resource Consumption (Memory)"
    url: "https://www.postgresql.org/docs/current/runtime-config-resource.html"
---

## Answer

The **buffer pool** (`shared_buffers`) is Postgres's in-RAM cache of **8 KB pages** in shared memory. *Every* heap/index page a backend reads or writes goes **through** it — never straight to the file. When it fills, a **clock-sweep** algorithm evicts a victim; and the moment a *dirty* victim is written back is exactly where the **write-ahead rule** ([[write-ahead-log]]) is mechanically enforced. This ties the block together: pages ([[heap-storage-layout]]) live here while hot, MVCC hint bits dirty them ([[mvcc]]), VACUUM avoids polluting it ([[table-bloat-and-autovacuum]]), and checkpoints flush it.

```sql
SHOW shared_buffers;                       -- pool size (default 128MB; ~25% RAM in prod)
CREATE EXTENSION pg_buffercache;           -- inspect what's cached now
SELECT count(*) FROM pg_buffercache WHERE isdirty;
```

## Q: The three-layer structure?

1. **Buffer pool** — array of fixed **8 KB slots**, each holding one page; a slot's index is its **`buffer_id`**.
2. **Buffer table** — a **hash map** `buffer_tag → buffer_id`. A **`buffer_tag`** is a page's global identity: `(tablespace, database, relation, fork#, block#)`. Turns "block 7 of this table's main fork" into "slot 412" in O(1).
3. **Buffer descriptors** — per-slot **state**: current `buffer_tag`, **dirty** flag, **refcount** (pin count — users right now), and **`usage_count`** (popularity → eviction priority).

## Q: Reading a page + pinning?

`ReadBuffer(tag)`: **hit** → hash lookup, **pin** (`refcount++`), bump `usage_count` (capped at `BM_MAX_USAGE_COUNT = 5`); **miss, free slot** → take from free list, load from disk, insert into buffer table; **miss, full** → clock-sweep a victim (flush if dirty), load into it. A **pin** (`refcount > 0`) forbids eviction while in use; the backend **unpins** (`refcount--`) when done. `usage_count` persists as a popularity residue.

## Q: Clock-sweep eviction (approximate LRU)?

A pointer (`nextVictimBuffer`) walks descriptors in a circle. At each slot:
1. **pinned** (`refcount > 0`) → skip.
2. **`usage_count == 0`** & unpinned → **victim**.
3. **`usage_count > 0`** → **decrement** and move on (second chance).

Popular pages survive several sweeps; touched-once pages decay to 0 and get reclaimed; the small cap (5) ensures even a hot page is *eventually* evictable.

**Why not true LRU?** True LRU keeps an **exact access-ordered list** and evicts the single oldest — but that requires **moving a page to the list front on *every* access**, and since the pool is shared by all backends, that list needs a **lock on every read** → a contention bottleneck. Clock-sweep drops the exact ordering: on access you only **bump a counter** (no list, no lock); eviction approximates LRU via second chances. **Locked global ordering per access (LRU) vs. cheap per-page counter + rotating hand (clock-sweep).**

## Q: The WAL connection (enforcement point)?

Before a **dirty** victim is written to its data file, the buffer manager must **flush WAL up to that page's `pd_lsn`** (`XLogFlush`) — the **write-ahead rule enforced mechanically**: a data page can never reach disk before the WAL records describing it. Three actors flush dirty buffers:
- **Checkpointer** — flushes **all** dirty buffers at a checkpoint (so old WAL recycles).
- **Background writer (bgwriter)** — trickles out soon-to-be-evicted dirty buffers, so victims are usually already clean.
- **A regular backend** — if it picks an un-cleaned dirty victim, **it does the write itself, synchronously, mid-query** → a **latency spike**. Avoiding that is *why the bgwriter exists*.

## Q: Cache pollution & ring buffers?

A naive cache flaw: one `SELECT * FROM huge_table` would stream millions of never-reread pages through the pool and **evict the hot working set**. Postgres prevents this with a **Buffer Access Strategy (ring buffer)**: large sequential scans (relation > 25% of `shared_buffers`) and bulk ops (`COPY`, `CREATE TABLE AS`, **VACUUM**) are confined to a **small set of buffers *within* the pool** (256 KB–16 MB) reused cyclically — **not** RAM outside `shared_buffers`. So a giant scan/vacuum churns its own few slots and **can't blow away the cache**. This is why a big analytical scan doesn't tank OLTP latency.

## Q: Double buffering & sizing?

Postgres pages live in **two** caches at once: `shared_buffers` **and** the **OS page cache** (kernel file cache). This **double buffering** is why sizing is **~25% of RAM** (rarely >40%): unlike `O_DIRECT` engines (Oracle/InnoDB), Postgres deliberately leans on the OS cache too, so leave RAM for it. Cranking to 80% backfires: (1) **double-buffering waste** — hot pages cached twice → fewer *distinct* pages cached overall; (2) **heavier checkpoints** (more dirty pages to flush) + memory pressure on `work_mem`/OS.

- **`shared_buffers`** — **actually allocates** the pool (real memory).
- **`effective_cache_size`** — **allocates nothing**; a *planner hint* (≈ shared_buffers + OS cache) that nudges the cost model toward **index scans**. Changes plans, not cache. (Distinct: `work_mem` = per sort/hash op; `maintenance_work_mem` = VACUUM/CREATE INDEX.)

## Mental model

A **librarian's desk with a fixed number of reading stands** (slots). A requested book (8 KB page) is checked against a **card catalog** (buffer table: `buffer_tag → buffer_id`); if absent she fetches it from the stacks (disk) onto a stand. Each stand has a sticky note: **readers now** (pin/refcount), **how popular** (usage_count), **written-in?** (dirty). When all stands are full, she walks a **circle** (clock hand): skip books being read; knock each popular book's popularity down by one and move on (second chance); evict the first unpopular one — but if it was **written in** (dirty), first **copy the changes to the master journal** (flush WAL) before reshelving. For a patron skimming a giant encyclopedia cover-to-cover (seq scan / VACUUM), she gives a **tiny separate cart** (ring buffer) so they don't clear every popular book off the main desk.

## Recall questions

1. A backend wants block 7 of a table. Walk the path through the three buffer-manager structures to find-or-load it, naming each and the `buffer_tag`'s role.
2. Explain clock-sweep: the three per-slot actions, why a hot page survives, and why Postgres uses it instead of true LRU.
3. A `SELECT` picks a dirty victim. What must happen before it's written back, which earlier-topic rule is enforced, and which background process keeps this off the query path?
4. A colleague sets `shared_buffers` to 80% of RAM "to cache more" and performance drops. Two reasons why, and how `effective_cache_size` differs from `shared_buffers`.
5. "A `SELECT *` over our 500 GB archive table will evict the whole cache." Why is this wrong in Postgres — name the mechanism and its trigger.

## Clarifications

### Confirmed answers (learner, 2026-06-30 — graded ~85%)

1. **Request → tag → buffer table hash → buffer_id; descriptors hold slot state. ✅ 4/5.** Add the **miss path**: free-list slot or clock-sweep victim (flush if dirty) → read page from disk into slot → insert `(tag→id)` into the buffer table → pin.
2. **Three steps correct (pinned skip / usage>0 decrement / usage==0 victim). ✅ 4/5.** LRU difference (was unclear): **true LRU** keeps an exact access-ordered list requiring a **locked move-to-front on every access** (contention across all backends); **clock-sweep** replaces that with a **cheap per-page counter + rotating second-chance hand** — approximate LRU, no global lock.
3. **Flush WAL up to pd_lsn before writing; checkpoint + bgwriter flush. ✅ 4.5/5.** The process specifically off the query path = **bgwriter** (else the foreground backend writes the dirty victim itself = latency spike). The rule enforced = write-ahead ([[write-ahead-log]]).
4. **Was unclear — taught.** (1) **Double-buffering waste**: pages cached in both shared_buffers *and* OS cache; oversizing the pool caches duplicates → fewer *distinct* pages overall. (2) **Heavier checkpoints** (more dirty pages) + memory pressure. **`shared_buffers`** allocates real RAM; **`effective_cache_size`** allocates nothing — a planner hint (pool + OS estimate) that biases toward index scans. Keep ~25% because Postgres shares caching with the OS.
5. **Ring buffer keeps hot pages safe. ✅ 4/5.** Fix: the ring is a **small set of buffers *within* `shared_buffers`** reused cyclically — not separate RAM. Trigger: seq scan of a table **> 25% of `shared_buffers`**, and bulk ops (COPY/CTAS/VACUUM).

**Storage Internals block complete** (heap-storage-layout → mvcc → table-bloat-and-autovacuum → write-ahead-log → buffer-pool). The buffer pool is where the block converges: pages cached here, hint bits dirty them, the write-ahead rule fires on dirty eviction, checkpoints flush them, and ring buffers protect the working set from scans/VACUUM.
