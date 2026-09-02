---
slug: encapsulation-decapsulation
title: Encapsulation & Decapsulation — Segments → Packets → Frames → Bits
topic: networks
bloom-level: some
created: 2026-07-07
updated: 2026-08-08
published: 2026-07-20
related: [osi-model, tcp-ip-model, how-internet-works, bandwidth-throughput-latency-jitter, ethernet, ipv4-addressing, routing-fundamentals]
tags: [fundamentals, encapsulation, decapsulation, pdu, headers, demultiplexing, mtu, ethertype, ttl, mac, ip]
sources:
  - "RFC 1122 — Requirements for Internet Hosts (1989)"
  - "IEEE 802.3 — Ethernet frame format"
---

## Answer

**The concept:** As data moves **down** the stack on send, each layer wraps the layer above in
its own header (encapsulation); as it moves **up** on receive, each layer strips its own header
and hands the rest up (decapsulation). The mental image is nesting dolls / envelopes inside
envelopes. See [[osi-model]], [[tcp-ip-model]], [[how-internet-works]].

**The rule that makes it work:** each layer only reads and writes *its own* header; everything
inside is opaque cargo it never opens. Ethernet doesn't know it carries IP; IP doesn't peek at
TCP; TCP doesn't parse HTTP. This is the layering principle made physical.

### Down the stack: the wrapping

```
L7 App        │ GET / HTTP/1.1 ...                              │   ← "Data"
L4 Transport  │[TCP hdr]│ GET / ... │                           │   ← "Segment"
L3 Network    │[IP hdr]│[TCP hdr]│ GET / ... │                  │   ← "Packet"
L2 Data Link  │[Eth hdr]│[IP hdr]│[TCP hdr]│ GET / ... │[Eth FCS]│   ← "Frame"
L1 Physical   │ 010101101000101110100101110001010110...        │   ← "Bits"
```

Three things to notice:
1. **Each layer's payload = the entire PDU from the layer above** (its header + everything it
   carried). Dolls inside dolls.
2. **Headers are prepended** (added to the front); the innermost data stays put.
3. **Layer 2 also adds a trailer** (the FCS), not just a header.

### The PDU vocabulary (the word *is* the layer)

| Layer | PDU name | What got added |
|---|---|---|
| L7–5 Application | **Data** / message | raw content |
| L4 Transport | **Segment** (TCP) / **Datagram** (UDP) | ports + reliability control |
| L3 Network | **Packet** | source/dest **IP**, TTL |
| L2 Data Link | **Frame** | source/dest **MAC** + trailer |
| L1 Physical | **Bits** | signaling only |

Saying "the *frame* dropped" vs "the *packet* was routed" vs "the *segment* was retransmitted"
tells you which layer someone means.

### Load-bearing header fields (earlier concepts, now as bytes)

**L4 TCP header (~20 B):** source/dest **port** (which app), **seq/ack #** (ordering &
confirmation), **flags** SYN/ACK/FIN/RST (handshake), **window** (flow control), **checksum**.

**L3 IP header (~20 B):** source/dest **IP** (end-to-end, never change en route), **TTL** (hop
counter, −1 each router, 0 = dropped, kills loops), **Protocol** (which L4 is inside: 6=TCP,
17=UDP, 1=ICMP), **checksum**.

**L2 Ethernet (14 B header + 4 B trailer):** dest/source **MAC** (one hop, rewritten every
hop), **EtherType** (which L3 is inside: 0x0800=IPv4, 0x0806=ARP, 0x86DD=IPv6), **FCS** trailer
(error detection).

The addressing hierarchy from the first three topics, literally stacked: TCP carries *ports*
(which app), IP carries *end-to-end IPs* (fixed), Ethernet carries *MACs* (one hop, rewritten).

### Demultiplexing: how the receiver knows how to unwrap

Each header carries a "what's inside me" pointer, so a decapsulating machine always knows which
upper-layer protocol to hand the payload to:

```
Ethernet ──EtherType 0x0800──►  payload is IPv4
   IP    ──Protocol 6────────►  payload is TCP
   TCP   ──Dest Port 443──────►  hand to the HTTPS server process
```

This chain of signposts is **demultiplexing (demuxing)**. Ports as the final demux step is the
dedicated *ports & multiplexing* topic later.

### Up the stack: decapsulation (exact mirror)

Each layer reads its own header, verifies it (checksum ok? addressed to me?), strips it, and
uses the pointer field to hand the payload up:

```
Bits → L2 (my MAC? FCS ok?) strip → EtherType: IPv4, up
     → L3 (my IP? TTL/checksum ok?) strip → Protocol: TCP, up
     → L4 (which port/connection?) strip → Port 443, hand to app
     → L7 app reads "GET / HTTP/1.1"
```

### What routers and switches do (partial decap / re-encap)

- **Switch (L2):** unwraps only to L2, reads dest MAC, forwards out a port — never touches
  IP/TCP inside.
- **Router (L3):** unwraps to L3, reads dest IP, makes the routing decision, then **strips the
  old Ethernet frame and builds a brand-new one** (new src/dest MAC) for the next hop, and
  decrements TTL. The IP packet inside is untouched; the TCP/HTTP is never opened (and over
  HTTPS is encrypted anyway).

```
Router: strip L2 → read/keep IP packet → decide next hop → TTL−1 → wrap in NEW L2 frame → send
```

This is *exactly* why **IP is end-to-end and MAC is rewritten every hop**: the IP packet is the
durable inner doll that travels the whole way; the Ethernet frame is a disposable outer doll
torn off and rebuilt at every router. See [[how-internet-works]].

### Overhead (why headers cost something)

```
TCP (20) + IP (20) + Ethernet header+trailer (18) ≈ 58 bytes overhead per frame
```

A 1-byte payload still puts ~59 bytes on the wire — wasteful. A full ~1500-byte frame (the
standard Ethernet MTU) amortizes the overhead. This is why small/chatty packets hurt throughput
and why MTU/MSS/fragmentation matter (next topic block).

### Gotchas & anti-patterns

- **Headers are prepended, not appended.** Only L2 adds a trailer (FCS).
- **Routers do NOT rewrite IP addresses** (normally) — they rewrite the L2 frame each hop. The
  exception is **NAT**, which deliberately rewrites IPs; that boundary-breaking is *why* NAT is a
  special hack (later topic).
- **The opaque-payload rule is what lets encryption work:** TLS-encrypted HTTP is just opaque
  bytes to TCP, IP, and every router — they forward it perfectly without reading it.
- **PDU names are not interchangeable.** Segment (L4), packet (L3), frame (L2) each pin a layer.
- **Only the final destination decapsulates to L7.** Switches stop at L2, routers at L3 — they
  unwrap only as far as their job requires.

### Recall check

1. A packet crosses 5 routers to a server. How many times is the Ethernet frame rebuilt, and how
   many times do the IP source/dest change? Why?
   → Frame rebuilt ~6 times (per hop + final link); IP src/dest change 0 times (absent NAT).
   The frame is the disposable one-hop wrapper (MAC = local); the IP packet is the durable
   end-to-end payload (IP = whole journey).
2. When bits arrive, how does the machine know the Ethernet payload is IP vs ARP, then TCP vs
   UDP?
   → Demultiplexing via pointer fields: Ethernet **EtherType** (0x0800=IP, 0x0806=ARP), then IP
   **Protocol** (6=TCP, 17=UDP). Each header names what's nested inside it.
3. Why can a router forward HTTPS traffic it can't read?
   → The opaque-payload rule: a router reads only the IP header to route; TCP/TLS/HTTP are cargo
   it never opens. Encryption lives inside the payload, so routing is unaffected — it needs the
   envelope, not the letter.

### One thing to walk away with

**Encapsulation is dolls-in-dolls:** each layer wraps the layer above in its own header, treats
the inside as opaque cargo, and each header carries a pointer to what's nested so the receiver
can unwrap in reverse. The **IP packet** is the durable inner doll that survives the whole trip;
the **Ethernet frame** is the disposable outer doll rebuilt at every router. That one picture
explains routing, the MAC-vs-IP split, why encryption doesn't break routing, and why header
overhead makes small packets wasteful.
