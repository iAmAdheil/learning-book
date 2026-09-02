---
slug: ethernet
title: Ethernet — Frame Format, MAC Addresses & EtherType
topic: networks
bloom-level: some
created: 2026-07-12
updated: 2026-07-12
published: 2026-07-20
related: [encapsulation-decapsulation, osi-model, how-internet-works, how-switches-work, vlans, arp]
tags: [layer-2, ethernet, mac-address, frame, ethertype, fcs, mtu, csma-cd, broadcast, oui]
sources:
  - "IEEE 802.3 — Ethernet standard"
---

## Answer

**The concept:** Ethernet is the dominant technology for local networks (LANs) — the
standardized way devices on the *same local link* format data into frames and address each
other, defined by the **IEEE 802.3** family. It is the concrete Layer-2 (Data Link) reality
behind the abstractions in [[osi-model]] and [[encapsulation-decapsulation]]: the "one hop, MAC
addressing" layer, reaching down into Layer 1 (Physical).

The problem it solves: put several computers on a shared medium and you need (1) addressing —
"who is this for?" (MAC addresses) and (2) framing — "where does a chunk start/end and did it
arrive intact?" (the frame format). Ethernet answers both and won the LAN wars by being cheap,
simple, and endlessly upgradeable (10 Mbps → 400 Gbps, same frame concept).

### MAC addresses — the L2 identity

A **48-bit (6-byte)** hardware address, usually burned into the NIC, written as six hex pairs:

```
a4:5e:60 : 12:34:56
└──────┘   └──────┘
  OUI       device-specific
```

- **First 3 bytes = OUI (Organizationally Unique Identifier):** IEEE-assigned to the
  manufacturer (you can look up the maker from a MAC).
- **Last 3 bytes:** manufacturer-assigned, unique per device.
- Together: globally unique (in theory).

Three destination types:
| Type | Address | Meaning |
|---|---|---|
| Unicast | a specific MAC | one device |
| Broadcast | `ff:ff:ff:ff:ff:ff` | every device on the local network |
| Multicast | special ranges (low bit of first byte = 1) | a subscribed group |

Broadcast is how a device shouts to the whole LAN — used by **ARP** ("who has this IP?") and by
switch flooding. MAC = flat, hardware, **local scope only** (rewritten every router hop); IP =
hierarchical, logical, **global** (end-to-end). See [[how-internet-works]]. Modern wrinkle:
phones use **MAC randomization** for privacy, so permanence/uniqueness isn't guaranteed.

### The Ethernet frame format

```
┌──────────┬─────┬───────────┬───────────┬───────────┬──────────────────┬──────┐
│ Preamble │ SFD │  Dest MAC │  Src MAC  │ EtherType │      Payload      │ FCS  │
│  7 bytes │ 1 B │   6 bytes │  6 bytes  │  2 bytes  │   46 – 1500 B     │ 4 B  │
└──────────┴─────┴───────────┴───────────┴───────────┴──────────────────┴──────┘
   └── L1 sync ──┘└───────────────── the actual frame ───────────────────────┘
```

| Field | Size | Purpose |
|---|---|---|
| Preamble + SFD | 7 + 1 B | Clock sync (L1, not counted in frame); SFD marks "frame starts now" |
| Destination MAC | 6 B | Who it's for; switches read this to forward |
| Source MAC | 6 B | Who sent it; switches *learn* from this |
| EtherType | 2 B | Which L3 protocol is inside — the demux pointer |
| Payload | 46–1500 B | The encapsulated L3 packet (usually IP) |
| FCS | 4 B | CRC32 checksum for error *detection* |

Destination-first ordering is deliberate: a switch can start forwarding on the dest MAC before
the whole frame arrives (cut-through switching).

### EtherType — the demux pointer

The 2-byte "what's inside me" signpost (see [[encapsulation-decapsulation]]):
| EtherType | Payload |
|---|---|
| `0x0800` | IPv4 |
| `0x0806` | ARP |
| `0x86DD` | IPv6 |
| `0x8100` | 802.1Q VLAN tag |

### FCS — detection, not correction (Ethernet is best-effort)

The FCS is a CRC32 over the frame; on mismatch the frame is **silently discarded**. Ethernet
**detects but does not fix or retransmit** errors — recovery is TCP's job (L4). "Smart edges,
dumb middle": L2 stays simple, endpoints handle reliability.

### Frame size limits (where MTU comes from)

- **Minimum 64 bytes** (payload padded to 46 B if smaller). Historical reason: in half-duplex
  Ethernet with collisions, a frame had to stay on the wire long enough to detect a collision
  before finishing.
- **Maximum 1518 bytes** = 1500 payload + 18 (header + FCS). That **1500-byte payload is the
  Ethernet MTU** — why IP packets cap at 1500 and TCP's MSS ≈ 1460 (see
  [[encapsulation-decapsulation]] overhead).
- **Jumbo frames** (~9000 B) exist for data-center throughput — the dedicated MTU topic later.

### Media access: then vs now

- **Then (shared/half-duplex):** **CSMA/CD** — listen before you talk; on collision, back off
  randomly and retry. Source of the 64-byte minimum and collision domains.
- **Now (switched/full-duplex):** each device has a dedicated link to a switch, sending and
  receiving simultaneously — **no collisions**, so CSMA/CD is effectively dead on wired LANs.
  Wi-Fi uses CSMA/**CA** (Collision Avoidance) since radio is still shared.

### Gotchas

- **MACs don't route across the internet** — link-local only, rewritten each hop; only IP is
  end-to-end.
- **MACs can be spoofed and are randomized** — don't build security on "MAC = device" (see
  ARP-spoofing / port-security topics).
- **EtherType (L3 select) ≠ port (L4 app select)** — different demux layers.
- **FCS doesn't make Ethernet reliable** — it only detects and drops; TCP retransmits.
- **18 bytes of framing overhead per frame** — why tiny packets are inefficient.

### Recall check

1. Frame with dest MAC `ff:ff:ff:ff:ff:ff` and EtherType `0x0806` — what is it and who receives
   it?
   → An **ARP request** (0x0806) sent as **broadcast** (all devices on the LAN); the device
   owning the target IP replies.
2. Frame arrives with a bad FCS — what happens?
   → NIC **silently discards** it; no L2 retransmission. **TCP** (L4) notices the gap via
   seq/ACK and retransmits if it matters.
3. Why does the 1500-byte payload keep showing up (MTU, MSS, fragmentation)?
   → It's the **Ethernet MTU**, and Ethernet is near-universal, so IP sizes to fit it, TCP MSS =
   1500−20−20 ≈ 1460, and larger packets must fragment. One hardware limit ripples upward.

### One thing to walk away with

Ethernet is the concrete L2 reality: a **48-bit MAC** identity (OUI + device, link-local only),
a **frame** with dest/src MACs, an **EtherType** demux pointer, and an **FCS** that detects but
never fixes errors. It's **best-effort** (drops corrupt frames, leaves reliability to TCP), and
its **1500-byte MTU** is the number you keep meeting. Switches, VLANs, and STP are all clever
things done *to and with* these frames.
