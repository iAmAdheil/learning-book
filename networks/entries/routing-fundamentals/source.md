---
slug: routing-fundamentals
title: Routing Fundamentals — The Routing Table, Longest-Prefix Match & Next Hop
topic: networks
bloom-level: some
created: 2026-08-08
updated: 2026-08-08
published: null
related: [ipv4-addressing, subnetting, vlsm, arp, encapsulation-decapsulation]
tags: [layer-3, routing, routing-table, longest-prefix-match, next-hop, default-route, administrative-distance, metric, rib, fib, cef, recursive-lookup, connected-route, static-route, floating-static, null-route, ecmp, ttl, asymmetric-routing, control-plane, data-plane]
sources:
  - "RFC 1812 — Requirements for IP Version 4 Routers (1995), §5.2.4 Next Hop Address — https://www.rfc-editor.org/rfc/rfc1812.txt — fetched 2026-08-08"
  - "RFC 1122 — Requirements for Internet Hosts (1989), §3.3.1 Routing Outbound Datagrams — https://www.rfc-editor.org/rfc/rfc1122.txt — fetched 2026-08-08"
  - "RFC 4632 — CIDR: The Internet Address Assignment and Aggregation Plan (2006) — https://www.rfc-editor.org/rfc/rfc4632.txt — fetched 2026-08-03"
  - "RFC 791 — Internet Protocol (1981) — https://www.rfc-editor.org/rfc/rfc791.txt — fetched 2026-08-03"
---

## Answer

**The concept:** A router has exactly one job — for each arriving packet, answer *"which
interface do I send this out, and to whom?"* — and the **routing table** is the data
structure that answers it. Every routing protocol that exists (OSPF, EIGRP, BGP) is
machinery for populating that table. The forwarding decision itself is simple and identical
regardless of how the table was filled.

RFC 791's framing from the addressing entry closes here:

> "A name indicates what we seek. An address indicates where it is. **A route indicates how
> to get there.**"

### The forwarding algorithm

Per RFC 1812 §5.2.4, for every packet:

```
1. read the destination IP from the header
2. look it up in the routing table
3. among all matching routes, select the LONGEST PREFIX
4. that route yields  → next-hop IP  +  egress interface
5. resolve the next-hop IP to a MAC (ARP cache, or ARP for it)
6. decrement TTL, recompute the IP header checksum
7. build a NEW L2 frame with that MAC, transmit out the egress interface
```

Steps 5–7 are why the `encapsulation-decapsulation` and `arp` entries were prerequisites.
The **L3 header survives end-to-end** (only TTL and checksum change); the **L2 frame is
built fresh at every hop**. A packet crossing 12 routers is re-framed 12 times and keeps one
IP header throughout.

RFC 1812 also confirms the header mutation: the router "decrements the TTL field and
recalculates the IP header checksum before forwarding."

### Anatomy of an entry

```
O    10.2.0.0/24 [110/20] via 192.168.1.2, 00:04:12, GigabitEthernet0/1
│    │           │   │        │             │         │
│    │           │   │        │             │         └ egress interface
│    │           │   │        │             └ age
│    │           │   │        └ next-hop IP
│    │           │   └ metric (OSPF cost)
│    │           └ administrative distance
│    └ destination prefix
└ source (O = OSPF, C = connected, S = static, D = EIGRP, B = BGP, L = local)
```

Only two fields are strictly required to forward: **prefix** and **next-hop + interface**.
Everything else exists to decide *which* route earns the slot.

---

## Q: How does longest-prefix match actually work, and what does it beat?

### The rule

Among all routes matching a destination, the one with the **most network bits** wins.
RFC 1812:

> "Routers must use the most specific matching route (the longest matching network prefix)
> when forwarding traffic."

```
destination 10.2.3.4

routing table:
  0.0.0.0/0        via ISP-A         matches —  0 bits
  10.0.0.0/8       via Core-1        matches —  8 bits
  10.2.0.0/16      via Regional-2    matches — 16 bits
  10.2.3.0/24      via Access-7      matches — 24 bits   ← WINS
  10.5.0.0/16      via Regional-5    does not match
```

The default route `0.0.0.0/0` matches every destination with zero bits, so it wins only when
nothing else matches. That is why it works as a catch-all rather than swallowing everything.

### The misconception worth killing

**Longest-prefix match is not a tiebreak among equals — it is the primary key, evaluated
before metric or administrative distance is ever consulted.**

```
  10.2.3.0/24   via Access-7,    metric 9999   ← WINS
  10.2.0.0/16   via Regional-2,  metric 1
```

A `/24` with a terrible metric beats a `/16` with a perfect one. They are **different
prefixes**, so they never compete on metric at all. Metric and AD only ever compare routes
to the *same* prefix.

### The two stages that get conflated

This is the clean model:

| Stage | Plane | Question | Decided by |
|---|---|---|---|
| **Installation** | control | For prefix P, which protocol's route goes in the table? | **administrative distance** |
| " | control | Within one protocol, which path to P? | **metric** |
| **Forwarding** | data | For destination D, which prefix applies? | **longest-prefix match** |

Metric is *inside* a protocol. AD is *between* protocols. LPM is at *lookup time* and does
not care about either.

---

## Q: Where do routes come from, and how are conflicts resolved?

### Three origins

**Connected (`C`)** — created automatically the moment an IP is configured on an interface
that comes up. Free, instant, and the foundation everything else builds on. Accompanied by a
**local (`L`)** `/32` for the router's own address, which is how the router recognizes
packets addressed to itself.

**Static (`S`)** — configured by hand. Deterministic, zero protocol overhead, no
adaptation to failure.

**Dynamic (`O`, `D`, `B`, `R`)** — learned from a routing protocol. Adapts to topology
change, at the cost of CPU, bandwidth, and configuration complexity.

### Administrative distance — trust between protocols

When two protocols offer a route to the **same prefix**, AD decides. Lower wins. Cisco's
defaults:

| Source | AD |
|---|---|
| Connected | 0 |
| Static | 1 |
| EIGRP summary | 5 |
| External BGP | 20 |
| Internal EIGRP | 90 |
| OSPF | 110 |
| IS-IS | 115 |
| RIP | 120 |
| External EIGRP | 170 |
| Internal BGP | 200 |
| Unusable | 255 |

The ordering encodes a trust judgement: a directly observed link (0) beats a human's
assertion (1), which beats any protocol's inference. Among protocols, those with richer
metrics and faster convergence rank better.

**AD 255 means "never install."** It is how a route is administratively disabled without
deleting it.

### Floating static — AD used deliberately

Give a static route an AD *higher* than the dynamic protocol's, and it sits inactive until
the dynamic route disappears:

```
Router(config)# ip route 0.0.0.0 0.0.0.0 192.168.2.1 210
                                                     └── AD 210 > OSPF's 110
```

While OSPF has a default route, OSPF wins. When OSPF loses it, the static "floats" into the
table as backup. This is the standard primary/backup WAN pattern and is worth recognizing on
sight.

---

## Q: What does "next hop" really require?

### Recursive lookup

A static route pointing at an IP does not tell the router which interface to use — that must
be resolved:

```
Router(config)# ip route 10.9.0.0 255.255.0.0 192.168.1.2

lookup for 10.9.0.1
  → matches 10.9.0.0/16, next hop 192.168.1.2
  → 192.168.1.2 is not an interface; look IT up
  → matches 192.168.1.0/24, directly connected, GigabitEthernet0/1   ← resolved
  → ARP for 192.168.1.2 on Gi0/1, frame it, send
```

That second lookup is **recursive resolution**. Two consequences:

- **If the next hop becomes unreachable, the route is removed from the table.** A static
  route whose next hop dies does not linger — but only if the *route to the next hop* dies.
  A next hop that is silently dead while its subnet stays up leaves a black hole.
- Specifying the exit interface avoids recursion:
  `ip route 10.9.0.0 255.255.0.0 GigabitEthernet0/1 192.168.1.2` (fully specified) is the
  robust form on multi-access links.

### The next hop is always one hop away

A next hop must be **directly reachable** — on a connected subnet or via another route. It
is never the final destination unless the destination happens to be adjacent. This is the
same locality as ARP: a router knows only its neighbours, and the end-to-end path is an
emergent property of every router's local decision. No single device knows the whole path.

### Null routes

```
Router(config)# ip route 10.99.0.0 255.255.0.0 null0
```

Traffic matching this is silently discarded. Two real uses:

- **Summarization anchor** — advertise a summary while null-routing the unallocated parts,
  so traffic for holes inside the summary is dropped locally instead of looping.
- **Remotely-triggered black hole (RTBH)** — under DDoS, null-route the victim address at
  the network edge so the flood is dropped before it saturates internal links. Sacrificing
  one destination to keep the rest of the network alive.

---

## Q: Do hosts route?

Yes — every host performs the same decision, in miniature. RFC 1122 §3.3.1 states the design
principle bluntly:

> "routing is a complex and difficult problem, and ought to be performed by the gateways,
> not the hosts."

So a host's table is deliberately trivial:

```
$ ip route
default via 192.168.10.1 dev eth0
192.168.10.0/24 dev eth0 proto kernel scope link src 192.168.10.57
```

Two entries, and the same longest-prefix match:

```
destination 192.168.10.99  → matches /24 (24 bits) and default (0 bits) → /24 wins
                           → scope link, no next hop → ARP for 192.168.10.99 directly

destination 8.8.8.8        → matches only default → next hop 192.168.10.1
                           → ARP for the GATEWAY's MAC, not 8.8.8.8's
```

**That second case is the single most important thing to internalize about hosts.** The
frame carries the gateway's MAC and Google's IP simultaneously — L2 addresses the next hop,
L3 addresses the final destination. This is exactly the handoff described in the `arp` entry,
now shown as a routing-table lookup.

RFC 1122 also says hosts "SHOULD maintain a route cache" — the ancestor of the modern kernel
route cache and of `ip route get`.

Linux exposes the decision directly:

```
$ ip route get 8.8.8.8
8.8.8.8 via 192.168.10.1 dev eth0 src 192.168.10.57 uid 1000

$ ip route get 192.168.10.99
192.168.10.99 dev eth0 src 192.168.10.57 uid 1000      ← no "via" = on-link
```

The presence or absence of `via` *is* the on-link/off-link answer. This is the fastest way to
debug a suspected mask or gateway problem.

---

## Q: RIB vs FIB — why are there two tables?

Because a software lookup per packet cannot run at line rate.

| | RIB (routing table) | FIB (forwarding table) |
|---|---|---|
| Plane | control | data |
| Holds | every candidate route from every protocol | only the chosen best path per prefix |
| Lives in | software / RAM | optimized structure, often ASIC/TCAM |
| Cisco command | `show ip route` | `show ip cef` |
| Changes when | topology or config changes | the RIB's best-path selection changes |

The control plane runs protocols, converges, and picks winners. It then **pushes the result
down** into the FIB, which does nothing but match-and-forward at hardware speed. Cisco's
implementation is CEF (Cisco Express Forwarding), with a companion **adjacency table**
holding pre-computed L2 rewrite strings so the frame header can be stamped without an ARP
lookup per packet.

```
Router# show ip cef 10.2.3.4
10.2.3.0/24
  nexthop 192.168.1.2 GigabitEthernet0/1
```

**Why this matters beyond Cisco:** the control-plane/data-plane split is the central idea of
modern networking. It is what SDN separates onto different machines, what makes a switch ASIC
possible, and what "programmable data plane" (P4, eBPF/XDP) refers to. A routing protocol
converging slowly is a control-plane problem; a router dropping packets at 40 Gbps is a
data-plane problem. They fail independently and are debugged differently.

---

## Q: What does this look like on real gear?

```
Router# show ip route
Codes: L - local, C - connected, S - static, R - RIP, O - OSPF,
       D - EIGRP, B - BGP, * - candidate default

Gateway of last resort is 192.168.1.1 to network 0.0.0.0

S*    0.0.0.0/0 [1/0] via 192.168.1.1
      10.0.0.0/8 is variably subnetted, 4 subnets, 3 masks
O        10.1.0.0/16 [110/20] via 192.168.1.2, 00:12:44, GigabitEthernet0/1
C        10.2.3.0/24 is directly connected, GigabitEthernet0/2
L        10.2.3.1/32 is directly connected, GigabitEthernet0/2
D        10.5.0.0/16 [90/2172416] via 192.168.1.6, 01:03:10, GigabitEthernet0/3
      192.168.1.0/24 is directly connected, GigabitEthernet0/1
```

Reading it:

- `S*` — the `*` marks the candidate default. "Gateway of last resort" is IOS naming the
  `0.0.0.0/0` next hop.
- `[110/20]` vs `[90/2172416]` — **these metrics are not comparable.** OSPF cost 20 and
  EIGRP metric 2,172,416 are different units. Only AD (110 vs 90) compares across protocols.
- `variably subnetted, 4 subnets, 3 masks` — the VLSM signal from the previous entry.

Ask the router to run the lookup rather than reading the table yourself:

```
Router# show ip route 10.2.3.99
Routing entry for 10.2.3.0/24
  Known via "connected", distance 0, metric 0 (connected, via interface)
  Routing Descriptor Blocks:
  * directly connected, via GigabitEthernet0/2
```

`show ip route <specific-address>` performs the actual longest-prefix match and reports the
winner. On a table of any size this is faster and more reliable than eyeballing.

### Static route configuration

```
! next-hop only — requires recursive lookup
Router(config)# ip route 10.9.0.0 255.255.0.0 192.168.1.2

! fully specified — interface AND next hop (preferred on multi-access links)
Router(config)# ip route 10.9.0.0 255.255.0.0 GigabitEthernet0/1 192.168.1.2

! default route
Router(config)# ip route 0.0.0.0 0.0.0.0 192.168.1.1

! floating static backup (AD 210 > OSPF 110)
Router(config)# ip route 0.0.0.0 0.0.0.0 192.168.2.1 210

! null route
Router(config)# ip route 10.99.0.0 255.255.0.0 null0
```

---

## Deeper — edge cases and gotchas

**TTL is why L3 loops are survivable and L2 loops are not.** A routing loop wastes bandwidth
and blackholes traffic, but each packet dies after at most 255 hops. Ethernet has **no TTL
field**, so an L2 loop multiplies frames without limit until the segment collapses — which
is exactly why STP must exist and why there is no "spanning tree for IP." The presence of one
header field is the entire difference between "degraded" and "fatal." (See the
`spanning-tree-protocol` entry.)

**Asymmetric routing is normal and breaks stateful middleboxes.** Nothing requires the
return path to mirror the forward path — each router decides independently, and the two
directions may legitimately differ. Consequences: a stateful firewall that sees only one
direction drops the flow as unsolicited; a NAT device that never sees the return traffic
cannot translate it; packet captures taken at one point show half a conversation. When a
connection establishes but stalls, asymmetry is a prime suspect.

**ECMP hashes per flow, not per packet.** With multiple equal-cost paths, routers hash the
5-tuple (src IP, dst IP, protocol, src port, dst port) to pick a path, so every packet of a
flow follows the same route. Per-*packet* load balancing would reorder segments, and TCP
interprets reordering as loss — triggering spurious fast retransmits and collapsing
throughput. The consequence is that a single TCP flow cannot exceed one path's bandwidth no
matter how many paths exist; aggregate capacity requires many flows.

**Anti-pattern: assuming a route means reachability.** A route says "I believe this
direction is correct," not "the destination is up." A static route to a dead next hop stays
installed as long as the next hop's *subnet* is up, black-holing everything. This is why
dynamic protocols use hellos/keepalives, and why static routes in production want an
attached liveness check (IP SLA + object tracking on Cisco, BFD generally).

**Anti-pattern: relying on the default route inside a core.** A default route in a transit
core can create loops — two routers each defaulting to the other bounce a packet until TTL
expires. Defaults belong at the edge, pointing toward the provider.

**No route ≠ silent drop.** A router with no matching route discards the packet **and sends
ICMP Destination Unreachable / Network Unreachable** back to the source. This is what makes
`traceroute` and MTU discovery work, and why silently dropping instead of replying (common in
over-aggressive firewall configs) breaks diagnostics. (See the ICMP entry.)

---

## Recall

1. A router's table contains `0.0.0.0/0 via A`, `10.0.0.0/8 via B`, `10.4.0.0/16 via C`, and
   `10.4.7.0/24 via D`. Which next hop is chosen for `10.4.7.200`, and for `10.4.9.1`?
2. Two routes to `192.168.5.0/24` exist: one via OSPF with cost 10, one static. Which is
   installed, and why? What single change would make the OSPF route win?
3. A route to `10.2.0.0/16` via OSPF has metric 5. A route to `10.2.3.0/24` via RIP has
   metric 15. A packet arrives for `10.2.3.9`. Which route forwards it — and explain why the
   metrics and administrative distances are irrelevant here.
4. A host is `192.168.10.57/24` with gateway `192.168.10.1`. It sends to `8.8.8.8`. Whose MAC
   address is in the destination field of the Ethernet frame, and whose IP is in the
   destination field of the IP header?
5. Why does an L2 loop destroy a network while an L3 routing loop merely degrades it?
6. A static route's next hop stops responding but its subnet stays up. What happens to the
   route, what happens to traffic, and what mechanism would detect it?
7. You have four equal-cost paths to a destination and one large TCP file transfer. Roughly
   how much of the aggregate bandwidth will it use, and why?
