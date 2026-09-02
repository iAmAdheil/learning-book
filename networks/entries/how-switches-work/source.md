---
slug: how-switches-work
title: How Switches Work — MAC Learning, CAM Table, Forward/Flood/Filter
topic: networks
bloom-level: some
created: 2026-07-12
updated: 2026-07-12
published: 2026-07-20
related: [ethernet, osi-model, how-internet-works, vlans, spanning-tree-protocol]
tags: [layer-2, switch, cam-table, mac-address-table, mac-learning, flooding, broadcast-domain, collision-domain, port-security, cam-overflow]
sources:
  - "IEEE 802.1D — MAC Bridges"
---

## Answer

**The concept:** A switch is a self-teaching frame forwarder. It has many ports, and when a
frame arrives for some MAC it must decide which port to send it out. Nobody configures that
map — the switch builds it automatically by watching traffic. See [[ethernet]], [[osi-model]].

### The CAM table (the switch's map)

The switch stores its `MAC → port` map in the **CAM table** (Content Addressable Memory), also
called the **MAC address table** or **forwarding table**:

```
 ┌───────────────────┬──────┬───────┐
 │ MAC               │ Port │ Age   │
 ├───────────────────┼──────┼───────┤
 │ aa:aa:aa:aa:aa:aa │  1   │ 12 s  │
 │ bb:bb:bb:bb:bb:bb │  2   │ 45 s  │
 └───────────────────┴──────┴───────┘
```

Each entry has an **age timer** (Cisco default ~300 s), reset whenever that MAC is seen again
and removed if the device goes silent. The table is dynamic and self-maintaining.

### MAC learning — learn from the SOURCE

On every arriving frame the switch does two independent things:

1. **To learn:** read the **SOURCE MAC** → record "this MAC lives on the port this frame arrived
   on."
2. **To decide:** read the **DESTINATION MAC** → consult the table.

**A switch learns where devices are by noting the source address of frames they send.** Every
transmitted frame teaches the switch that sender's location, for free — no configuration, no
protocol, just observation.

### Forward / Flood / Filter — the three decisions

| Decision | When | Action |
|---|---|---|
| **Forward** | Dest MAC **in table**, on a **different** port | Send out **only that port** (efficient unicast) |
| **Flood** | Dest MAC **unknown**, OR **broadcast** (`ff:ff:...`) / multicast | Send out **all ports except** the arrival port |
| **Filter** | Dest MAC in table, on the **same** port it arrived on | **Drop** — sender & receiver share a segment |

Flooding is the designed "I don't know where you are, so I'll ask everyone" behavior — not a
failure. The correct device's reply (carrying its source MAC) *teaches* the switch its location,
so future frames are forwarded, not flooded. The system bootstraps itself.

### Worked example (the whole topic in one trace)

Three hosts, fresh switch, **CAM table empty**:

```
   Host A ── port 1 ┐
   Host B ── port 2 ┼── [ SWITCH ]
   Host C ── port 3 ┘
```

**Step 1 — A sends to B** (arrives port 1, dest = B):
- *Learn:* source A → record **A → port 1**.
- *Decide:* dest B unknown → **FLOOD** out ports 2 and 3.
- B receives and processes it; C receives and ignores it.
- Table: `A → port 1`

**Step 2 — B replies to A** (arrives port 2, dest = A):
- *Learn:* source B → record **B → port 2**.
- *Decide:* dest A known (port 1) → **FORWARD** out port 1 only.
- Only A receives it; C is untouched.
- Table: `A → port 1`, `B → port 2`

**Step 3 — A sends to B again:**
- *Decide:* dest B known (port 2) → **FORWARD** out port 2 only. Clean unicast.

**Pattern:** the first frame to an unknown destination floods; the reply teaches the switch;
everything after is efficient unicast. A busy network's CAM table fills in seconds and flooding
becomes rare (mostly just broadcasts).

### On real gear

```
Switch# show mac address-table
          Mac Address Table
-------------------------------------------
Vlan    Mac Address       Type        Ports
----    -----------       --------    -----
   1    aaaa.aaaa.aaaa    DYNAMIC     Fa0/1
   1    bbbb.bbbb.bbbb    DYNAMIC     Fa0/2
```

`DYNAMIC` = learned automatically; `STATIC` entries can be added by hand. The **Vlan** column
foreshadows VLANs: the table is actually *per-VLAN*.

### Why switches beat hubs

A **hub** (L1) was dumb: every bit in on one port went out **every** other port, always — one
giant **collision domain**, everyone saw everyone's traffic. A **switch** (L2) learns MACs and
forwards selectively, so **each port is its own collision domain** (with full-duplex, collisions
vanish) and A↔B traffic doesn't bother C (more usable bandwidth + basic privacy). Hubs are
extinct.

### The key limitation: one switch = one broadcast domain

Broadcast frames (`ff:ff:...`) are **always flooded** to every port; a switch never filters them.

> **A switch (by default) is a single broadcast domain — every broadcast reaches every device.**

ARP requests, DHCP discovery, etc. hit *everyone*. Fine on a small network; on a large flat
network broadcast noise wastes bandwidth and CPU everywhere. **This is exactly what VLANs solve**
(slicing one switch into multiple broadcast domains), and it's why redundant switch links need
**STP**: a flooded broadcast in a loop circulates forever — a *broadcast storm*. This one
behavior motivates both following topics.

### Security: CAM table overflow

The CAM table is finite. **MAC flooding** sends thousands of frames with fake random source MACs
to fill it. Once full, the switch can't learn new entries and **fails open — flooding all traffic
out every port** (hub-like), letting an attacker sniff everything. Defense: **port security**
(limit MACs per port) — a later topic. The switch's greatest strength (learning) has an
exploitable capacity limit.

*Switching methods:* **store-and-forward** reads the whole frame and verifies FCS before
forwarding (safe, default); **cut-through** starts forwarding after reading the dest MAC (lower
latency, no error check).

### Gotchas

- **"The switch learns from the destination MAC."** No — it **learns from SOURCE**, **decides by
  DESTINATION**. Two fields, two jobs. The #1 error.
- **Flooding isn't broken** — it's the designed response to unknown-unicast and broadcast, and
  it's self-correcting.
- **Switches don't contain broadcasts** — only a **router** (or VLAN boundary) stops one. Switch
  = one broadcast domain; router = boundary between broadcast domains.
- **Switch ≠ router.** Switch = L2, frames, MAC, within a network, learns via source MACs.
  Router = L3, packets, IP, between networks.
- **Aging timers matter** — entries expire (~5 min); a moved or quiet device re-triggers
  learning/flooding. Normal.

### Recall check

1. Frame arrives on port 3 with an unknown destination MAC — what happens, and what is learned?
   → **Floods** out every port except 3; simultaneously **learns** `source-MAC → port 3` from the
   source field. Learn-from-source and decide-by-destination happen on the same frame.
2. A and B have been chatting; A sends a unicast to B — does C see it? Does C see A's ARP
   broadcast?
   → Unicast: **no** (switch forwards only to B's known port). ARP broadcast: **yes** —
   broadcasts are always flooded. Switch = one broadcast domain.
3. Attacker fills the CAM table with fake source MACs — what happens?
   → The switch **fails open and floods all frames out all ports** (hub-like), letting the
   attacker **sniff all traffic**. Mitigated by **port security**.

### One thing to walk away with

A switch is a **self-teaching frame forwarder**: it learns `MAC → port` from the **SOURCE**
address of every frame and decides where to send each frame by its **DESTINATION**. Three
outcomes — **forward** (known, different port), **flood** (unknown or broadcast), **filter**
(same port). First frame floods; the reply teaches; everything after is unicast. And because it
**floods every broadcast**, one switch is one **broadcast domain** — the fact that sets up VLANs
and STP.
