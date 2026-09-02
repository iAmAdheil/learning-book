---
slug: arp
title: ARP — Resolving IP → MAC, ARP Cache, Gratuitous ARP
topic: networks
bloom-level: some
created: 2026-07-12
updated: 2026-08-08
published: 2026-07-20
related: [ethernet, how-switches-work, vlans, how-internet-works, encapsulation-decapsulation, ipv4-addressing, subnetting, routing-fundamentals]
tags: [layer-2, arp, address-resolution, arp-cache, gratuitous-arp, arp-spoofing, mitm, broadcast, ndp, next-hop, default-gateway]
sources:
  - "RFC 826 — An Ethernet Address Resolution Protocol (1982)"
---

## Answer

**The concept:** ARP (**Address Resolution Protocol**, RFC 826) is the glue between the two
addressing worlds: the **IP** world (L3, logical, end-to-end) and the **MAC** world (L2,
physical, one-hop). Given a next-hop IP on the local link, it finds that host's MAC.

### The problem it solves

A host wants to send a packet. It knows the destination IP, its own IP and MAC — but **not the
destination MAC**. Per [[encapsulation-decapsulation]], you cannot put a frame on the wire without
a destination MAC. IP says *where ultimately*; the frame needs *who's physically next*. ARP
performs that translation: **next-hop IP → MAC**.

### The critical subtlety: ARP is only ever for the NEXT HOP

```
   "Is the destination IP on MY subnet?"
        │
   ┌────┴─────┐
  YES         NO
   │           │
 ARP for     ARP for
 the dest    the DEFAULT GATEWAY
 IP directly (the router)
```

A host reaching a *remote* server does **not** ARP for the server's MAC. It applies the L3 rule
("destination off-subnet → send to my default gateway") and **ARPs for the gateway's MAC**. So ARP
resolves the IP of the **next hop on the local link** — the final destination if local, the router
if remote. This is "IP is end-to-end, MAC is hop-to-hop" ([[how-internet-works]]) with the
resolution mechanism filled in, and it is why **ARP is subordinate to the L3 routing decision**:
the host picks the next-hop IP first, then ARP fetches its MAC.

### How it works: request and reply

```
 1. ARP REQUEST  (broadcast — dest MAC ff:ff:ff:ff:ff:ff)
    "Who has 192.168.1.1? Tell 192.168.1.10."
    → reaches EVERY device in the VLAN / broadcast domain
              │
    each device checks "is that IP me?" — all discard except the owner
              │
 2. ARP REPLY  (unicast — straight back to the asker)
    "192.168.1.1 is at a4:5e:60:12:34:56."
```

- **Request is broadcast** — the asker doesn't know the MAC yet, so it must ask everyone. This is
  why ARP requests reach every device in the broadcast domain, and why they stop at VLAN/router
  boundaries ([[vlans]]).
- **Reply is unicast** — the responder learned the asker's MAC from the request, so it answers
  directly.

ARP rides **directly on Ethernet** with EtherType **`0x0806`** — it is **not** inside IP. ARP
straddles L2/L3: it carries IP addresses but isn't encapsulated in an IP packet. It's the
connective tissue *between* the layers.

### The ARP cache

Broadcasting per packet would be absurd, so each host keeps an **ARP cache** (`IP → MAC`):

```
$ arp -a
? (192.168.1.1)  at a4:5e:60:12:34:56 [ether] on en0     ← the gateway
? (192.168.1.20) at b8:27:eb:aa:bb:cc [ether] on en0     ← a local device
```

Check cache first → hit means build the frame immediately; miss means request/reply, then cache
the result. Entries **expire** (minutes) so stale mappings self-correct. Pattern to notice:
*broadcast to discover, cache to avoid repeating* — the same shape as DNS resolution + TTL, but at
L2.

### Gratuitous ARP

An **unprompted** ARP announcing one's own `IP → MAC` (no request was made). Three uses:

1. **Announce presence / refresh caches** — on boot or NIC change.
2. **Detect IP conflicts** — ARP for your *own* IP; a reply means the address is taken.
3. **Failover (the big one)** — when a standby device takes over a shared/virtual IP (HSRP/VRRP
   gateway failover, load-balancer VIP), a gratuitous ARP **instantly updates every cache** to the
   new MAC. Without it, hosts keep sending to the dead device's MAC until their cache expires — a
   multi-minute outage. Connects to the first-hop-redundancy topic.

### Security: ARP has zero authentication

**Any device can send an ARP reply claiming any IP maps to its MAC, and everyone believes it** —
replies are accepted even when unsolicited. This enables **ARP spoofing / poisoning**, the basis of
most LAN man-in-the-middle attacks:

```
 Attacker → Victim:  "192.168.1.1 (the gateway) is at MY MAC"
 Attacker → Gateway: "192.168.1.10 (the victim) is at MY MAC"
```

Both now send traffic to the attacker, who forwards it on while reading/modifying it. It defeats
the privacy switching normally provides, because it poisons the **endpoints' maps**, not the
switch's forwarding.

Defenses: **Dynamic ARP Inspection (DAI)** (validates ARP against a trusted DHCP-snooping table),
**static ARP entries** for critical devices, and **TLS** so intercepted traffic is unreadable. Ties
to the MAC-spoofing warning in [[ethernet]].

### CLI

```
arp -a                        # view ARP cache (macOS/Linux/Windows)
ip neigh                      # modern Linux (neighbor table)
arp -d 192.168.1.1            # delete an entry, forcing a re-ARP

Switch# show ip arp
Switch(config)# ip arp inspection vlan 10     # enable DAI
```

Watching `arp -a` while pinging a new local host is the clearest way to see ARP happen live.

### Gotchas

- **"My laptop ARPs for the remote server's MAC."** No — it ARPs for the **next hop** (the
  gateway) when the destination is off-subnet. You only ARP for things on your own link.
- **ARP doesn't cross networks.** It's a broadcast; it stops at the VLAN/router boundary. Routers
  do **not** forward ARP — each hop ARPs for its own next hop.
- **Never trust ARP** — unauthenticated by design, trivially spoofable.
- **ARP ≠ DNS.** DNS: name → IP (L7, global). ARP: IP → MAC (L2, local, one link). Both are
  "resolve + cache," at opposite ends of the stack.
- **ARP is IPv4-only.** IPv6 uses **NDP (Neighbor Discovery Protocol)** over ICMPv6 multicast
  instead — same concept, different mechanism.

### Recall check

1. Laptop `192.168.1.10` (gateway `192.168.1.1`) connects to `93.184.215.14` — whose MAC does it
   ARP for?
   → The **gateway's** (`192.168.1.1`). The server is off-subnet and unreachable directly; L3 says
   "send to the gateway," and ARP resolves that **next-hop** IP. You only ARP for IPs on your own
   link.
2. Why is the request broadcast but the reply unicast?
   → The **request** must reach everyone because the sender doesn't know the target's MAC yet. The
   **reply** can be unicast because the responder learned the asker's MAC from the request itself.
3. A backup router takes over the gateway IP but sends no gratuitous ARP — what breaks?
   → Every host still has the **dead primary's MAC** cached for the gateway IP and keeps sending
   there until the cache **expires** (minutes) — a multi-minute outage despite a ready backup. The
   gratuitous ARP updates all caches instantly, enabling near-seamless failover.

### One thing to walk away with

ARP is the **glue between the IP world and the MAC world**: given a next-hop IP on the local link,
it finds the MAC. It **broadcasts** a request, gets a **unicast** reply, and **caches** the result
(expiring after minutes). You ARP for the **next hop** — the destination if local, the **gateway**
if remote — never the far-away server. It rides directly on Ethernet (`0x0806`), is **link-local**
(stops at router/VLAN boundaries), and is **completely unauthenticated**, making ARP spoofing the
basis of most LAN MITM attacks.
