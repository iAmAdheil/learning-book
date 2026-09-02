---
slug: how-internet-works
title: How the Internet Works End-to-End — A Packet's Journey
topic: networks
bloom-level: some
created: 2026-07-07
updated: 2026-08-06
published: 2026-07-20
related: [osi-model, tcp-ip-model, encapsulation-decapsulation, bandwidth-throughput-latency-jitter, ethernet, arp, ipv4-addressing, subnetting, vlsm]
tags: [fundamentals, dns, tcp, udp, ip, routing, arp, encapsulation]
sources: []
---

## Answer

**The concept:** Every web request is a physical journey. Typing `https://example.com`
and getting a page back involves name resolution, address discovery, layered packaging,
connection setup, and dozens of router-to-router hops — twice. Understanding this whole
journey once gives every other networking topic a place to hang, because each of them is a
zoom-in on one leg of this trip.

The scenario: a laptop on a home network requests `https://example.com`. In ~100–300 ms a
page appears. In that fraction of a second, data crossed several physical machines, several
protocols negotiated, and bytes traveled thousands of kilometers of copper, fiber, and radio
— and back.

### Act 1 — Name resolution (DNS)

Computers route by **IP address** (e.g. `93.184.215.14`), not names. So the first step is a
**DNS (Domain Name System)** lookup — the internet's phone book. The laptop asks a DNS
resolver "what is the IP for `example.com`?" If not cached, the resolver walks a hierarchy:
root server → `.com` TLD server → the authoritative server for `example.com`, which returns
the IP. The answer is **cached** (governed by a TTL, time-to-live) so future lookups are
instant. DNS happens *before* any real connection, usually over UDP. Mental model: *name in,
IP out, and it's cached.*

### Act 2 — Leaving the local network (ARP + default gateway)

The destination server is far away; a laptop can only physically talk to devices on its own
**local network (LAN)**. It applies a rule: *"Is this destination IP on my own subnet? No? Then
hand the packet to my* **default gateway** *(the home router) and let it forward the packet
onward."*

To hand the packet to the router, the laptop needs the router's **MAC address** (the hardware
address burned into its network chip). It knows the router's IP (e.g. `192.168.1.1`) but not
its MAC, so it uses **ARP (Address Resolution Protocol)** to ask on the local network: "Who has
`192.168.1.1`? Tell me your MAC." The router replies with its MAC.

**The single most important idea about how data moves:**

> **IP addresses are the end-to-end destination (the whole journey). MAC addresses are
> hop-to-hop (this one link only).** At every hop the IP addresses stay the same, but the MAC
> addresses get rewritten for the next link.

Analogy: mailing a letter. The **envelope address (IP)** never changes — it names the final
recipient. But the letter physically passes mailbox → local post office → sorting hub →
destination hub → carrier. Each handoff is a MAC-level, local-only relationship. The envelope
address is the *plan*; the handoffs are the *execution*.

### Act 3 — Building the packet (encapsulation)

Before anything goes on the wire, the data is wrapped in layers, each adding its own header
for its own job — **encapsulation**:

```
        ┌─────────────────────────────────────────────┐
Frame → │ Eth │ IP │ TCP │ TLS │ HTTP: "GET /"         │ ← the actual request
        └─────────────────────────────────────────────┘
          ▲     ▲     ▲     ▲
          │     │     │     └─ encryption (padlock)
          │     │     └─ "port 443, reliable, in order"
          │     └─ "from my IP → to 93.184.215.14"
          └─ "from my MAC → to router's MAC" (this hop only)
```

- **HTTP** (application) writes the request: *"GET / — give me the homepage."*
- **TLS** encrypts it (the `s` in `https`).
- **TCP** (transport) adds a header: *"destination port 443, delivered reliably and in order."*
- **IP** (network) adds source/destination IP — the end-to-end plan.
- **Ethernet** (link) adds source/destination MAC — for this one hop to the router.

Then it's turned into **bits** and pushed onto the wire. The real message is buried deepest,
wrapped in progressively more shipping-and-handling metadata. Every layer only reads its own
header and treats everything inside as opaque cargo. This nesting is exactly what the
OSI / TCP-IP layer models describe.

### Act 4 — Establishing the connection (TCP handshake + TLS handshake)

Because this is `https`, two negotiations happen before the request is even sent:

**TCP three-way handshake** — reliability requires both sides to agree they are talking first:
```
Laptop → Server:  SYN      "Let's talk? Here's my starting sequence #."
Server → Laptop:  SYN-ACK  "Sure. Got yours, here's mine."
Laptop → Server:  ACK      "Great, we're connected."
```

**TLS handshake** — the server proves its identity with a **certificate** signed by a trusted
authority, and both sides agree on a shared secret key.

Only then does the browser send the encrypted `GET /`. This is why round-trips and latency
matter: several happen before a single byte of webpage moves.

### Act 5 — Crossing the internet (routing, hop by hop)

The internet is not one network but ~75,000 independent networks (**Autonomous Systems**: ISPs,
backbone carriers, data centers) that agree to pass traffic. At every **router** the same tiny
decision repeats:

1. Read the destination **IP**.
2. Consult the **routing table**: which neighbor gets this closer?
3. Rewrite the **MAC** header for the next hop, decrement **TTL** (so lost packets eventually
   die instead of looping forever), and forward.

No single router knows the whole path — each knows only "the next best step," like driving
cross-country using only road signs. Full-route knowledge is *distributed* across thousands of
routers and kept roughly in sync by routing protocols (**BGP** between networks, **OSPF** inside
one). `traceroute example.com` prints this chain of hops.

**Crucial subtlety:** packets are independent. Two packets from one request can take different
paths and arrive out of order. The network makes **no guarantees** — it is "best effort."
Reliability is faked at the edges by TCP, not provided by the middle. This is the internet's
deepest design choice (packet switching vs circuit switching) and why it is so robust: no
central brain to fail.

### Act 6 — Arrival and response (decapsulation)

At the server (in reality often a load balancer or CDN edge first) everything unwraps in
reverse — **decapsulation**: Ethernet stripped → IP checked → TCP matched to the connection →
TLS decrypted → HTTP finally read. The server builds the HTML response and the entire process
runs in reverse: HTTP → TLS → TCP → IP (source/dest swapped) → Ethernet, back through the maze
of routers (possibly a different path), to the laptop, back up its stack, and the browser
renders the page. The HTML often references more resources, triggering dozens more journeys
(reusing the open connection where possible via keep-alive / connection pooling).

### TL;DR

A name is typed. **DNS** turns it into an IP. The laptop **ARP**s for its gateway and hands the
packet to the router, because it can only reach things on its own link. Data is **encapsulated**
— HTTP inside TLS inside TCP inside IP inside Ethernet. A **TCP handshake** and **TLS handshake**
establish a reliable, encrypted connection. Packets then hop router-to-router across thousands
of independent networks; **IP addresses stay fixed end-to-end while MAC addresses are rewritten
every hop**, each router doing longest-prefix routing toward the destination. The network is
**best-effort and unreliable by design** — TCP fakes reliability at the two ends. The server
**decapsulates** back up the stack, generates a response, and the whole thing runs in reverse.

### Two mental models to burn in

1. **Two kinds of addresses, two scopes.** IP = the whole trip (end-to-end, never changes).
   MAC = one hop (rewritten constantly). Confusing these is the #1 beginner mistake; clarity
   here makes routing, switching, NAT, and ARP all click later.
2. **Smart edges, dumb middle.** The network core just forwards packets, best-effort, no
   promises. All intelligence — reliability, ordering, encryption, retransmission — lives in the
   endpoints. This is the opposite of the old phone system (smart middle, dumb phones), and it
   is *why* the internet scaled.

### Recall check

1. Why does the laptop ARP for the **router's** MAC instead of the **server's** MAC, even
   though the server is the real destination?
   → Because a device can only physically talk to others on its own local link. The server is
   unreachable directly, so the laptop hands the packet to its gateway and trusts routers to
   relay it. MAC addressing is always local, so it must be the router's MAC.
2. If IP identifies the final destination, why are MAC addresses needed at all?
   → IP is a logical end-to-end *plan*, but delivery happens one physical link at a time. Each
   link needs a way to say "this frame is for the device physically next to me" — that's MAC.
   IP says *where ultimately*; MAC says *who's next*.
3. What guarantees does the network in the middle make, and who provides reliability?
   → None — it is best-effort and can drop, reorder, or duplicate packets. TCP, running only on
   the two endpoints, detects loss and retransmits to create the illusion of a reliable stream.

## Q: If TCP "runs only on the endpoints," is it still a protocol? And how is that different from UDP?

**Yes, TCP is a protocol** — an agreed-upon set of rules for a conversation ("if I send X, you
reply Y"). But rules must be *executed by something*. TCP's rules are implemented in **software,
specifically in the operating system kernel** (the TCP/IP stack) on each machine. So "TCP runs
only on the endpoints" means: **the code that speaks TCP lives on the two end machines; the
routers in the middle do not run TCP at all** — they read only the IP header, forward the
packet, and ignore everything inside.

```
   LAPTOP                 routers in the middle              SERVER
 ┌────────┐          ┌─────┐   ┌─────┐   ┌─────┐          ┌────────┐
 │  TCP   │──────────│ IP  │───│ IP  │───│ IP  │──────────│  TCP   │
 │(kernel)│          │only │   │only │   │only │          │(kernel)│
 └────────┘          └─────┘   └─────┘   └─────┘          └────────┘
     ▲                                                        ▲
     └──────────── TCP conversation is only between these two ────────┘
```

Routers are like postal trucks — they carry the sealed envelope and never open it.

**TCP vs UDP.** Both are transport-layer (L4) protocols, both run on endpoints (kernel
software, not routers), and both use **ports** to identify the destination app. That shared
structure is why they can feel similar. But their jobs are opposite:

| | UDP | TCP |
|---|---|---|
| Detects lost packets? | No | Yes |
| Retransmits lost data? | No | Yes |
| Reorders packets correctly? | No | Yes |
| Handshake before sending? | No (just fire) | Yes (SYN/SYN-ACK/ACK) |
| Guarantees delivery? | No | Yes (or reports failure) |

"Detects loss and retransmits to create the illusion of a reliable stream" is exactly the thing
UDP does **not** do. UDP is fire-and-forget: if a packet drops, it is simply gone.

**The deeper insight:** raw IP gives only unreliable, best-effort delivery. **UDP ≈ raw IP with
almost nothing added** — the thinnest wrapper, just ports, exposing the network's native "no
promises" nature to the app. **TCP = raw IP + a reliability machine** (sequence numbers,
acknowledgments, retransmission, ordering, flow control) that hides the unreliability behind a
clean, ordered pipe. So the intuition "isn't the underlying network kind of UDP-like/unreliable?"
is correct — the network *is* unreliable; UDP leaves that exposed, TCP hides it.

One-liner: *The network is dumb and unreliable. UDP hands you that unreliability raw and fast.
TCP does the extra work (ACKs + retransmits) to hide it and give you a clean, ordered stream.*

Why ever choose UDP? Because reliability costs time (handshakes, waiting for ACKs, retransmit
delays). For a video call or a game, a slightly-dropped frame *now* beats a perfectly-recovered
frame 200 ms *late*. Speed over guarantees — the core TCP-vs-UDP tradeoff.
