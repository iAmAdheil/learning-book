---
slug: tcp-ip-model
title: TCP/IP Model — How the 4/5-Layer Model Maps to Reality vs OSI
topic: networks
bloom-level: some
created: 2026-07-07
updated: 2026-08-03
published: 2026-07-20
related: [osi-model, how-internet-works, encapsulation-decapsulation, ipv4-addressing]
tags: [fundamentals, tcp-ip-model, osi-model, layering, hourglass, narrow-waist, ip, sockets, tls]
sources:
  - "RFC 1122 — Requirements for Internet Hosts, Communication Layers (1989)"
---

## Answer

**The concept:** The **TCP/IP model** is the layered stack the actual internet is built on.
Where OSI is the idealized 7-layer *reference map*, TCP/IP is the *territory* — the leaner
4-layer stack (RFC 1122, 1989) that really runs, and where real protocols like TLS and
sockets have crisp homes. See [[osi-model]].

### Why a second model exists (the history that explains everything)

- **OSI** was designed by an international committee (ISO) in the late 1970s–80s: the complete,
  elegant 7-layer blueprint — *designed first, implemented later.*
- **TCP/IP** grew out of DARPA / the ARPANET in the 1970s — *built first, standardized later.*
  By the time OSI's committees finished, TCP/IP already ran the network and shipped in Unix
  (BSD sockets).

The IETF motto settled the contest: *"We reject kings, presidents, and voting. We believe in
rough consensus and running code."* OSI was the beautiful design that arrived late and heavy;
TCP/IP was the pragmatic thing that already worked. **OSI won the vocabulary; TCP/IP won the
internet.** Learn OSI to *talk* about networking; learn TCP/IP because it is what's *deployed*.

### The two versions (know both — the difference is trivial)

| TCP/IP 4-layer (RFC 1122, official) | TCP/IP 5-layer (textbook) |
|---|---|
| Application | Application |
| Transport | Transport |
| Internet | Network |
| **Link** (physical + data link lumped) | **Data Link** |
| | **Physical** |

The only difference: the 4-layer model lumps physical wire + framing into one **Link** layer;
the 5-layer model splits it into **Data Link + Physical** (matching OSI's bottom two). Same
stack, one seam. Textbooks (Kurose, Tanenbaum) teach 5; RFC 1122 says 4.

### Master mapping: OSI 7 → TCP/IP (the whole topic in one table)

```
   OSI (7)                    TCP/IP 5-layer     TCP/IP 4-layer     Real protocols
 ┌─────────────────┐
 │ 7 Application   │┐
 │ 6 Presentation  │├──► Application     ┐──────► Application    ── HTTP, DNS, TLS, SSH
 │ 5 Session       │┘                    │
 │ 4 Transport     │──► Transport        ┴──────► Transport      ── TCP, UDP
 │ 3 Network       │──► Network           ──────► Internet       ── IP, ICMP
 │ 2 Data Link     │──► Data Link        ┐──────► Link           ── Ethernet, Wi-Fi, ARP
 │ 1 Physical      │──► Physical         ┘                       ── cables, fiber, radio
 └─────────────────┘
```

Two collapses when OSI → TCP/IP:

1. **OSI's top three (7 Application, 6 Presentation, 5 Session) merge into one Application
   layer.** TCP/IP gives Session and Presentation no dedicated layers — those jobs belong to
   the application. This is why "where does TLS go?" is awkward in OSI (nominally L6) but simple
   in TCP/IP: **TLS is just part of the Application layer.**
2. **OSI's bottom two (2 Data Link, 1 Physical) may merge** into Link (4-layer) or stay split
   (5-layer).

**The middle is identical across all three models:** Transport (TCP/UDP) and Network/Internet
(IP) never change. Only the top and bottom get reorganized.

### Where the things you actually touch live

| Thing | TCP/IP layer | Note |
|---|---|---|
| HTTP, DNS, SMTP, SSH | Application | the protocols programs speak |
| **TLS / SSL** | Application (top of it) | no dedicated layer — the app secures its own data |
| **Sockets API** | boundary of App ↔ Transport | the programming interface to TCP/UDP — where code plugs in |
| TCP, UDP | Transport | ports + (optional) reliability |
| IP, ICMP, routing | Internet | addressing + routing (a router's world) |
| Ethernet, Wi-Fi, ARP, switches | Link | one-hop delivery, MAC addressing |
| cables, fiber, radio | Link / Physical | the actual signals |

The **socket** sits exactly at the App↔Transport boundary: `socket()/bind()/listen()/send()`
is your application handing bytes to TCP. TCP/IP makes that boundary crisp where OSI blurred it
across three layers. For network engineers, the **Internet layer** (IP, subnets, routing) and
**Link layer** (switches, VLANs, MACs) are the whole job.

### The best mental model: the hourglass (narrow waist)

```
      many applications          HTTP  DNS  SMTP  SSH  gRPC  QUIC
                                   \    |    |    |    /    /
      transport-ish choice          TCP        UDP
                                        \        /
      ═══════════ THE WAIST ═══════════ IP ═══════════   ← everything funnels through ONE protocol
                                        /        \
      many link technologies      Ethernet  Wi-Fi  Fiber  5G  Bluetooth
```

The internet is an **hourglass**: many applications on top, many physical technologies on the
bottom, but a **single narrow waist in the middle — IP.** The rule: **"IP over everything, and
everything over IP."** A new app just runs over IP; a new physical tech just carries IP. Because
everyone agreed on *one* thing in the middle, innovation at the top and bottom happened
independently and permissionlessly. **That narrow waist is why the internet scaled explosively**
— the same layering/decoupling idea from OSI, made concrete, and the same "narrow waist" pattern
praised in API and platform design.

### Gotchas & anti-patterns

- **"TCP/IP" means two things:** the *model* (this 4/5-layer stack) and the *protocol suite*
  (TCP, IP, UDP, ICMP, ARP…). Context tells you which.
- **4 vs 5 layers is not a real disagreement** — just whether Link is split into Physical +
  Data Link.
- **Session & Presentation didn't disappear** — their jobs (encryption, encoding, session
  management) still happen; TCP/IP just assigns them to the application.
- **No clean 1:1 with OSI.** ARP straddles Link/Internet (resolves L3 IP → L2 MAC). Real
  protocols don't respect tidy lines.
- **The model isn't the code.** Like OSI, it's a conceptual organization, not literal kernel
  modules.

### Recall check

1. OSI has 7 layers, TCP/IP (official) has 4 — which OSI layers merged, and into what?
   → OSI 7+6+5 (Application + Presentation + Session) → one **Application** layer; OSI 2+1 (Data
   Link + Physical) → one **Link** layer. The middle (Transport, Network) maps 1:1.
2. Why is "which layer is TLS?" easy in TCP/IP but awkward in OSI?
   → TCP/IP has no Presentation/Session layers — encryption is simply the **application's** job,
   so TLS is just "part of Application." No 6-vs-between-4-and-7 debate.
3. What is the "narrow waist," and why did it help the internet scale?
   → **IP** — the single protocol everything runs over ("IP over everything, everything over
   IP"). It decoupled apps (top) from link tech (bottom); both only had to agree on IP, enabling
   independent, permissionless growth.

### One thing to walk away with

**TCP/IP is the real stack; OSI is the shared language.** They agree exactly in the middle
(Transport = TCP/UDP, Internet = IP) and differ only at the edges, where TCP/IP folds OSI's top
three into "Application" and its bottom two into "Link." And the reason it works is the
**hourglass**: one narrow waist (IP) that everything funnels through, decoupling the apps above
from the wires below.
