---
slug: vlsm
title: VLSM & Route Summarization — Carving a Network Efficiently
topic: networks
bloom-level: some
created: 2026-08-06
updated: 2026-08-08
published: null
related: [subnetting, ipv4-addressing, vlans, how-internet-works, osi-model, routing-fundamentals]
tags: [layer-3, vlsm, variable-length-subnet-mask, subnetting, route-summarization, supernetting, aggregation, alignment, classless-routing, classful-routing, ripv1, ripv2, auto-summary, discontiguous-network, wildcard-mask, ospf, eigrp]
sources:
  - "RFC 2453 — RIP Version 2 (1998) — https://www.rfc-editor.org/rfc/rfc2453.txt — fetched 2026-08-06"
  - "RFC 950 — Internet Standard Subnetting Procedure (1985) — https://www.rfc-editor.org/rfc/rfc950.txt — fetched 2026-08-05"
  - "RFC 4632 — CIDR: The Internet Address Assignment and Aggregation Plan (2006) — https://www.rfc-editor.org/rfc/rfc4632.txt — fetched 2026-08-03"
  - "RFC 1878 — Variable Length Subnet Table For IPv4 (1995) — referenced, not fetched"
---

## Answer

**The concept:** VLSM (Variable Length Subnet Masking) means using **different prefix
lengths within the same network**, sizing each subnet to what it actually needs instead of
splitting uniformly. It is what makes a 2-address point-to-point link and a 500-host LAN
coexist in one address block without waste.

```
192.168.1.0/24 carved for real requirements:

Sales        60 hosts → /26  192.168.1.0/26     .0   – .63
Engineering  28 hosts → /27  192.168.1.64/27    .64  – .95
HR           12 hosts → /28  192.168.1.96/28    .96  – .111
WAN link 1    2 hosts → /30  192.168.1.112/30   .112 – .115
WAN link 2    2 hosts → /30  192.168.1.116/30   .116 – .119
WAN link 3    2 hosts → /30  192.168.1.120/30   .120 – .123
                                       still free: .124 – .255
```

Six subnets of four different sizes, out of one /24, with 132 addresses left over.

---

## Q: Why is VLSM necessary — isn't fixed-length subnetting enough?

For the requirement above, fixed-length subnetting is not merely wasteful. **It is
impossible.** Both attempts fail:

```
Attempt 1 — size for the largest subnet (60 hosts)
  need /26 (62 usable)
  a /24 splits into only 4 × /26
  requirement is 6 subnets  →  FAILS, not enough subnets

Attempt 2 — size for the subnet count (6 subnets)
  need /27 (8 subnets)
  /27 gives 30 usable hosts
  Sales needs 60                →  FAILS, subnet too small
```

This is the trap from the subnetting entry made concrete: **"I need N subnets" and "I need
N hosts per subnet" are two independent constraints, and a single uniform prefix length
must satisfy both simultaneously.** When the requirements have any spread, no single value
exists.

VLSM removes the constraint by letting each subnet carry its own prefix length. The only
reason it works at all is that CIDR made the mask explicit — a classful world could not
express two different masks inside one network number.

---

## Q: What is the actual procedure?

**Sort requirements largest-first, then allocate in descending order.**

### The alignment rule — the thing that makes it work

> **A block of size 2ⁿ must begin at an address that is a multiple of 2ⁿ.**

This is not a convention; it falls out of the arithmetic. A `/28` has 4 host bits, so its
network address must have those 4 bits zero — meaning the last octet must be a multiple of
16. There is no such thing as `192.168.1.100/28`:

```
192.168.1.100/28   block 16 → 100 lands in the 96 block
                   → the network is actually 192.168.1.96/28
                   → the address is a host inside .96/28, not a network address
```

Writing `192.168.1.100/28` as a subnet definition silently means `192.168.1.96/28`, which
may already be allocated. **Alignment violations do not error — they overlap.**

### Why largest-first

Allocating in descending size order makes alignment automatic. Each block ends on a
boundary that is already a valid starting point for every smaller block size, because
smaller blocks are powers of two that divide the larger one.

```
/26 ends at .63   → next free .64  is a multiple of 32, 16, 8, 4  ✓ any smaller block fits
/27 ends at .95   → next free .96  is a multiple of 16, 8, 4      ✓
/28 ends at .111  → next free .112 is a multiple of 8, 4          ✓
```

Allocate small-first and the reverse is not guaranteed: place a `/30` at `.0` and the next
`/26` cannot start until `.64`, because `.4` is not a multiple of 64. The addresses between
are not *lost* — they can still hold smaller blocks — but you must now track fragments by
hand. Largest-first needs no bookkeeping at all.

### Worked allocation

```
Given 192.168.1.0/24

requirement    hosts   prefix   block   allocation
────────────────────────────────────────────────────────────────
Sales            60     /26      64     192.168.1.0/26     .0   – .63
Engineering      28     /27      32     192.168.1.64/27    .64  – .95
HR               12     /28      16     192.168.1.96/28    .96  – .111
WAN 1             2     /30       4     192.168.1.112/30   .112 – .115
WAN 2             2     /30       4     192.168.1.116/30   .116 – .119
WAN 3             2     /30       4     192.168.1.120/30   .120 – .123
────────────────────────────────────────────────────────────────
consumed 124 addresses · free 192.168.1.124 – .255
```

Each allocation's starting address is the previous block's end + 1, and each is
automatically a valid boundary for its size. Verify by checking every start is a multiple
of its own block size: 0÷64 ✓, 64÷32 ✓, 96÷16 ✓, 112÷4 ✓, 116÷4 ✓, 120÷4 ✓.

### Sizing note

Always round **up** to the prefix that satisfies the requirement, then check headroom.
Sales at 60 hosts takes a `/26` (62 usable) with 2 spare — tight. A network that will grow
should be sized at roughly 2× projected peak, which would push Sales to a `/25`. The
procedure is unchanged; only the input numbers move.

---

## Q: Why does VLSM require a classless routing protocol?

Because **a subnet is meaningless without its mask**, and older routing protocols did not
carry one.

RFC 2453 (RIPv2) states the RIPv1 problem directly:

> "If a RIP-1 route is a network route (all non-network bits 0), the subnet mask equals the
> network mask. However, if some of the non-network bits are set, the router cannot
> determine the subnet mask."

A RIPv1 router receiving `192.168.1.64` has no way to know whether that is a `/26`, a `/27`,
or a host route. Its only recourse is to **assume the mask of the interface the update
arrived on** — which is correct exactly when every subnet uses the same mask, and wrong the
moment VLSM is in use. Routes get installed with the wrong prefix length and traffic goes
to the wrong place.

RFC 2453's fix was to add an explicit field:

> "The Subnet Mask field contains the subnet mask which is applied to the IP address to
> yield the non-host portion of the address."

| Classful (no mask in updates) | Classless (mask in updates) |
|---|---|
| RIPv1, IGRP | RIPv2, EIGRP, OSPF, IS-IS, BGP |
| No VLSM, no CIDR | VLSM and CIDR supported |
| Auto-summarize at classful boundaries, always | Summarization is configurable |

Everything on the modern CCNA is classless. RIPv1 and IGRP appear only as the historical
contrast that explains *why* `no auto-summary` exists as a command.

### Discontiguous networks — the classic failure

Classful protocols automatically summarize to the classful boundary when advertising across
a different major network. That breaks when one network is split by another:

```
   172.16.1.0/24 ──[R1]── 10.0.0.0/8 ──[R2]── 172.16.2.0/24

R1 auto-summarizes and advertises  172.16.0.0/16
R2 auto-summarizes and advertises  172.16.0.0/16

Both claim the whole /16. Neither can reach the other's half —
traffic is split arbitrarily or black-holed.
```

The fix is `no auto-summary`, which lets each router advertise its specific `/24` and lets
longest-prefix match do its job.

```
R1(config)# router eigrp 100
R1(config-router)# no auto-summary
```

On modern IOS this is the default for EIGRP, but the command persists because the failure it
prevents is severe and the symptom (intermittent, direction-dependent reachability) is hard
to diagnose.

---

## Q: How does route summarization work — the reverse operation?

VLSM splits a block into more-specific prefixes. **Summarization merges more-specific
prefixes into one less-specific advertisement.** Same mask boundary, opposite direction.

### The procedure: find the common bit prefix

```
192.168.0.0     11000000.10101000.000000|00.00000000
192.168.1.0     11000000.10101000.000000|01.00000000
192.168.2.0     11000000.10101000.000000|10.00000000
192.168.3.0     11000000.10101000.000000|11.00000000
                └───── 22 bits identical ─┘

summary: 192.168.0.0/22
```

Count the leading bits that are identical across every prefix; that count is the summary
prefix length. The summary address is the lowest network with the remaining bits zeroed.

### The alignment rule applies here too

A summary is only exact when the set of networks is **contiguous and aligned** to a power of
two. Otherwise the summary covers addresses you do not own:

```
10.1.5.0/24, 10.1.6.0/24, 10.1.7.0/24, 10.1.8.0/24

common prefix is only /21 → 10.1.0.0/21 covers 10.1.0.0 – 10.1.7.255
  — this both over-covers (.0 – .4 not owned) and under-covers (.8 excluded)

correct minimal set:
  10.1.5.0/24     (.5 alone — not aligned for anything larger)
  10.1.6.0/23     (.6 – .7 — 6 is a multiple of 2 ✓)
  10.1.8.0/24     (.8 alone)
```

Advertising a summary that covers addresses you do not own is a **black hole**: you attract
traffic for those destinations and then drop it. This is the mechanism behind accidental
BGP hijacks.

### Why it matters

Summarization is what keeps routing tables small — the same aggregation from the
`ipv4-addressing` entry, now computed by hand. It also **contains instability**: if a
`/24` inside a summarized `/22` flaps up and down, routers outside the summary never see it,
because the `/22` advertisement does not change. The flap stops at the summarization
boundary instead of propagating recalculations network-wide.

**This is the design argument for hierarchical addressing.** Allocate address space to
match topology — contiguous blocks per site, per building, per region — and summarization
becomes possible at every tier. Allocate randomly and no summary is ever exact, so every
subnet must be advertised individually forever.

---

## Q: What does this look like on real gear?

### The VLSM signal in the routing table

```
Router# show ip route
      192.168.1.0/24 is variably subnetted, 6 subnets, 4 masks
C        192.168.1.0/26    is directly connected, GigabitEthernet0/0
C        192.168.1.64/27   is directly connected, GigabitEthernet0/1
C        192.168.1.96/28   is directly connected, GigabitEthernet0/2
C        192.168.1.112/30  is directly connected, Serial0/0/0
C        192.168.1.116/30  is directly connected, Serial0/0/1
C        192.168.1.120/30  is directly connected, Serial0/1/0
```

**"variably subnetted, 6 subnets, 4 masks"** is IOS reporting VLSM directly — one major
network carved at four different prefix lengths. Seeing `1 mask` where you expect several
means a summarization or mask misconfiguration.

### Wildcard masks — required for OSPF and ACLs

Cisco's OSPF `network` statements and ACLs take the **wildcard mask** (the bitwise inverse
of the subnet mask), not the subnet mask:

```
subnet mask     255.255.255.192   (/26)
wildcard mask     0.  0.  0. 63
```

The conversion is `255 − each octet`, and the wildcard is always `block size − 1` in the
interesting octet:

```
Router(config)# router ospf 1
Router(config-router)# network 192.168.1.0   0.0.0.63  area 0    ← the /26
Router(config-router)# network 192.168.1.64  0.0.0.31  area 0    ← the /27
Router(config-router)# network 192.168.1.112 0.0.0.3   area 0    ← the /30
```

### Configuring a summary

```
Router(config)# interface GigabitEthernet0/0
Router(config-if)# ip summary-address eigrp 100 192.168.0.0 255.255.252.0
```

OSPF summarizes at area boundaries instead, which is why OSPF area design and address
allocation must be planned together:

```
Router(config-router)# area 1 range 192.168.0.0 255.255.252.0
```

### Python — mechanising the whole procedure

```python
import ipaddress

pool = ipaddress.ip_network("192.168.1.0/24")
requirements = [("Sales", 60), ("Engineering", 28), ("HR", 12),
                ("WAN1", 2), ("WAN2", 2), ("WAN3", 2)]

def prefix_for(hosts):
    for p in range(30, 0, -1):                 # smallest block that fits
        if (2 ** (32 - p)) - 2 >= hosts:
            return p
    raise ValueError("no prefix fits")

cursor = pool.network_address
for name, hosts in sorted(requirements, key=lambda r: -r[1]):   # largest first
    net = ipaddress.ip_network(f"{cursor}/{prefix_for(hosts)}")
    print(f"{name:<12} {hosts:>3} hosts  {net}  usable {net.num_addresses - 2}")
    cursor = net.broadcast_address + 1

# Sales         60 hosts  192.168.1.0/26     usable 62
# Engineering   28 hosts  192.168.1.64/27    usable 30
# HR            12 hosts  192.168.1.96/28    usable 14
# WAN1           2 hosts  192.168.1.112/30   usable 2
# WAN2           2 hosts  192.168.1.116/30   usable 2
# WAN3           2 hosts  192.168.1.120/30   usable 2
```

Largest-first is what keeps `cursor` aligned at every step — the loop needs no alignment
logic because the ordering guarantees it.

Summarization has a stdlib primitive:

```python
nets = [ipaddress.ip_network(f"192.168.{i}.0/24") for i in range(4)]
list(ipaddress.collapse_addresses(nets))
# [IPv4Network('192.168.0.0/22')]

nets = [ipaddress.ip_network(f"10.1.{i}.0/24") for i in (5, 6, 7, 8)]
list(ipaddress.collapse_addresses(nets))
# [IPv4Network('10.1.5.0/24'), IPv4Network('10.1.6.0/23'), IPv4Network('10.1.8.0/24')]
```

`collapse_addresses` returns the **minimal exact set** — it never over-covers, which is the
correct and safe behaviour.

---

## Deeper — edge cases and gotchas

**Anti-pattern: allocating smallest-first.** It does not produce wrong addresses, but it
strands fragments that must be tracked manually, and a later large request may find no
aligned space even when the free-address total is sufficient. Descending order costs
nothing and removes the problem.

**Anti-pattern: summarizing address space you do not own.** An inexact summary attracts
traffic for destinations you cannot deliver and silently drops it. Always verify the summary
covers exactly the owned set — `collapse_addresses` or a hand check of the block boundaries.

**Alignment violations overlap, they do not error.** `192.168.1.100/28` is accepted by
config parsers and silently means `192.168.1.96/28`. If `.96/28` is already allocated, two
subnets now claim the same addresses. Verify every network address is a multiple of its
block size.

**Summarization hides flapping — which is both the benefit and the risk.** Instability
inside a summarized block stops at the boundary, which protects the wider network. It also
means a failed subnet inside the summary is invisible from outside, and traffic keeps being
attracted to the summarizing router. Summarize where you have an alternate path or where the
failure is genuinely local.

**Cloud has no VLSM constraint but the same discipline applies.** AWS subnets within a VPC
can each carry any prefix length, so VLSM is automatic. What is not automatic is planning:
subnets are immutable after creation, so an under-sized subnet means creating a new one and
migrating resources. Size generously — address space inside an RFC 1918 block is free.

**The `/31` and `/30` choice on WAN links compounds.** Six point-to-point links at `/30`
consume 24 addresses; at `/31` they consume 12. On a small `/24` carve that difference is
the margin between fitting and not.

---

## Recall

1. You hold `172.16.0.0/22` and must allocate: Building A 500 hosts, Building B 200 hosts,
   Building C 100 hosts, Building D 50 hosts, and two WAN links of 2 hosts each. Produce the
   full allocation — network address and prefix for each — and state what remains free.
2. Is `10.20.30.40/29` a valid subnet definition? If not, what does it actually mean?
3. Summarize `10.1.4.0/24`, `10.1.5.0/24`, `10.1.6.0/24`, `10.1.7.0/24` into a single prefix.
   Show the bit reasoning.
4. Now try to summarize `10.1.5.0/24`, `10.1.6.0/24`, `10.1.7.0/24`, `10.1.8.0/24` into a
   single prefix. What goes wrong, and what is the correct minimal set?
5. A network runs RIPv1. An engineer configures `192.168.1.0/26` on one interface and
   `192.168.1.64/27` on another. What specifically breaks, and why?
6. Why does allocating largest-first remove the need to check alignment at each step?

---

## Clarifications

### 1. Alignment is a property of the (address, prefix) pair — never of the address alone

The test is divisibility by the block size, not whether the number "looks round."

```
10.20.30.40/29   block  8  →  40 ÷  8 = 5     ✓ VALID
                              network .40, broadcast .47, usable .41 – .46

10.20.30.40/28   block 16  →  40 ÷ 16 = 2.5   ✗ INVALID
                              silently means 10.20.30.32/28
```

Same address, different prefix, opposite verdicts. An address that looks arbitrary can be
perfectly aligned, and a round-looking one can be misaligned. Always divide.

### 2. Why largest-first works — the divisibility argument

The procedure is correct because of a one-line fact, not a convention:

> After allocating a block of size 2ⁿ, the next free address is a **multiple of 2ⁿ**.
> Every smaller block size 2ᵐ (m < n) **divides** 2ⁿ.
> Therefore that address is automatically a multiple of 2ᵐ — already aligned for anything
> smaller.

```
finish a /26 (block 64) → next free is a multiple of 64
64 is divisible by 32, 16, 8, 4, 2
→ a multiple of 64 is automatically a multiple of all of them
→ any smaller block may legally start there; no check is needed
```

The reverse fails for the same reason:

```
finish a /30 (block 4) → next free is a multiple of 4
4 is NOT divisible by 64
→ a multiple of 4 need not be a multiple of 64
→ a /26 may have nowhere legal to start
```

This is why a largest-first allocation loop needs no alignment logic at all — descending
order makes alignment a theorem rather than a per-step check.

### 3. RIPv1 + VLSM: the concrete failure, traced both directions

RIPv1 advertises a **bare subnet number with no mask**. Per RFC 2453 the receiver must
assume "the subnet mask of the interface over which the route was learned." With two masks
in one major network, at least one route installs wrong.

```
R1: Gi0/0 = 192.168.1.0/26        Gi0/1 = 192.168.1.64/27
    (note: these are ADJACENT, not nested — .0/26 is .0–.63, .64/27 is .64–.95)

Under-covering direction:
  R1 advertises "192.168.1.0" out Gi0/1 (a /27 interface)
  R2 applies its interface mask → installs 192.168.1.0/27  → covers .0 – .31
  actual subnet is .0 – .63
  → hosts .32 – .63 are BLACK HOLED

Over-covering direction:
  R1 advertises "192.168.1.64" out a /26 interface
  R2 installs 192.168.1.64/26 → covers .64 – .127
  actual subnet is .64 – .95
  → R2 attracts traffic for .96 – .127 and drops it
```

**The general statement:** RIPv1 is correct only when every subnet of a major network shares
one mask. This is not a bug — it is the definition of a classful protocol, and it is exactly
why VLSM had to wait for RIPv2/EIGRP/OSPF. **VLSM is a protocol capability, not a
configuration option.**

Cisco's RIPv1 adds a defensive behaviour: when a route's mask differs from the outgoing
interface's mask, it suppresses the subnet and advertises the classful `192.168.1.0/24`
instead. Safer, but all subnet visibility is lost — the failure changes shape rather than
disappearing.

### 4. An inexact summary can fail in both directions at once

```
summarizing 10.1.5.0/24, 10.1.6.0/24, 10.1.7.0/24, 10.1.8.0/24

5, 6, 7, 8 → 00000101, 00000110, 00000111, 00001000
             └ only 5 common bits ┘ → /21

10.1.0.0/21 covers 10.1.0.0 – 10.1.7.255
  over-covers   .0 – .4   ← not owned, yet traffic is attracted → black hole
  under-covers  .8        ← owned, yet excluded from the advertisement
```

`.5` cannot join a larger block because 5 is odd — the smallest aligned block containing it
is a `/24`. `.8` sits on the far side of a `/21` boundary. The gap is **structural**; no
cleverer single summary exists. The minimal exact set is
`10.1.5.0/24` + `10.1.6.0/23` + `10.1.8.0/24`.
