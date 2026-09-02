---
slug: vlans
title: VLANs — Segmentation, Access vs Trunk Ports, 802.1Q Tagging
topic: networks
bloom-level: some
created: 2026-07-12
updated: 2026-08-06
published: 2026-07-20
related: [how-switches-work, ethernet, osi-model, spanning-tree-protocol, arp, subnetting, vlsm]
tags: [layer-2, vlan, 802.1q, tagging, access-port, trunk-port, native-vlan, broadcast-domain, segmentation, vlan-hopping, inter-vlan-routing]
sources:
  - "IEEE 802.1Q — Virtual Bridged Local Area Networks"
---

## Answer

**The concept:** A **VLAN (Virtual LAN)** is a logically separate broadcast domain created in
software on a shared physical switch. It solves the problem left open by [[how-switches-work]]:
**one switch = one broadcast domain**, meaning no isolation and broadcast noise for everyone,
with "buy separate physical switches" as the only classic fix.

### The mental model

```
        ONE physical switch                      becomes...

  ┌───────────────────────────────┐     ┌──────────┐ ┌──────────┐ ┌──────────┐
  │  ▪ ▪ ▪ ▪ ▪ ▪ ▪ ▪ ▪ ▪ ▪ ▪ ▪ ▪  │  →  │ VLAN 10  │ │ VLAN 20  │ │ VLAN 30  │
  │      one broadcast domain     │     │   Eng    │ │    HR    │ │ Finance  │
  └───────────────────────────────┘     └──────────┘ └──────────┘ └──────────┘
                                          three independent virtual switches
```

You slice one physical switch into multiple virtual switches. The switch keeps a **separate CAM
table per VLAN** and refuses to forward frames between them. To devices it is *exactly* as if
they were on different physical switches with no cable between.

> **VLANs are L2 boundaries. A device in VLAN 10 cannot reach VLAN 20 at all without a Layer 3
> device (a router).** Broadcasts stop at the VLAN edge. Each VLAN is its own broadcast domain —
> more broadcast domains, without more switches.

### Benefits

| Benefit | Meaning |
|---|---|
| Smaller broadcast domains | Engineering's broadcasts never reach HR — less noise, less wasted CPU/bandwidth |
| Security / isolation | VLANs can't talk at L2; traffic separated as if physically apart |
| Logical grouping | Group by *function*, not location — Finance can span 3 floors, one VLAN |
| Cost & flexibility | One switch does the work of many; moving someone is a config change, not recabling |

### Access vs trunk ports (the central distinction)

| | **Access port** | **Trunk port** |
|---|---|---|
| Connects to | **End devices** (PC, printer, phone) | **Switch↔switch**, or switch↔router |
| Carries | Exactly **ONE** VLAN | **MULTIPLE** VLANs simultaneously |
| Frames on wire | **Untagged** | **Tagged** (802.1Q) |
| Device awareness | Device has **no idea** VLANs exist | Both ends must understand tags |

- **Access port:** a PC is a dumb participant. The frame arrives untagged and the **switch
  assigns the VLAN from the port config**. The PC never sees a tag.
- **Trunk port:** one cable must carry all VLANs between switches, so arriving frames would be
  ambiguous — the **tag** says which VLAN each belongs to. (Alternative: one cable per VLAN — 50
  VLANs = 50 cables. Trunking multiplexes them onto one link.)

### 802.1Q tagging

**IEEE 802.1Q** inserts **4 bytes** right after the source MAC:

```
 Untagged:
 ┌───────────┬───────────┬───────────┬──────────┬──────┐
 │  Dest MAC │  Src MAC  │ EtherType │ Payload  │ FCS  │
 └───────────┴───────────┴───────────┴──────────┴──────┘

 Tagged:
 ┌───────────┬───────────┬─────────────────┬───────────┬──────────┬──────┐
 │  Dest MAC │  Src MAC  │   802.1Q TAG    │ EtherType │ Payload  │ FCS  │
 │    6 B    │    6 B    │      4 B        │    2 B    │          │ 4 B  │
 └───────────┴───────────┴─────────────────┴───────────┴──────────┴──────┘
```

| Field | Size | Purpose |
|---|---|---|
| **TPID** | 2 B | Always `0x8100` — sits in the EtherType position, signalling "I'm tagged" |
| **PCP** | 3 bits | Priority (802.1p) — QoS class |
| **DEI** | 1 bit | Drop-eligible indicator |
| **VLAN ID** | **12 bits** | Which VLAN this frame belongs to |

The **TPID trick**: a receiver reads the EtherType position, sees `0x8100` (not a real L3
protocol), and knows *"a tag follows; the real EtherType is 4 bytes further."* Backwards-compatible
in-band signalling — see the EtherType table in [[ethernet]].

**12 bits → 4096 IDs**, usable **1–4094** (0 and 4095 reserved). **VLAN 1 is the default** (every
port starts there). Best practice: don't put user traffic on VLAN 1. Tagged frame max grows
**1518 → 1522 bytes**.

### The frame's journey

```
  PC-A ──(access, vlan 10)── [SW1] ═══trunk═══ [SW2] ──(access, vlan 10)── PC-B
```

| Step | What happens |
|---|---|
| 1 | PC-A sends a normal **untagged** frame — no clue VLANs exist |
| 2 | SW1's **access port** internally tags it **VLAN 10** (from port config) |
| 3 | Sending out the **trunk** → SW1 **adds the 802.1Q tag (VID 10)** |
| 4 | SW2 reads **VID 10**, consults its **VLAN 10 CAM table** only |
| 5 | Forwarding out PC-B's **access port** → SW2 **strips the tag** |
| 6 | PC-B receives a normal **untagged** frame — also no clue |

**Tags exist only on trunk links between switches.** Added entering a trunk, stripped leaving to
an access port. **End devices never see a tag** — which is why VLANs work with unmodified PCs.

### The native VLAN (and its sharp edge)

On a trunk, one VLAN is the **native VLAN**, sent **untagged** (default VLAN 1), for backwards
compatibility. It's a security liability: the **double-tagging VLAN-hopping attack** sends a frame
with two tags; the first switch strips the outer tag (matches native VLAN) and forwards it on the
trunk, where the second switch reads the **inner** tag and delivers it into a VLAN the attacker
was never allowed into.

**Best practice:** set the native VLAN to an **unused, dedicated VLAN** (never VLAN 1, never a
user VLAN), or tag everything.

### VLANs and subnets (1:1 by convention)

| VLAN | Purpose | Subnet |
|---|---|---|
| 10 | Engineering | `192.168.10.0/24` |
| 20 | HR | `192.168.20.0/24` |
| 30 | Finance | `192.168.30.0/24` |

Not technically required but near-universal — and it follows from the mechanics: a VLAN is one
broadcast domain, **ARP is a broadcast**, so a subnet (whose hosts must ARP each other) must live
inside one broadcast domain. **VLAN boundary = broadcast boundary = subnet boundary.** Therefore
crossing VLANs means crossing subnets = **routing**, requiring an L3 device (**inter-VLAN
routing**: router-on-a-stick / SVIs). **Switches segment; routers connect the segments.**

### On real gear

```
! Create the VLAN
Switch(config)# vlan 10
Switch(config-vlan)# name ENGINEERING

! Access port — one VLAN, for a PC
Switch(config)# interface FastEthernet0/1
Switch(config-if)# switchport mode access
Switch(config-if)# switchport access vlan 10

! Trunk port — many VLANs, to another switch
Switch(config)# interface GigabitEthernet0/1
Switch(config-if)# switchport mode trunk
Switch(config-if)# switchport trunk allowed vlan 10,20,30
Switch(config-if)# switchport trunk native vlan 999    ! unused VLAN — hardening
```

```
Switch# show vlan brief          ! which ports are in which VLAN
Switch# show interfaces trunk    ! trunk status + allowed VLANs
```

**Prune VLANs you don't need on a trunk** (`switchport trunk allowed vlan`) — a performance *and*
security practice.

### Gotchas

- **"VLANs help devices in different VLANs talk."** Backwards — VLANs **prevent** L2
  communication between them. Crossing requires a **router**.
- **End devices aren't VLAN-aware.** PCs send/receive untagged; the switch does all tagging.
  (Exceptions: VoIP phones, hypervisors/servers can be trunked and tag-aware.)
- **Access vs trunk confusion** — access = one VLAN untagged to end devices; trunk = many VLANs
  tagged between switches. Misconfiguring one is a classic outage.
- **Native VLAN left as VLAN 1** — enables double-tagging VLAN hopping. Change it.
- **VLANs aren't a firewall.** Good segmentation, but hopping/misconfig exist.
- **VLANs must exist and be allowed on both switches** for traffic to cross a trunk.

### Recall check

1. PC-A (VLAN 10) and PC-B (VLAN 20) on the **same switch**, both IPs in `192.168.1.0/24` — can
   they ping?
   → **No.** Different VLANs = different broadcast domains; separate CAM tables, no forwarding
   between. A's ARP broadcast never leaves VLAN 10, so it never learns B's MAC. Same-subnet IPs
   make it worse — A thinks B is local and won't even try the gateway. Needs a router + proper
   per-VLAN subnets.
2. Where is the 802.1Q tag added/removed? Do the PCs see it?
   → **Added** when the first switch sends the frame **out onto the trunk**; **removed** when the
   second switch sends it **out an access port**. **Neither PC ever sees it** — tags exist only on
   trunk links.
3. Why does a trunk need tagging but an access port doesn't?
   → A trunk carries **multiple VLANs over one cable**, so frames would be ambiguous on arrival —
   the tag disambiguates. An access port carries exactly **one** VLAN, already known from the port
   config, and end devices shouldn't need to understand tagging.

### One thing to walk away with

A VLAN **slices one physical switch into multiple virtual switches**, each its own broadcast
domain — segmentation without extra hardware. **Access ports** carry one VLAN untagged to
VLAN-unaware end devices; **trunk ports** carry many VLANs between switches using a **4-byte
802.1Q tag** (TPID `0x8100` + 12-bit VLAN ID). Tags are added entering a trunk, stripped leaving to
an access port. Because VLANs are hard L2 boundaries, **crossing them requires a router** —
switches segment, routers connect.

## Q: How does flooding work with VLANs? Does it flood out trunk ports too, along with access ports in the same VLAN?

**Yes — flooding goes out trunk ports as well as access ports.** The flood rule from
[[how-switches-work]] ("flood out all ports except the arrival port") gets **scoped to the VLAN**:

> **Flood out = (all access ports in VLAN X) + (all trunk ports that allow VLAN X) − (the arrival
> port)** — **untagged** on access ports, **tagged** on trunks.

A single flood event produces both untagged copies (to PCs) and tagged copies (to other switches).
Ports in other VLANs get nothing.

Three details:
1. **The flood domain is the VLAN, not the switch.** A VLAN can span multiple switches via trunks,
   so the flood crosses the trunk and continues on the far switch.
2. **`switchport trunk allowed vlan` gates it.** If VLAN 10 isn't allowed on a trunk, VLAN 10
   floods don't traverse it — this is why **VLAN pruning** is a performance practice, literally
   limiting how far flooded traffic travels.
3. **The lookup is per-VLAN.** "Unknown MAC in VLAN 10" is a separate question from VLAN 20's
   table; each VLAN floods independently.

**Trace** — PC-A (VLAN 10) sends to an unknown MAC:

```
PC-A (vlan 10) ─access─┐                                    ┌─access─ PC-C (vlan 10)
                       ├[SW1]═══trunk (allows 10,20)═══[SW2]┤
PC-B (vlan 20) ─access─┤                                    └─access─ PC-E (vlan 20)
PC-D (vlan 10) ─access─┘
```

| Where | What happens |
|---|---|
| SW1 learns | `A → port 1` in the **VLAN 10** CAM table |
| SW1 decides | Dest unknown in VLAN 10's table → **FLOOD within VLAN 10** |
| → PC-D access port | ✅ sent, **untagged** |
| → trunk to SW2 | ✅ sent, **tagged VID 10** |
| → PC-B access port | ❌ not sent — VLAN 20 |
| SW2 receives on trunk | Reads **VID 10**; learns `A → trunk port` in its VLAN 10 table |
| SW2 decides | Still unknown → floods within VLAN 10 |
| → PC-C access port | ✅ sent, **untagged** |
| → PC-E access port | ❌ not sent — VLAN 20 |
| → back out the trunk | ❌ never — that's the arrival port |

**SW2 learned A's location via the trunk port** — the same learn-from-source rule, just pointing at
a trunk instead of an access port. When the reply comes back, SW2 forwards out the trunk and SW1
out port 1; flooding stops and unicast takes over, now spanning two switches.

**What this sets up:** a flooded frame propagates across every trunk in the VLAN. If SW1 and SW2
have **two** trunk links (redundancy), the flood goes out trunk A → SW2 floods it out trunk B →
SW1 floods it out trunk A → **forever**. Ethernet has **no TTL** (that's an IP field; this is pure
L2), so the frame never dies — a **broadcast storm** that saturates links and melts switches in
seconds. That is precisely the problem **Spanning Tree Protocol** solves.
