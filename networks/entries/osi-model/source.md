---
slug: osi-model
title: OSI 7-Layer Model — What Each Layer Does and Why the Split Exists
topic: networks
bloom-level: some
created: 2026-07-07
updated: 2026-08-06
published: 2026-07-20
related: [how-internet-works, tcp-ip-model, encapsulation-decapsulation, ethernet, how-switches-work, ipv4-addressing, subnetting, vlsm]
tags: [fundamentals, osi-model, layering, switch, router, layer-2, layer-3, encapsulation, mac, ip]
sources:
  - "ISO/IEC 7498-1 (OSI Reference Model, 1994 revision)"
---

## Answer

**The concept:** Networking is split into seven stacked layers, each with one
responsibility and a clean contract with the layer above and below. The **OSI (Open
Systems Interconnection) reference model**, standardized by ISO in 1984 (ISO/IEC 7498-1),
is the shared vocabulary and mental map every network engineer uses — even though the
internet is actually built on the leaner TCP/IP model.

### Why layer anything? (the real point)

Imagine networking as one giant tangled program that turns an HTTP request into electrical
signals in a single blob. Switch from copper to Wi-Fi and you'd have to rewrite the whole
thing — including the HTTP parts that have nothing to do with radio. Layering is the fix,
identical to clean interfaces in software: split the job into layers, each with **one
responsibility** and a **clean contract** with its neighbors. Each layer (1) does its own
job and trusts the layer below, (2) talks to its **peer layer** on the other machine as if
directly, and (3) can be **swapped out** without touching the others.

That third point is the payoff. Wi-Fi vs Ethernet changes **only** Layers 1–2 — HTTP, TCP,
and IP never notice. TCP vs UDP is **only** Layer 4 — the browser and IP routing are
unaffected. **Layering lets each piece of the internet evolve independently.** That is the
entire reason the model exists.

Analogy — shipping a package internationally: you write a letter, hand it to a courier, who
hands it to an airline, which hands it to a plane's crew. Each layer only talks to the one
next to it and only cares about its own job. The airline doesn't read the letter; the writer
doesn't fly the plane. That division of labor *is* OSI.

### The seven layers

Numbered bottom (closest to the wire) to top (closest to the human):

| # | Layer | One-line job | Data unit (PDU) | Address | Examples |
|---|---|---|---|---|---|
| 7 | Application | Interface to the app / user | Data | — | HTTP, DNS, SMTP, SSH |
| 6 | Presentation | Format, encrypt, compress, encode | Data | — | TLS, JPEG, UTF-8 |
| 5 | Session | Set up / manage / tear down a dialogue | Data | — | session management |
| 4 | Transport | End-to-end delivery: reliability & ports | **Segment** (TCP) / Datagram (UDP) | Port | TCP, UDP |
| 3 | Network | Logical addressing & routing across networks | **Packet** | IP | IP, ICMP, routers |
| 2 | Data Link | Delivery across **one physical link** | **Frame** | MAC | Ethernet, Wi-Fi, switches |
| 1 | Physical | Raw bits as signals on a medium | **Bits** | — | cables, fiber, radio, voltages |

The **PDU column** (Protocol Data Unit) is worth memorizing: "segment," "packet," "frame,"
"bits" each name a specific layer. Data gets an L4 header (→ segment), then an L3 header
(→ packet), then an L2 header (→ frame), then becomes bits — that is encapsulation.

### Walking the layers (top-down, the order a click travels)

- **L7 Application** — the *protocol* the app speaks (HTTP, DNS), not the app itself. Defines
  the *meaning* of the request. About **what** you're asking for.
- **L6 Presentation** — translates app data ↔ neutral wire format: encryption (TLS lives
  here-ish), compression, encoding (UTF-8, JPEG). Why a Mac's image renders on Windows.
- **L5 Session** — manages the dialogue: open, keep alive, checkpoint, close. Blurriest layer
  in practice; modern stacks often fold it into the app or transport.
- **L4 Transport** — the **end-to-end** layer. Two jobs: **ports** (so one machine runs many
  conversations; the OS uses the port to pick which app gets the data) and **reliability**
  (TCP guarantees ordered/complete delivery; UDP doesn't). Highest layer that lives purely on
  the two endpoints — routers never touch it.
- **L3 Network** — **logical addressing and routing across networks.** Where **IP addresses**
  and **routers** live. Gets a packet from any network to any other, hop by hop, choosing a
  path. Global scope.
- **L2 Data Link** — delivery across **one physical link** (one hop). Where **MAC addresses**
  and **switches** live; builds Ethernet/Wi-Fi frames. Only cares about "get this frame to the
  device on the other end of *this* wire."
- **L1 Physical** — actual signals: voltage on copper, light in fiber, radio in Wi-Fi. Turns a
  frame's 1s and 0s into something physical and back.

The IP-is-end-to-end / MAC-is-hop-to-hop insight is literally **L3 (global, unchanging) vs L2
(local, rewritten each hop).** That distinction is the most useful thing OSI gives you. See
[[how-internet-works]].

### Mnemonics

- Top-down (7→1): **"All People Seem To Need Data Processing"**
- Bottom-up (1→7): **"Please Do Not Throw Sausage Pizza Away"**

### The reality check

The internet is **not actually built on OSI** — it runs on the **TCP/IP model**, which has
fewer layers. OSI is a *reference model*: an idealized 7-layer design that predates and
competed with TCP/IP and lost as an *implementation*. But the **vocabulary won even though
the implementation didn't.** Engineers say "that's a **Layer 2** issue" (switching/MAC/VLAN),
"we need a **Layer 3** device" (a router), "put an **L7 load balancer** in front" (routes on
HTTP paths — application-aware) vs "an **L4 load balancer**" (routes on IP:port — faster,
dumber). Learn OSI for the shared language and the layer-by-layer troubleshooting method;
learn TCP/IP for what's actually deployed.

### Gotchas & anti-patterns

- **"Chrome is Layer 7."** No — the *HTTP protocol* Chrome speaks is Layer 7. The app is a
  *user* of L7, not the layer itself.
- **Treating OSI as literal architecture.** TLS doesn't fit cleanly at L6 — it rides on TCP
  (L4). Real protocols smear across boundaries. OSI is a thinking tool, not gospel.
- **Layers 5 & 6 anxiety.** Their boundaries are fuzzy in practice. Nail 1–4 hard; know 5–7 by
  role.
- **Direction rule.** On send, data moves *down* the stack (7→1, adding headers =
  encapsulation). On receive, it moves *up* (1→7, stripping headers = decapsulation).

## Q: Do switches route? Is routing an L2 job, with IP just used for ARP and src/dest labels?

**No — this is the most common and most important inversion to fix.** Switches do **not**
route. **Routers route.** They are two different operations:

- **Routing** (L3, done by **routers**): deciding, based on the **destination IP**, which
  network to send toward next — crossing **between** networks.
- **Switching / L2 forwarding** (L2, done by **switches**): moving a frame to the right port
  **within one network**, based on **destination MAC**. No path decision, no crossing networks.

A plain switch doesn't even look at IP. It reads the destination MAC, checks its CAM table
("that MAC is on port 5"), and forwards the frame out that port. No routing table, no concept
of "next network."

**IP is not incidental — IP drives every routing decision; ARP is subordinate to IP.** The
real order of operations on a host sending to a remote destination:

1. **IP decision first:** "Is the destination IP on my subnet? No → send toward my gateway
   (a router)." (an L3 decision made by the *host*)
2. **ARP is a downstream helper:** "I've already decided the next hop is the router at
   `192.168.1.1`; now what's its MAC?" ARP just answers that narrow lookup.

So IP makes the decision; ARP merely fetches the MAC to execute it. IP isn't "just for ARP" —
ARP exists to *serve* IP's decision.

**Trace** — Laptop `192.168.1.10` → Server `93.184.215.14`, topology
`[Laptop]-[Switch]-[Router R1]===internet===[Router R2]-[Server]`:

| Step | Who | What | Layer |
|---|---|---|---|
| 1 | Laptop | "Dest IP not on my subnet → send to gateway R1" (routing decision) | L3 |
| 2 | Laptop | ARPs for R1's MAC, builds frame `dstMAC=R1`, `dstIP=server` (unchanged) | L2 helper |
| 3 | Switch | Sees `dstMAC=R1`, forwards toward R1. Never looks at IP. Doesn't route. | L2 |
| 4 | Router R1 | Reads `dstIP`, consults routing table, picks next hop R2, rewrites `srcMAC/dstMAC`, IPs unchanged, TTL−1 | L3 |
| 5 | Router R2 | Routes by dest IP again, rewrites MAC for final hop to server | L3 |

**IP stays fixed end-to-end; MAC is rewritten at every router.** Delete the switch and routing
still happens (laptop straight into R1). Delete the routers and nothing ever leaves the LAN —
routers are what make it "the internet."

*Footnote:* "Layer 3 switches" / multilayer switches do route — because they have **router
functionality built in**. When they route, they act as a router at L3. A pure L2 switch never
routes.

One-liner: *Routers **route** using **IP** (between networks). Switches **forward** using
**MAC** (within one network). ARP doesn't drive anything — it resolves the MAC that IP's
decision already pointed to. IP is the boss; MAC and ARP carry out its orders one hop at a
time.*

## Q: Are switches part of the endpoint machines? Do they only carry traffic to/from the router?

**No on both.** A switch is a **separate physical device** — a standalone box with many ports
(8/24/48). Every device (laptop, server, printer, and the router) gets its own cable to the
switch; the switch is the **central junction of one local network.**

The "part of the endpoint" idea comes from the **NIC (Network Interface Card)** — the chip
with the machine's MAC address, which *is* built into each endpoint. The NIC is the endpoint's
plug; the switch is the external thing all the plugs connect into. Different objects.

It's also not *only* device↔router. A switch handles **all** intra-subnet traffic:

- **Local → local (router never involved):** Laptop → Switch → Printer, both on the same
  subnet — the router never sees the frame.
- **Local → outside:** Laptop → Switch → Router → internet — here the switch just carries the
  frame to the router (which the host already chose at L3); the router then routes.

**Three-role taxonomy:**

| Role | What it is | Job | Layer | Endpoint? |
|---|---|---|---|---|
| Endpoint / host | Laptop, server, phone, printer | Produces & consumes data; full stack | L1–L7 | it **is** the endpoint |
| Switch | Separate box, the LAN's junction | Moves frames **within** one network by MAC | L2 | no |
| Router | Separate box, the network's exit door | Moves packets **between** networks by IP | L3 | no |

Endpoints are where data is born and dies (full seven-layer stack). Switches and routers are
*intermediary infrastructure* that only move other machines' data — a switch at L2, a router at
L3 — and neither runs your applications.

Mail-room analogy: **endpoints** = employees writing/reading mail; **switch** = the building's
internal mail carrier (walks mail between desks *and* to the loading dock) — shared staff, not
any one employee; **router** = the loading dock connecting the building to the outside world.

### Recall check

1. Wi-Fi and Ethernet differ, yet the same HTTP request works over both unchanged. Which
   layers differ, and why doesn't the change ripple up?
   → Only L1 (Physical) and L2 (Data Link) — the medium and frame format. Clean contracts mean
   L3 (IP) just hands a packet down and doesn't care what carries it.
2. A router and a switch both forward traffic — what's the fundamental OSI difference?
   → Switch = **L2**, forwards **frames** within one network by **MAC**. Router = **L3**,
   forwards **packets** *between* networks by **IP**, choosing paths.
3. Why still learn OSI if the internet runs on TCP/IP?
   → It's the universal vocabulary (L2/L3/L4/L7 shorthand) and a layer-by-layer troubleshooting
   framework, even though the deployed stack is TCP/IP's fewer layers.
