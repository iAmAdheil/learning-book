---
slug: subnetting
title: Subnetting — CIDR Notation, Masks & Calculating Subnets by Hand
topic: networks
bloom-level: some
created: 2026-08-05
updated: 2026-08-08
published: null
related: [ipv4-addressing, vlans, arp, how-internet-works, osi-model, vlsm, routing-fundamentals]
tags: [layer-3, subnetting, cidr, subnet-mask, prefix-length, block-size, magic-number, borrowing-bits, subnet-zero, broadcast-address, network-address, host-count, vlsm, ipaddress-module]
sources:
  - "RFC 950 — Internet Standard Subnetting Procedure (1985) — https://www.rfc-editor.org/rfc/rfc950.txt — fetched 2026-08-05"
  - "RFC 4632 — CIDR: The Internet Address Assignment and Aggregation Plan (2006) — https://www.rfc-editor.org/rfc/rfc4632.txt — fetched 2026-08-03"
  - "RFC 1812 — Requirements for IP Version 4 Routers (1995) — https://www.rfc-editor.org/rfc/rfc1812.txt — fetched 2026-08-05"
  - "RFC 3021 — Using 31-Bit Prefixes on IPv4 Point-to-Point Links (2000) — referenced, not fetched"
---

## Answer

**The concept:** Subnetting is **borrowing bits from the host portion of an address to create
additional network bits**, splitting one network into several smaller ones. The mask is the
only tool involved — move the network/host boundary right, and you trade host capacity for
subnet count.

```
192.168.1.0/24    one network, 254 hosts
                  11000000.10101000.00000001.|00000000
                                             ↑ boundary

192.168.1.0/26    borrow 2 bits → four networks, 62 hosts each
                  11000000.10101000.00000001.00|000000
                                               ↑ boundary moved right 2

  192.168.1.0/26   →  .0   – .63    (usable .1   – .62)
  192.168.1.64/26  →  .64  – .127   (usable .65  – .126)
  192.168.1.128/26 →  .128 – .191   (usable .129 – .190)
  192.168.1.192/26 →  .192 – .255   (usable .193 – .254)
```

It is a **zero-sum trade**. There are only 32 bits:

```
subnets = 2^s              s = bits borrowed
hosts   = 2^h − 2          h = bits remaining
s + h   = 32 − original prefix length
```

---

## Q: Why does subnetting exist at all?

RFC 950 (1985) — this predates CIDR by eight years and is where the subnet mask was born.

### The problem before subnets

The original internet had a **two-level hierarchy**: network number, then host. One network
number meant **one physical network** — one cable. But organizations needed multiple
physical networks for reasons RFC 950 lists directly:

- different LAN technologies on one campus (Ethernet vs. ring)
- technical limits on host count and cable length
- congestion requiring hosts be split into separate segments
- geographic separation requiring point-to-point links between buildings

The obvious workaround — request a separate network number per cable — was destructive.
RFC 950's own words:

> "Information about the internal details of local connectivity is propagated everywhere,
> although it is of little or no use outside the local organization."

Every internal cable a company added would add a route to **every router on the internet**.
This is the same routing-table pressure that later produced CIDR, appearing eight years
earlier at the organizational scale.

### The solution: a third level

Split the local (host) field into **subnet** + **host**, using a 32-bit mask. RFC 950
requires "that the subnet bits be contiguous and located as the most significant bits of
the local address" — the same contiguity rule CIDR later inherited.

```
classful:    | network | host           |
subnetted:   | network | subnet | host  |
```

### The locality principle — the real payoff

Subnet structure is **invisible outside the organization**. A company holding a Class B
subnetted into 256 /24s still advertises **one** route to the world. Internally it has 256
networks; externally it has one.

This is worth stating precisely, because it reframes both concepts:

> **Subnetting and route aggregation are the same mechanism pointed in opposite directions.**
> Subnetting splits a prefix into more-specific prefixes for internal use.
> Aggregation merges more-specific prefixes into one for external advertisement.
> Both are just "move the mask boundary." The direction depends on who is looking.

---

## Q: How do you calculate subnets by hand?

There is exactly one technique worth learning, and it removes binary conversion from the
critical path.

### The block-size (magic number) method

1. **Find the interesting octet** — the one where the mask is neither 255 nor 0.
2. **Block size = 256 − (mask value in that octet).**
3. **Count multiples of the block size** from 0. The largest multiple ≤ the address's value
   in that octet is the **network address**.
4. **Broadcast = next boundary − 1.** Usable range is everything between, exclusive.

### The table to memorize

Fourth-octet subnetting (the common case):

| Prefix | Mask | Block | Subnets from /24 | Usable hosts |
|---|---|---|---|---|
| /24 | 255.255.255.0 | 256 | 1 | 254 |
| /25 | 255.255.255.128 | 128 | 2 | 126 |
| /26 | 255.255.255.192 | 64 | 4 | 62 |
| /27 | 255.255.255.224 | 32 | 8 | 30 |
| /28 | 255.255.255.240 | 16 | 16 | 14 |
| /29 | 255.255.255.248 | 8 | 32 | 6 |
| /30 | 255.255.255.252 | 4 | 64 | 2 |
| /31 | 255.255.255.254 | 2 | 128 | 2 (P2P only, RFC 3021) |
| /32 | 255.255.255.255 | 1 | 256 | 1 (host route) |

Third-octet subnetting uses the identical block values, one octet left — and the block is
counted in **whole /24s**:

| Prefix | Mask | Block (3rd octet) | Usable hosts |
|---|---|---|---|
| /23 | 255.255.254.0 | 2 | 510 |
| /22 | 255.255.252.0 | 4 | 1,022 |
| /21 | 255.255.248.0 | 8 | 2,046 |
| /20 | 255.255.240.0 | 16 | 4,094 |
| /19 | 255.255.224.0 | 32 | 8,190 |
| /18 | 255.255.192.0 | 64 | 16,382 |
| /17 | 255.255.128.0 | 128 | 32,766 |
| /16 | 255.255.0.0 | 256 | 65,534 |

The mask octet values never change: **128, 192, 224, 240, 248, 252, 254, 255**. Only which
octet they land in changes.

### Worked example — fourth octet

```
192.168.10.57/26

interesting octet: 4th (mask = 192)
block size:        256 − 192 = 64
boundaries:        0, 64, 128, 192
57 falls in:       the 0 block

network    192.168.10.0
broadcast  192.168.10.63          (next boundary 64, minus 1)
usable     192.168.10.1 – .62
hosts      2^6 − 2 = 62
```

### Worked example — third octet

```
10.5.68.200/21

interesting octet: 3rd (mask = 248)
block size:        256 − 248 = 8
boundaries:        0, 8, 16, … 56, 64, 72
68 falls in:       the 64 block

network    10.5.64.0
broadcast  10.5.71.255            (next boundary 10.5.72.0, minus 1)
usable     10.5.64.1 – 10.5.71.254
hosts      2^11 − 2 = 2,046
```

Note the shape: when the interesting octet is the third, the fourth octet runs its full
0–255 range inside each block. The broadcast address ends in `.255` and the network ends
in `.0`, but those are **consequences of the arithmetic**, not rules.

---

## Q: How do you design a subnet plan?

Two directions, and real requirements usually arrive as one or the other.

### Direction A — "I need N subnets"

Borrow `s` bits where `2^s ≥ N`.

```
Given 192.168.50.0/24, need 12 subnets.

2^3 = 8   too few
2^4 = 16  ≥ 12  ✓

borrow 4 → /28
16 subnets of 2^4 − 2 = 14 usable hosts each
boundaries every 16: .0, .16, .32, .48, .64 …
```

### Direction B — "I need N hosts per subnet"

Keep `h` bits where `2^h − 2 ≥ N`.

```
Given 172.16.0.0/16, need 500 hosts per subnet, maximum subnet count.

2^8 − 2 = 254   too few
2^9 − 2 = 510   ≥ 500  ✓

keep 9 host bits → /23
subnets = 2^(23−16) = 2^7 = 128
```

### The tension between them

The two directions rarely agree. "8 subnets of 500 hosts" from a /24 is impossible — a /24
holds 254 addresses total. And a uniform split wastes badly when subnets differ in size: a
point-to-point router link needs 2 addresses, and giving it a /24 wastes 252.

**That mismatch is exactly what VLSM solves** — allocating different prefix lengths within
one network, sized per segment. It is the next topic, and it is only possible because CIDR
made the mask explicit.

### The design rule that connects this to L2

> **One VLAN = one subnet = one broadcast domain.**

These three are different names for the same boundary seen at different layers. A VLAN is
the L2 boundary; a subnet is the L3 boundary; they are configured to coincide because a
host's on-link/off-link decision (its mask) must agree with what the switch will actually
deliver. Mismatching them produces hosts that believe they are on-link with peers the
switch will never deliver to.

---

## Q: Which addresses are actually usable? (the .0 and .255 trap)

The single most common subnetting error is believing that **an address ending in `.0` is a
network address and one ending in `.255` is a broadcast address.** That is only true at
exactly `/24`.

Network and broadcast are defined by **host bits all-zero and all-one**, which depends
entirely on the prefix length.

```
172.16.4.0/22

network    172.16.4.0
broadcast  172.16.7.255
usable     172.16.4.1 – 172.16.7.254
```

Inside that range:

| Address | Valid host? | Why |
|---|---|---|
| `172.16.4.0` | ✗ | it *is* the network address here |
| `172.16.5.0` | ✓ | host bits are `00000001 00000000` — not all zero |
| `172.16.5.255` | ✓ | host bits are `00000001 11111111` — not all ones |
| `172.16.7.255` | ✗ | host bits all ones — the broadcast |

`172.16.5.0` and `172.16.5.255` are perfectly ordinary, assignable host addresses. DHCP
pools spanning a /22 hand them out routinely. Refusing to assign them is a real and common
waste born of /24-shaped intuition.

---

## Q: What is "subnet zero" and why do old materials forbid it?

RFC 950 stated:

> "The values of all zeros and all ones in the subnet field should not be assigned to
> actual (physical) subnets."

The reasoning was ambiguity in a classful world. Given `192.168.1.0/24` split into /26s,
the first subnet is `192.168.1.0/26` — whose network address is *identical in dotted
decimal* to the parent network `192.168.1.0/24`. Without an explicit mask on the wire, a
router could not tell which was meant. The all-ones subnet had the mirror problem with the
parent's broadcast address.

**CIDR dissolved the ambiguity** by carrying the mask, so both restrictions are obsolete.
Cisco's `ip subnet-zero` was the configuration knob, and it has been **enabled by default
since IOS 12.0**. Modern practice uses all subnets.

Two legacy artifacts survive, and both are exam traps:

- Old materials compute subnet count as **2^s − 2**. Modern (and correct) is **2^s**. The
  host formula `2^h − 2` is unchanged and still correct — network and broadcast addresses
  are still reserved *within* each subnet.
- The `− 2` applies to **hosts within a subnet**, never to the **number of subnets**.
  Conflating the two is the most common arithmetic error on this topic.

---

## Q: What does this look like in practice?

### Cisco IOS

```
Router(config)# interface GigabitEthernet0/0
Router(config-if)# ip address 192.168.10.1 255.255.255.192
Router(config-if)# description Subnet 192.168.10.0/26 - Engineering
Router(config-if)# no shutdown
```

Verify what the router derived:

```
Router# show ip interface GigabitEthernet0/0 | include Internet
  Internet address is 192.168.10.1/26
  Broadcast address is 255.255.255.255
  Address determined by setup command
```

And the resulting routes — one address, two entries:

```
Router# show ip route | begin 192.168
      192.168.10.0/24 is variably subnetted, 2 subnets, 2 masks
C        192.168.10.0/26 is directly connected, GigabitEthernet0/0
L        192.168.10.1/32 is directly connected, GigabitEthernet0/0
```

The `C` route is the **subnet**; the `L` route is the router's own interface as a host
route. "Variably subnetted, 2 masks" is IOS reporting that this network is carved at more
than one prefix length — the VLSM signal.

### Linux

```
$ ipcalc 10.5.68.200/21
Address:   10.5.68.200          00001010.00000101.01000 100.11001000
Netmask:   255.255.248.0 = 21   11111111.11111111.11111 000.00000000
Wildcard:  0.0.7.255            00000000.00000000.00000 111.11111111
=>
Network:   10.5.64.0/21         00001010.00000101.01000 000.00000000
HostMin:   10.5.64.1            00001010.00000101.01000 000.00000001
HostMax:   10.5.71.254          00001010.00000101.01000 111.11111110
Broadcast: 10.5.71.255          00001010.00000101.01000 111.11111111
Hosts/Net: 2046
```

The space in the binary column marks the mask boundary — a good way to check hand
calculations while the block-size method is still becoming automatic.

Note the **wildcard mask** (`0.0.7.255`) — the bitwise inverse of the subnet mask. It is
what Cisco ACLs and OSPF `network` statements take instead of a subnet mask, so the
conversion is worth internalizing now: `255.255.248.0` → `0.0.7.255`.

### Python — `ipaddress` (stdlib)

```python
import ipaddress

net = ipaddress.ip_network("10.5.64.0/21")
net.network_address      # IPv4Address('10.5.64.0')
net.broadcast_address    # IPv4Address('10.5.71.255')
net.num_addresses        # 2048
net.netmask              # IPv4Address('255.255.248.0')
net.hostmask             # IPv4Address('0.0.7.255')   ← the wildcard mask

# split a block — the design operation, in one call
list(net.subnets(new_prefix=24))
# [IPv4Network('10.5.64.0/24'), ..., IPv4Network('10.5.71.0/24')]   8 subnets

# which network does a host belong to?
ipaddress.ip_interface("10.5.68.200/21").network   # IPv4Network('10.5.64.0/21')

# membership and overlap — the VPC-peering check, mechanised
ipaddress.ip_address("10.5.70.9") in net           # True
net.overlaps(ipaddress.ip_network("10.5.0.0/16"))  # True
```

`overlaps()` is the programmatic form of the CIDR-collision check from the `ipv4-addressing`
entry — worth wiring into infrastructure CI to reject a VPC or subnet definition that
collides with an existing allocation before it is applied.

---

## Deeper — edge cases and gotchas

**A mask is a local decision; nothing enforces agreement.** Two hosts on one wire with
different masks produce asymmetric, direction-dependent connectivity. `10.1.1.10/24` thinks
`10.1.1.200` is on-link and ARPs for it directly; `10.1.1.200/26` thinks `10.1.1.10` is
off-link and replies via the gateway. Traffic flows one way directly and the other way via
a router — or fails entirely if the router lacks an interface in both.

**Subnetting does not reduce broadcast traffic by itself — the L2 boundary does.** Putting
two subnets on one VLAN gains nothing: broadcasts still reach every port because the switch
floods within a VLAN regardless of IP. The reduction comes from `one VLAN = one subnet`,
where the L2 flooding domain and the L3 subnet coincide.

**Anti-pattern: sizing subnets to current host count.** A /29 that exactly fits today's 6
servers has no room, and renumbering a live subnet is an outage. Conventional practice is
to size for roughly 2× projected peak, and to keep the plan on nibble boundaries (/20, /24,
/28) where the arithmetic is legible to humans reading it at 3 a.m.

**Anti-pattern: reusing the same /24 shape everywhere.** A point-to-point router link given
a /24 wastes 252 addresses. Use /30, or /31 per RFC 3021. Uniform sizing is the problem
VLSM exists to solve.

**Cloud subnets are not L2 segments.** An AWS subnet is a routing construct, not a broadcast
domain — there is no broadcast or multicast in a VPC at all. The `− 2` intuition also fails:
AWS reserves **five** addresses per subnet (network, VPC router `.1`, DNS `.2`, a reserved
`.3`, and broadcast), so a `/28` yields 11 usable, not 14. Carrying LAN intuition into a VPC
silently under-provisions small subnets.

**The `− 2` never applies to subnet count.** `2^s` subnets, `2^h − 2` hosts. Materials
written before subnet zero became default teach `2^s − 2` and are wrong on modern gear.

---

## Recall

1. `172.20.140.99/21` — give the network address, broadcast address, usable range, and host
   count.
2. `192.168.200.130/25` — same four values.
3. You hold `192.168.50.0/24` and need **12 subnets**. What prefix, and how many usable
   hosts per subnet?
4. You hold `172.16.0.0/16` and need **at least 500 hosts per subnet** while maximising the
   number of subnets. What prefix, and how many subnets?
5. Are `10.1.1.100/27` and `10.1.1.130/27` on the same subnet? Show the reasoning.
6. Is `172.16.5.0/22` a valid, assignable host address? Is `172.16.5.255/22`? Explain both.
7. A host is configured `192.168.1.200/26` with default gateway `192.168.1.193`. Is this a
   valid configuration?
8. Why does a `/30` waste 50% of its addresses on a router-to-router link, and what are the
   two ways to avoid that waste?

---

## Clarifications

### 1. The most common hand-calculation error: broadcast one block too high

The failure mode is finding the *next boundary* correctly and then writing `.255` into the
last octet instead of stepping back one address:

```
next boundary 172.20.144.0  →  172.20.144.255   ✗  (wrong — this is in the NEXT subnet)
next boundary 172.20.144.0  −1 → 172.20.143.255 ✓
```

The `− 1` must **borrow across the octet**. `172.20.144.0` minus one address is
`172.20.143.255`.

**Better formulation — compute the broadcast directly and skip the borrow entirely:**

> **Broadcast = network value + block − 1** in the interesting octet.
> Every octet to the *right* of it becomes `255`.

```
172.20.136.0/21     block 8    →  136 +   8 − 1 = 143  →  172.20.143.255
172.16.4.0/22       block 4    →    4 +   4 − 1 =   7  →  172.16.7.255
192.168.10.0/26     block 64   →    0 +  64 − 1 =  63  →  192.168.10.63
192.168.200.128/25  block 128  →  128 + 128 − 1 = 255  →  192.168.200.255
```

**Free self-check, usable on every calculation:**

> **A broadcast address can never sit on a block boundary.**

Boundaries are network addresses by definition. So if the broadcast's interesting octet is
a **multiple of the block size**, the calculation is wrong.

```
claimed broadcast 172.20.144.255, block 8  →  144 = 18 × 8   → multiple → WRONG
correct           172.20.143.255            →  143 not a multiple      → OK
```

**Why this matters beyond arithmetic.** An inflated broadcast inflates the perceived subnet
range. Believing `172.16.4.0/22` ends at `172.16.8.255` means believing `172.16.8.100` is
on-link — it is not, it belongs to the next `/22`. The host would ARP for it directly
instead of sending to the gateway, and the traffic silently fails. A broadcast miscalculation
is a self-inflicted mask mismatch.

### 2. A default gateway has no required position within the subnet

The only requirements are that the gateway address is (a) a **usable** address and (b) in
the **same subnet** as the host.

```
host 192.168.1.200/26  →  network .192, broadcast .255, usable .193 – .254
gateway .193 ✓    .194 ✓    .220 ✓    .254 ✓    — all equally valid
```

First-address (`.193`) and last-address (`.254`) are **conventions**, not rules. Being firm
on this matters diagnostically: the real failure to look for is a gateway in a *different*
subnet than the host, which is instantly fatal and easy to miss when the addresses look
similar.

### 3. Avoiding /30 waste: allocate at /31, or use unnumbered interfaces

A `/30` on a point-to-point link consumes 4 addresses to make 2 usable — 50% waste. Note the
correct framing: the fix is not to *subdivide* an existing `/30`, it is to **allocate at a
different prefix length in the first place.**

| Method | Addresses consumed | Notes |
|---|---|---|
| `/30` | 4 (2 usable) | The legacy default |
| **`/31`** (RFC 3021) | **2, both usable** | No network/broadcast concept on P2P links |
| **Unnumbered** | **0** | The link borrows an address from another interface |

```
Router(config)# interface Serial0/0/0
Router(config-if)# ip unnumbered Loopback0
```

An unnumbered interface has no address of its own and sources packets from the referenced
interface — conventionally a loopback, since a loopback never goes down with a physical
port. Standard on ISP backbones carrying thousands of point-to-point links, where even the
2 addresses a `/31` consumes multiply into real numbers.
