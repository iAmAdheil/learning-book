---
slug: spanning-tree-protocol
title: Spanning Tree Protocol (STP/RSTP) — Loop Prevention & Root Bridge Election
topic: networks
bloom-level: some
created: 2026-07-12
updated: 2026-07-12
published: 2026-07-20
related: [how-switches-work, vlans, ethernet]
tags: [layer-2, stp, rstp, spanning-tree, loop-prevention, root-bridge, bpdu, broadcast-storm, bridge-id, portfast, bpdu-guard, 802.1d, 802.1w]
sources:
  - "IEEE 802.1D — Spanning Tree Protocol"
  - "IEEE 802.1w — Rapid Spanning Tree Protocol"
---

## Answer

**The concept:** Redundant switch links create physical loops, and because Ethernet has **no
TTL**, a looping frame lives forever — multiplying into a network-killing broadcast storm. STP
(IEEE 802.1D) keeps the physical redundancy but computes a loop-free logical **tree**, blocking
the links that would form cycles. Follows directly from the flooding behavior in
[[how-switches-work]] and [[vlans]].

### The problem: redundancy vs flooding

Two facts: (1) switches **flood** unknown-unicast/broadcast out every port in the VLAN; (2)
**Ethernet frames have no TTL** (that's an IP/L3 field — L2 has no hop counter or expiry). Add
redundant links (needed for availability) and one broadcast loops forever:

```
        ┌──────── link A ────────┐
   [SW1]                          [SW2]
        └──────── link B ────────┘
```

SW1 floods a broadcast out A and B → SW2 floods each back out the other → forever, multiplying.
Three simultaneous failures:

| Failure | Effect |
|---|---|
| **Broadcast storm** | Frames multiply exponentially, saturate every link, network dies in seconds |
| **MAC table instability** | Same source MAC seen on port A then B then A… CAM table "flaps," forwarding breaks |
| **Duplicate delivery** | Hosts get multiple copies, confusing upper layers |

**STP's job:** keep the redundancy, eliminate the logical loops.

### The core idea

STP takes a looped physical topology and computes a **spanning tree** (connected, no cycles) that
reaches all switches, then **blocks** redundant links. Blocked links are **standby, not
disconnected** — they still exchange STP control messages and, if an active link dies, STP
recomputes and **unblocks** one to restore connectivity. Redundancy without loops.

### How it works (three steps, via BPDUs)

Switches exchange **BPDUs** (Bridge Protocol Data Units) — small multicast control frames, every
2 s.

**Step 1 — Elect the root bridge.** All switches elect one **root bridge** (the tree's reference).
Compare **Bridge ID (BID) = Priority (2 B, default 32768) + MAC (6 B)**. **Lowest BID wins.** With
equal default priorities, the tie goes to **lowest MAC** — so by default the lowest-MAC switch
(often the *oldest*) becomes root. **Trap:** set the root deliberately by lowering priority on
your intended core switch.

**Step 2 — Each non-root switch picks a root port** = the port with the **lowest cumulative path
cost to the root** ("my best way home"). Cost is bandwidth-based (faster = cheaper) and adds along
the path:

| Speed | Cost |
|---|---|
| 10 Mbps | 100 |
| 100 Mbps | 19 |
| 1 Gbps | 4 |
| 10 Gbps | 2 |

**Step 3 — Each segment picks a designated port** (lowest cost to root forwards onto that
segment); every remaining port **blocks**.

| Port role | Meaning | State |
|---|---|---|
| Root port | Non-root switch's best path to root | Forwarding |
| Designated port | Forwarder for a segment (all root-bridge ports are designated) | Forwarding |
| Blocking port | Would create a loop; standby | Blocked |

Block the right ports → the topology becomes a tree → no loop possible.

### Port states and why classic STP is slow

Classic 802.1D walks a port up through timed states:

```
Blocking (20s) → Listening (15s) → Learning (15s) → Forwarding   (~30–50s total)
```

Listening/Learning ensure the topology is understood before forwarding (learn MACs without
forwarding). But ~30–50 s of downtime per topology change is brutal for VoIP/TCP/users.

### RSTP (802.1w) — the fix

Rapid STP converges in **ms–seconds** by: collapsing states to **Discarding / Learning /
Forwarding**; using an **active proposal/agreement handshake** instead of timers; precomputing
**alternate/backup** port roles for near-instant failover; and adding **edge ports** (to end
devices → straight to forwarding). Backwards-compatible with STP; the **modern default**. Concepts
(root bridge, root port, costs) are identical — RSTP just converges faster.

Also: **PVST+/Rapid-PVST+** (Cisco: one STP instance per VLAN — different VLANs can use different
links, using idle redundant bandwidth) and **MSTP** (802.1s: instances per VLAN group).

### On real gear

```
Switch(config)# spanning-tree vlan 10 root primary      ! make this the root (sets low priority)
Switch(config)# spanning-tree vlan 10 priority 4096     ! ...explicitly
Switch(config)# spanning-tree mode rapid-pvst           ! use RSTP
Switch(config-if)# spanning-tree portfast               ! access port → skip the wait
Switch(config-if)# spanning-tree bpduguard enable       ! shut port if a BPDU appears
Switch# show spanning-tree vlan 10                       ! root, port roles/states, costs
```

**PortFast + BPDU Guard** pairing: PortFast skips the delay on access ports (a PC can't loop);
BPDU Guard shuts the port if a BPDU arrives (a BPDU on an access port = rogue switch plugged in).

### Gotchas

- **"Blocked ports are wasted."** They're **standby** — listening to BPDUs, ready to take over.
  (The bandwidth *is* idle in plain STP; Rapid-PVST+/MSTP let different VLANs use different links.)
- **Root elected by accident** → lowest MAC → often the oldest switch. Set priority explicitly.
- **Forgetting Ethernet has no TTL** — the whole reason STP exists. IP survives loops (TTL kills
  the packet); L2 has no safety net, so loops are permanent and fatal.
- **PortFast on a switch-to-switch link** — skips loop checks; catastrophic on a trunk. Pair with
  BPDU Guard.
- **Assuming STP prevents all loops instantly** — convergence takes time; transient loops can
  occur during changes (RSTP shrinks the window).
- **STP ≠ routing redundancy.** STP = L2 loop prevention. Gateway redundancy at L3 is HSRP/VRRP
  (later topic).

### Recall check

1. Why is a broadcast storm fatal at L2 but routing loops don't destroy L3 the same way?
   → **Ethernet has no TTL**, so a looping frame circulates forever and is duplicated out multiple
   ports — exponential until saturation. **IP has a TTL** decremented per router; at 0 the packet
   is discarded, so routing loops self-terminate per packet. L2 has no such net → STP required.
2. Three switches, no STP config — which becomes root, and why is that bad?
   → Lowest **Bridge ID**; equal default priorities (32768) → **lowest MAC**, usually the
   **oldest** switch. Bad because all traffic is drawn through your weakest switch — bottleneck +
   fragile SPOF. Fix: low priority on the core switch.
3. A blocked port sits idle for months, then the active link is unplugged — what happens?
   → STP detects the change, **recomputes, and transitions the blocked port to forwarding** (~30–50
   s classic, ~ms–s RSTP). Shows **blocked ≠ disconnected**: it was alive exchanging BPDUs on
   standby — the redundancy you built the second link for.

### One thing to walk away with

Redundant L2 links create loops, and with **no TTL** in Ethernet a looping frame lives forever →
broadcast storm → dead network in seconds. STP fixes it by electing a **root bridge** (lowest
Bridge ID = priority + MAC — *set it deliberately*), each switch finding its lowest-cost **root
port**, and **blocking** the rest into a loop-free **tree**. Blocked ports are **standby, not
dead** — a failure unblocks one. **RSTP** does this in milliseconds and is the modern default.
