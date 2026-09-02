---
slug: ipv4-addressing
title: IPv4 Addressing — Structure, Classes (Historical) & Private Ranges (RFC 1918)
topic: networks
bloom-level: some
created: 2026-08-03
updated: 2026-08-08
published: null
related: [arp, encapsulation-decapsulation, osi-model, how-internet-works, tcp-ip-model, subnetting, vlsm, routing-fundamentals]
tags: [layer-3, ipv4, ip-address, addressing, cidr, prefix, subnet-mask, classful, rfc1918, private-address, loopback, link-local, apipa, cgnat, longest-prefix-match, route-aggregation, dotted-decimal]
sources:
  - "RFC 791 — Internet Protocol (1981), §3.2 Addressing — https://www.rfc-editor.org/rfc/rfc791.txt — fetched 2026-08-03"
  - "RFC 1918 — Address Allocation for Private Internets (1996) — https://www.rfc-editor.org/rfc/rfc1918.txt — fetched 2026-08-03"
  - "RFC 4632 — CIDR: The Internet Address Assignment and Aggregation Plan (2006) — https://www.rfc-editor.org/rfc/rfc4632.txt — fetched 2026-08-03"
  - "RFC 6890 — Special-Purpose IP Address Registries (2013) — https://www.rfc-editor.org/rfc/rfc6890.txt — fetched 2026-08-03"
  - "RFC 3021 — Using 31-Bit Prefixes on IPv4 Point-to-Point Links (2000) — https://www.rfc-editor.org/rfc/rfc3021.txt — referenced, not fetched"
  - "RFC 3927 — Dynamic Configuration of IPv4 Link-Local Addresses (2005) — https://www.rfc-editor.org/rfc/rfc3927.txt — referenced, not fetched"
  - "RFC 6598 — IANA-Reserved IPv4 Prefix for Shared Address Space (2012) — https://www.rfc-editor.org/rfc/rfc6598.txt — referenced, not fetched"
---

## Answer

**The concept:** An IPv4 address is a **32-bit number** that identifies a *network interface*
and is split by a **mask** into a **network portion** (shared by everyone on the same link)
and a **host portion** (unique within that link). That split is the entire point: routers
memorize *networks*, not hosts. Without it, every router on Earth would need a table of
4.29 billion entries.

RFC 791 §3.2 states the framing that still governs L3 thinking:

> "A name indicates **what** we seek. An address indicates **where** it is. A route indicates
> **how** to get there."

An IP address is the *where*. DNS supplies the *what*. Routing protocols supply the *how*.

### Dotted decimal is a human convenience

The wire format is 32 raw bits. Dotted decimal just chunks them into four 8-bit octets
(0–255) for readability.

```
  192  .  168  .   10   .   57
11000000.10101000.00001010.00111001
= 3232238137 as a single unsigned 32-bit integer
```

Every addressing question — masks, subnets, ranges, "is this address in that network?" —
becomes obvious in binary and mysterious in decimal. Fluency in binary octets is the
single highest-leverage skill in L3.

### The address belongs to the interface, not the host

RFC 791 is explicit: a host "may have several physical interfaces... with each having
several logical internet addresses." This is the mental-model shift from L2:

- A **MAC** is burned into one NIC — flat, global, permanent, location-independent.
- An **IP** is *assigned* to an interface and describes **where that interface currently
  sits in the topology**. Move the machine to a different network and the IP must change;
  the MAC does not.

A router with 4 interfaces has (at least) 4 IP addresses — one per attached network. It is
a member of every network it touches.

### Network portion vs host portion — the mask

The mask is a run of contiguous `1` bits marking the network portion, followed by `0` bits
marking the host portion. Two equivalent notations:

```
dotted-decimal mask:  255.255.255.0
CIDR prefix length:   /24            ← 24 leading 1-bits
```

Applying it:

```
address    192.168.10.57    11000000.10101000.00001010.00111001
mask /24   255.255.255.0    11111111.11111111.11111111.00000000
                            └────── network (24) ──────┘└host(8)┘

network address  (host bits all 0)  192.168.10.0     ← names the network itself
broadcast address(host bits all 1)  192.168.10.255   ← "everyone on this network"
usable host range                   192.168.10.1 – .254   (2^8 − 2 = 254)
```

**The −2 rule:** the all-zeros host value names the network (it is what appears in a
routing table) and the all-ones host value is the directed broadcast. Neither can be
assigned to an interface, so a /24 gives 254 usable addresses, not 256.

### Only nine octet values ever appear in a mask

Because the mask is contiguous ones, each octet can only be:

```
/0 →   0    00000000
/1 → 128    10000000
/2 → 192    11000000
/3 → 224    11100000
/4 → 240    11110000
/5 → 248    11111000
/6 → 252    11111100
/7 → 254    11111110
/8 → 255    11111111
```

Memorize this column. `255.255.255.192` is instantly `/26`; `/26` is instantly
"block size 64".

### A non-octet-boundary worked example

```
host: 172.16.5.130/26
mask: 255.255.255.192            block size = 256 − 192 = 64

subnet boundaries in the 4th octet: 0, 64, 128, 192
130 falls in the .128 block

network    172.16.5.128
first host 172.16.5.129
last host  172.16.5.190
broadcast  172.16.5.191
usable     62 hosts  (2^6 − 2)
```

The "block size = 256 − mask octet" trick is how subnetting is done by hand under exam
time pressure. (Full treatment lives in the subnetting entry.)

---

## Q: What was classful addressing and why was it abandoned?

### The original design (RFC 791, 1981)

The 1981 spec did not have masks. The **leading bits of the address itself** declared how
the network/host split worked:

| Class | Leading bits | Net bits | Host bits | First-octet range | Networks | Hosts each |
|---|---|---|---|---|---|---|
| A | `0` | 7 | 24 | 1–126 | 126 | 16,777,214 |
| B | `10` | 14 | 16 | 128–191 | 16,384 | 65,534 |
| C | `110` | 21 | 8 | 192–223 | 2,097,152 | 254 |
| D | `1110` | — | — | 224–239 | multicast | — |
| E | `1111` | — | — | 240–255 | reserved | — |

Historical precision: RFC 791 defined only A, B, and C. It labelled the `111` space an
"escape to extended addressing mode" that was left undefined. **Class D (multicast)** was
defined later (RFC 988 → RFC 1112), and **Class E** was fenced off as reserved. So "the
five classes" is a retroactive tidy-up, not the original text.

Note the gaps: `0.x` was "this network" and `127.x` became loopback, which is why Class A
yields 126 usable networks rather than 128.

Under this scheme the mask was **implicit** — a router seeing `10.1.1.1` knew from the
leading `0` bit that the network was `10.0.0.0/8`, with no mask carried anywhere.

### The three problems that killed it (RFC 4632)

The IETF's ROAD group named exactly three, in 1992:

1. **Class B exhaustion.** The root cause named in RFC 4632 is "the lack of a network class
   of a size that is appropriate for mid-sized organization." An organization with 500 hosts
   found Class C (254 hosts) too small and Class B (65,534) grotesquely oversized — and took
   the Class B. Roughly 99% of a typical Class B was wasted.
2. **Routing-table growth.** Handing out thousands of individual Class C blocks instead
   meant thousands of separate routes in the global table, growing faster than router
   memory and CPU could absorb.
3. **IPv4 address-space depletion.** The 32-bit space itself running dry.

Problems 1 and 2 are in direct tension: fix waste by allocating smaller blocks, and you
explode the routing table. CIDR solves both at once.

### CIDR (RFC 1519 → RFC 4632, 1993)

**Carry the mask explicitly.** Once the prefix length travels with the address, the class
bits become meaningless and any power-of-two block size is available.

- That 500-host org gets a `/23` (510 usable) instead of a whole Class B — a ~128× saving.
- **Aggregation ("supernetting")** fixes the routing table from the other direction: an ISP
  allocated `203.0.0.0/16` hands `/24`s to 256 customers but advertises **one** `/16` route
  to the rest of the internet. 256 routes collapse to 1.
- Allocation becomes **topology-aligned** rather than size-aligned — addresses are handed
  down the provider hierarchy so they *can* aggregate.

**Longest-prefix match** is the forwarding rule that makes this work. When several routes
match a destination, the router picks the **most specific** (longest prefix):

```
destination 203.0.113.75

routing table:
  0.0.0.0/0        → ISP-A       (matches — 0 bits)
  203.0.0.0/16     → ISP-B       (matches — 16 bits)
  203.0.113.0/24   → Router-C    (matches — 24 bits)  ← WINS
```

This is what lets a specific customer route override the aggregate, and what makes
`0.0.0.0/0` a valid catch-all default route (it matches everything, with the fewest bits,
so it only wins when nothing else does).

RFC 4632 declares classful addressing **deprecated and obsolete** for internet routing.

### So why is it still taught?

Three reasons it survives in practice and on the CCNA:

1. **Vocabulary.** "A Class C block" is still spoken shorthand for a /24.
2. **Default masks on gear.** Cisco IOS still assumes a classful mask if you omit one, and
   `no auto-summary` exists in RIP/EIGRP precisely because classful auto-summarization was
   the default behaviour.
3. **RFC 1918's shape is classful.** The three private blocks are literally one Class A,
   sixteen Class Bs, and 256 Class Cs — the classes are fossilized in the ranges you use
   daily.

---

## Q: What are the RFC 1918 private ranges and why do they exist?

### The three blocks

| CIDR | Range | Size | Classful equivalent |
|---|---|---|---|
| `10.0.0.0/8` | 10.0.0.0 – 10.255.255.255 | 16,777,216 | one Class A |
| `172.16.0.0/12` | 172.16.0.0 – 172.31.255.255 | 1,048,576 | 16 contiguous Class Bs |
| `192.168.0.0/16` | 192.168.0.0 – 192.168.255.255 | 65,536 | 256 contiguous Class Cs |

RFC 1918 calls them the 24-bit, 20-bit, and 16-bit blocks (after the number of host bits).
The design intent is visible: **one block of each classful size**, so an organization picks
the one matching its scale.

The `172.16.0.0/12` boundary is the one people get wrong. It is `172.16` **through
`172.31`**, not through `172.16.255`, and not through `172.32`. In binary:

```
172.16.0.0/12   10101100.0001 0000.00000000.00000000
                └── 12 fixed ──┘
third-nibble range: 0001 0000 (16) … 0001 1111 (31)
```

### Why they exist

RFC 1918 gives two drivers:

1. **Address conservation.** Global uniqueness is only required for hosts that actually
   communicate globally. The RFC's own examples of hosts that don't: "cash registers, money
   machines, and equipment at clerical positions." Burning globally-unique space on a cash
   register is waste.
2. **Reuse.** Because these prefixes are never routed on the public internet, *every*
   organization can use `10.0.0.0/8` simultaneously with no conflict. The same address space
   is reused millions of times over.

### The routing contract

RFC 1918 is unambiguous:

> "routing information about private networks shall not be propagated on inter-enterprise
> links, and packets with private source or destination addresses should not be forwarded
> across such links."

ISPs filter these prefixes at their borders (this is one half of "bogon filtering"). The
consequence: a private-addressed host reaching the internet **must** be translated — this
is the direct motivation for **NAT/PAT**, covered in its own entry.

### The collision warning

RFC 1918 anticipates mergers and recommends organizations "choose randomly from the
reserved pool of private addresses when allocating sub-blocks" — precisely to reduce the
chance that two networks being joined both used `10.0.0.0/16`.

This is not a historical footnote. It is the single most common real-world failure in cloud
networking: **AWS/GCP VPCs with overlapping CIDRs cannot be peered.** Two teams that both
defaulted to `10.0.0.0/16` will discover this the day they need the VPCs to talk, and the
fix is renumbering. Pick deliberately-odd sub-blocks (`10.47.0.0/16`, not `10.0.0.0/16`).

---

## Q: What about the other reserved ranges — loopback, 169.254, 100.64, 0.0.0.0?

RFC 6890 consolidates every special-purpose block into one registry. The ones worth knowing:

| Block | Name | What it actually means |
|---|---|---|
| `0.0.0.0/8` | "This host on this network" | Valid as a **source only**. A DHCP client sends DISCOVER from `0.0.0.0` because it has no address yet. |
| `10.0.0.0/8` | Private-Use | Forwardable internally, never globally reachable. |
| `100.64.0.0/10` | Shared Address Space (CGNAT) | RFC 6598. ISP carrier-grade NAT space — between the subscriber and the ISP's NAT. |
| `127.0.0.0/8` | Loopback | The **entire /8**, not just `127.0.0.1`. Never valid on the wire; never source, never destination, never forwarded. |
| `169.254.0.0/16` | Link-Local (APIPA) | RFC 3927. Self-assigned when DHCP fails. Valid on the local link, **never forwarded**. |
| `172.16.0.0/12` | Private-Use | — |
| `192.0.2.0/24` | TEST-NET-1 (documentation) | Not valid as source or destination. Use in docs/examples. |
| `192.168.0.0/16` | Private-Use | — |
| `198.18.0.0/15` | Benchmarking | Reserved for device performance testing. |
| `198.51.100.0/24` | TEST-NET-2 | Documentation. |
| `203.0.113.0/24` | TEST-NET-3 | Documentation. |
| `240.0.0.0/4` | Reserved (former Class E) | Not usable; too much deployed hardware rejects it to reclaim. |
| `255.255.255.255/32` | Limited Broadcast | Valid destination only; **never forwarded** by a router. |

Practical readings:

- **See `169.254.x.x` on an interface → DHCP failed.** That single fact is a first-move
  diagnostic. The host self-assigned; there is no gateway; nothing off-link will work.
- **See `100.64.x.x` as your address → you are behind carrier-grade NAT.** Inbound
  connections are impossible without the ISP's cooperation. Increasingly common on mobile
  and residential fibre.
- **Use `192.0.2.0/24` in documentation**, never a real-looking address like `1.2.3.4`
  (which belongs to APNIC) — that is what TEST-NET exists for.

### The three meanings of 0.0.0.0

A genuine source of confusion, because context changes the meaning entirely:

```
1. As a source address     → "I have no address yet"  (DHCP DISCOVER)
2. As a bind/listen address → "all interfaces on this host"
3. As a route 0.0.0.0/0     → "every destination"      (the default route)
```

Meaning 2 is the classic backend bug. A server bound to `127.0.0.1` accepts only
connections originating on the same host; bound to `0.0.0.0` it accepts on every interface.

```python
sock.bind(("127.0.0.1", 8080))   # localhost only — unreachable from outside
sock.bind(("0.0.0.0",   8080))   # every interface — reachable from the network
```

This is *the* reason a containerized service appears dead from outside: the process inside
the container bound to loopback, so the container's own network interface never sees the
connection. The fix is always `0.0.0.0` inside a container.

---

## Q: What does this look like on real gear?

### Cisco IOS

```
Router(config)# interface GigabitEthernet0/0
Router(config-if)# ip address 192.168.10.1 255.255.255.0
Router(config-if)# no shutdown
Router(config-if)# exit
Router(config)# interface GigabitEthernet0/1
Router(config-if)# ip address 172.16.5.129 255.255.255.192
Router(config-if)# no shutdown
```

IOS wants the **dotted-decimal mask**, not `/24` — a common stumble coming from Linux.

```
Router# show ip interface brief
Interface              IP-Address      OK? Method Status                Protocol
GigabitEthernet0/0     192.168.10.1    YES manual up                    up
GigabitEthernet0/1     172.16.5.129    YES manual up                    up
GigabitEthernet0/2     unassigned      YES unset  administratively down down
```

`show ip interface brief` is the single most-used troubleshooting command on IOS. Read the
last two columns as a layered check: **Status** is L1/L2 (is the link physically up?),
**Protocol** is L3 (is the line protocol up?). `up/down` means cabling is fine but
something at L2 is wrong — encapsulation mismatch, no keepalives.

```
Router# show ip route
      172.16.0.0/16 is variably subnetted, 2 subnets, 2 masks
C        172.16.5.128/26 is directly connected, GigabitEthernet0/1
L        172.16.5.129/32 is directly connected, GigabitEthernet0/1
      192.168.10.0/24 is variably subnetted, 2 subnets, 2 masks
C        192.168.10.0/24 is directly connected, GigabitEthernet0/0
L        192.168.10.1/32 is directly connected, GigabitEthernet0/0
```

Note what the router stored: assigning **one** address created **two** routes. `C` is the
connected *network* (the aggregate it can reach out that port); `L` is the **local** /32
for the router's own interface address — how the router recognizes packets addressed to
itself. And the routing table stores the **network address**, never a host address. That is
the whole payoff of the network/host split.

### Linux

```
$ ip -4 addr show
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536
    inet 127.0.0.1/8 scope host lo
2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500
    inet 192.168.10.57/24 brd 192.168.10.255 scope global eth0

$ ip route
default via 192.168.10.1 dev eth0          ← this is 0.0.0.0/0
192.168.10.0/24 dev eth0 proto kernel scope link src 192.168.10.57
```

Linux shows CIDR natively and computes `brd` (broadcast) for you. `scope host` on loopback
means "never leaves this machine"; `scope link` means "reachable without a router";
`scope global` means routable.

The two-line route table is the complete decision procedure for an outgoing packet:
if the destination matches `192.168.10.0/24`, it is on-link — ARP for it directly. Otherwise
fall through to `default` and ARP for the **gateway's** MAC, not the destination's. That
handoff is exactly the boundary between this entry and the ARP entry.

---

## Q: Where does this actually bite in backend/cloud work?

- **VPC CIDR planning.** An AWS VPC takes an RFC 1918 block (`/16` conventional) carved into
  per-AZ subnets. The block is **immutable after creation** in practice, and overlapping
  blocks cannot be peered. Choose non-obvious sub-blocks so future peering/VPN stays possible.
- **AWS reserves 5 addresses per subnet, not 2.** Network address, VPC router (`.1`), DNS
  (`.2`), a reserved `.3`, and the broadcast address. A `/28` gives 11 usable, not 14.
- **Security groups and firewall rules are written in CIDR.** `10.0.0.0/8` in an ingress rule
  says "any host in the private block" — writing `/16` when you meant `/8` silently locks out
  half your fleet.
- **`X-Forwarded-For` and CGNAT.** Behind a load balancer the socket peer address is the LB's
  private IP, not the client's. And with `100.64.0.0/10` CGNAT upstream, thousands of distinct
  users can share one public IP — which quietly breaks per-IP rate limiting and IP-based
  geolocation.
- **Kubernetes runs three distinct address spaces.** Node CIDR, Pod CIDR, and Service CIDR
  must not overlap each other or the VPC. Most "my cluster can't reach the database" incidents
  are a Pod CIDR colliding with a VPC subnet.

---

## Deeper — edge cases and gotchas

**The /31 exception (RFC 3021).** The −2 rule wastes 50% of a point-to-point link: a `/30`
gives 4 addresses to hold 2 routers. RFC 3021 permits `/31` on point-to-point links, where
both addresses are usable because there is no meaningful broadcast — with exactly two
endpoints, "broadcast" and "the other guy" are the same thing. Standard practice on
router-to-router links.

**`/32` is legal and common.** A single host route. Loopback interfaces on routers are
configured as `/32` (used as a stable router ID for OSPF/BGP that never goes down with a
physical port), and it is what a `L` route in `show ip route` represents.

**Leading zeros are a real security bug.** `010.1.1.1` is parsed as octal by
`inet_aton()`-style parsers (→ `8.1.1.1`) but as decimal `10.1.1.1` by stricter ones. This
parser disagreement was CVE-2021-28918 and friends — an SSRF filter and the HTTP client it
guards can disagree about which host an address refers to. Normalize before comparing;
never string-match addresses.

**Anti-pattern: treating an IP as an identity.** IPs are *locations*, not identities. NAT,
CGNAT, DHCP lease churn, and mobile handoff all mean one IP maps to many users over time and
many users to one IP at any instant. IP-based authentication, per-IP rate limits, and
IP-based licensing all degrade badly under CGNAT.

**Anti-pattern: assuming private = secure.** RFC 1918 addresses are unroutable on the public
internet, which is *not* the same as unreachable. Anything already inside the perimeter — a
compromised container, a malicious dependency, an SSRF-able request handler — reaches
`10.x.x.x` freely. This is precisely why `169.254.169.254` (the cloud metadata endpoint, on
the link-local block) has been the payload of choice for SSRF attacks. Covered further in
the NAT-as-security-theater entry.

**The mask must be contiguous.** `255.255.0.255` is not a valid mask. CIDR requires a solid
run of ones; some ancient stacks tolerated non-contiguous masks, but no modern hardware or
routing protocol does.

---

## Recall

1. A host is configured `172.16.5.130/26`. Another host on the same switch is
   `172.16.5.100/26`. Can they talk directly without a router? Why or why not?
2. Why does `/24` give 254 usable addresses instead of 256 — and what exactly changes on a
   point-to-point `/31` that removes the penalty?
3. A colleague reports a server is "up but unreachable." `ip addr` shows
   `inet 169.254.11.203/16`. What has failed, and what would you check first?
4. Two teams each built a VPC on `10.0.0.0/16` and now need them peered. What breaks, and
   what does RFC 1918 recommend that would have prevented it?
5. What would happen if CIDR had never been introduced — describe the effect on *both* the
   IPv4 address supply and the size of the global routing table.

---

## Clarifications

Six points that reliably trip people up, drawn from working the recall questions. The
unifying theme: most confusion about *addresses* is really confusion about the *routing
table*. A routing table maps a prefix to **exactly one** next hop — that single constraint
explains items 1, 4, and 5 below.

### 1. Private addresses are fully routable — just not *between* enterprises

A common worry: "if both hosts have private IPs, how does a router know which private
network is meant?"

It is not ambiguous. RFC 1918's restriction is specifically on **inter-enterprise links**.
Inside a single routing domain, private prefixes are ordinary routes with no NAT and no
special handling:

```
C    172.16.5.64/26  is directly connected, GigabitEthernet0/1
C    172.16.5.128/26 is directly connected, GigabitEthernet0/2
```

Private addressing is second-class **only at the internet border**, where the ISP filters
the prefixes and NAT must translate. Within one domain each prefix appears exactly once, so
there is nothing to disambiguate.

The ambiguity people intuit is real, but it only materializes when **two separate routing
domains that each used the same private block are joined** — see item 4.

### 2. Same wire, different subnets — the switch is not the blocker

Given `172.16.5.130/26` and `172.16.5.100/26` on the same switch:

```
/26 → block size 64 → boundaries .0, .64, .128, .192
  .100 → network 172.16.5.64   (range .64 – .127)
  .130 → network 172.16.5.128  (range .128 – .191)
```

Different networks, so they cannot talk directly — but note *where* the block occurs. The
switch never inspects IP and would forward a frame between them happily. The traffic is
stopped by the **sending host's own L3 decision**: it applies its mask, concludes the
destination is off-link, and ARPs for the default gateway instead. The packet travels
host → router → back out the same switch → host. Same cable, twice.

**Corollary — a mask mismatch produces asymmetric connectivity.** If one host were
misconfigured as `/24`, it would consider the other on-link and ARP for it directly; the
reply would arrive, so A→B works while B→A goes via the router. Half-working,
direction-dependent connectivity is the signature of a mask typo. The mask is a purely
local decision — nothing on the wire enforces agreement between hosts.

### 3. On a /31 there is no network address and no broadcast address

A frequent misconception is that a `/31`'s low address doubles as both a usable host
address *and* the network address. Neither is true — RFC 3021 **abolishes both concepts**
for that prefix length.

```
10.0.0.4/31
  10.0.0.4  → Router A's interface   (usable host)
  10.0.0.5  → Router B's interface   (usable host)
  network address: none      broadcast address: none      usable: 2 of 2
```

The underlying correction:

> **The network address is not how a router names the network. The *prefix* is.**

The routing-table entry is `10.0.0.4/31` — an (address, length) pair. It does not require a
burned address slot to exist. Reserving the all-zeros host value is a **convention**
inherited from stacks that once treated it as a broadcast form; RFC 3021 drops the
convention on point-to-point links and nothing breaks. The broadcast half of the
justification is independent: with exactly two endpoints, "broadcast to everyone" and
"unicast to the one peer" are the same packet, so the broadcast address carries zero
information.

**Why it matters at scale:** `/30` was the old P2P standard — 4 addresses to connect 2
routers, 50% waste. An ISP with 10,000 point-to-point links wastes 20,000 addresses on
nothing. `/31` halves it.

`/31` is restricted to point-to-point links because a multi-access segment may genuinely
need a subnet broadcast address — and with only 2 addresses, nothing larger fits anyway.
The same reasoning extends to `/32`: no network address, no broadcast, one host route.

### 4. Overlapping VPC CIDRs break peering via a longest-prefix-match tie

Two VPCs both on `10.0.0.0/16`. Peering them requires a route that already exists:

```
VPC-A route table:
  10.0.0.0/16  →  local          ← created with the VPC
  10.0.0.0/16  →  pcx-peering    ← the route that must be added
```

**Identical prefix lengths.** Longest-prefix match cannot break the tie — neither route is
more specific. AWS gives `local` absolute priority, and its API refuses to create a peering
route overlapping the VPC's own CIDR. A packet from VPC-A to `10.0.1.5` in VPC-B is
delivered to VPC-A's *own* `10.0.1.5`, or dropped. It never leaves.

This is a **longest-prefix-match failure**: one table cannot hold two meanings for one
prefix — the same constraint as item 1, seen from the failure side.

Prevention, restating RFC 1918's "choose randomly" for cloud practice — keep a central
address plan and give every VPC a deliberately unusual block:

```
10.20.0.0/16   prod      us-east-1
10.21.0.0/16   prod      eu-west-1
10.30.0.0/16   staging   us-east-1
10.40.0.0/16   dev
```

- **Never accept the console default `10.0.0.0/16`** — it is the maximum-collision choice
  precisely because it is the default.
- **Avoid `192.168.0.0/16` for corporate networks** — home routers and remote-worker LANs
  live there, and a VPN client on `192.168.1.0/24` cannot reach a VPC subnet of the same
  name (their local route wins, same tie-break).
- `172.16.0.0/12` is the least-used of the three and often safest.

Remediation once overlapping, all unpleasant: renumber one side (correct, requires
downtime); a private NAT gateway to translate the overlap (works, adds a second NAT layer);
or Transit Gateway with NAT. There is no clean fix — this is a planning problem.

### 5. Classful addressing has no *syntax* for aggregation — that is why CIDR exists

The address-waste problem (Class B too big, Class C too small) is the well-known half. The
routing-table half is the one that made it an emergency.

Because a classful router carries no mask, it **cannot express that several small networks
are one thing**:

```
Classful — 8 separate, permanently unmergeable global routes:
  201.10.1.0  201.10.2.0  201.10.3.0  201.10.4.0
  201.10.5.0  201.10.6.0  201.10.7.0  201.10.8.0

CIDR — one route, because the mask can be carried:
  201.10.0.0/21
```

By the early 1990s the global table was growing exponentially while routers did software
forwarding with small, expensive RAM. The projection was not "slower" but **failure** — the
table outgrowing installed hardware. The ROAD group formed against a credible date.

The two problems form a vice:

```
allocate smaller  →  fixes waste        →  explodes the routing table
allocate larger   →  keeps table small  →  burns the address space
```

CIDR escapes it because an explicit mask **decouples allocation size from advertisement
size**: a 500-host organization receives a right-sized `/23`, while its ISP advertises a
single `/19` covering 32 such customers. Today's global BGP table is on the order of a
million IPv4 routes and only reached that scale *with* aggregation.

Depletion (the third ROAD problem) was only ever deferred: CIDR bought time, RFC 1918 + NAT
bought much more, and IPv6 is the actual fix.

### 6. `169.254.0.0/16` on an interface means DHCP failed

Link-local addressing, RFC 3927 — **APIPA** on Windows, "self-assigned IP" on macOS. The
host asked for a lease, got no answer, and invented an address:

1. Broadcast DHCP DISCOVER with source `0.0.0.0` ("I have no address yet").
2. No offer arrives; times out.
3. Pick a pseudo-random address in `169.254.1.0 – 169.254.254.255` (first and last /24
   reserved).
4. **ARP probe** it to detect a conflict.
5. Silence → claim it. Reply → pick another and retry.

Consequences, which are what make it diagnostic:

- **No default gateway** — DHCP supplies it, and DHCP is what failed. Nothing off-link works.
- Per RFC 6890 the block is **not forwardable**; routers drop it. Same-wire only.
- Two hosts that both self-assigned *can* reach each other — so two broken machines pinging
  each other successfully is an expected, confusing symptom.

Triage in layer order:

| Layer | Check |
|---|---|
| L1 | Link actually up? (`ip link`, `show interface`) — cable, SFP, port |
| L2 | Port in the **correct VLAN**? Wrong VLAN → wrong DHCP scope, or none |
| L3 | DHCP server up? Pool **exhausted**? |
| L3 | Server on another subnet → is the **relay** configured (`ip helper-address`)? |

The relay case is the most common in a routed network: DHCP DISCOVER is a broadcast and
**routers do not forward broadcasts**, so a DHCP server on another subnet is unreachable
unless the router is explicitly configured to relay.

Related: `169.254.169.254` — the cloud metadata endpoint — sits in this block deliberately.
Link-local means never routed, so it is guaranteed to resolve to the local hypervisor and
cannot be spoofed from off-link. For the same reason it is the most-targeted SSRF payload
in existence.
