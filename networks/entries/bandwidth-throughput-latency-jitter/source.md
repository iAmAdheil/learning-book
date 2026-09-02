---
slug: bandwidth-throughput-latency-jitter
title: Bandwidth vs Throughput vs Latency vs Jitter
topic: networks
bloom-level: some
created: 2026-07-12
updated: 2026-07-12
published: 2026-07-20
related: [how-internet-works, encapsulation-decapsulation]
tags: [fundamentals, performance, bandwidth, throughput, latency, jitter, rtt, bandwidth-delay-product, cdn, qos]
sources:
  - "Stuart Cheshire, 'It's the Latency, Stupid' (1996–97)"
---

## Answer

**The concept:** Four performance words that everyone conflates but that measure completely
different things. Two are *rates* (bandwidth, throughput — bits/sec); two are *times* (latency,
jitter — milliseconds). Confusing them causes the classic costly mistake: throwing bandwidth at
a problem that was never a bandwidth problem.

### The unifying analogy: a highway

- **Bandwidth** = number of **lanes** (max cars that could flow at once).
- **Latency** = **length of the road** / how long one car takes end-to-end.
- **Throughput** = cars **actually arriving** per hour (given traffic, accidents, tolls).
- **Jitter** = how **irregular the spacing** is between arriving cars.

These are independent: a 12-lane highway (huge bandwidth) can still be 3,000 km long (high
latency). Adding lanes doesn't shorten the road.

### Precise definitions

| Term | Measures | Unit | Highway | Key point |
|---|---|---|---|---|
| Bandwidth | Maximum capacity of a link | bits/sec | # lanes | A rate *ceiling*, not a speed |
| Throughput | Actual data delivered | bits/sec | cars/hour | Always ≤ bandwidth |
| Latency | Delay to travel | ms (one-way or RTT) | road length | About time, not rate |
| Jitter | Variation in latency | ms | irregular spacing | Consistency; kills real-time media |

### The core misconception: bandwidth is not speed

Higher bandwidth does **not** make a single bit arrive sooner — it lets **more bits travel in
parallel**. One bit NY→London takes the same time on 10 Mbps as on 10 Gbps, because that time is
set by the road length (latency = speed of light × distance), not the lane count. Widening the
highway doesn't make your car drive faster. This is why "upgrade to gigabit" often does nothing
for how *snappy* the internet feels: web browsing is usually latency-bound, not bandwidth-bound.

### Why throughput < bandwidth

Bandwidth is the ceiling; throughput is reality, reduced by: protocol overhead (headers, see
[[encapsulation-decapsulation]]), congestion, packet loss + retransmission, and **latency
itself** (TCP can only have so much data in flight before it must wait for an ACK — see BDP
below).

### Latency, unpacked (four delays — full treatment in the latency deep-dive topic)

1. **Propagation** = distance ÷ signal speed (~⅔ c in fiber ≈ 200,000 km/s). A **physics floor**
   you cannot beat — NY↔London is ~28 ms one-way minimum, forever.
2. **Transmission** = packet size ÷ bandwidth (time to push bits onto the wire; shrinks with
   more bandwidth).
3. **Queuing** = waiting in router buffers.
4. **Processing** = router/host inspection & forwarding.

Propagation dominates over distance — pure physics. This is *why CDNs exist*: they don't add
bandwidth, they move content physically closer to cut propagation distance, hence latency. You
can buy bandwidth; you cannot buy a shorter speed-of-light path — only a shorter distance.

### "It's the latency, stupid"

Once you have "enough" bandwidth, adding more stops helping; latency is what you can't buy your
way out of, and it's usually the real bottleneck for interactive workloads.

- **10 GB file download** → **bandwidth/throughput-bound.** More lanes = finishes faster.
- **Webpage with 80 small resources** → **latency-bound.** Each request needs a round trip; 10
  sequential round trips at 100 ms RTT = 1 full second of pure waiting, and gigabit bandwidth
  changes it by ~nothing.

Much of modern networking is a **war on round trips**, not a hunt for bandwidth: HTTP/2
multiplexing, keepalives/connection reuse, TLS 1.3 (1-RTT), QUIC (0-RTT), CDNs. For system
design: **diagnose latency-bound vs bandwidth-bound before optimizing** — they need opposite
fixes.

### Bandwidth-delay product (why latency caps throughput)

**BDP = bandwidth × RTT** = data that can be "in flight" at once (the pipe's *volume*, not just
its width). For TCP, **throughput ≈ window size ÷ RTT**. If the TCP window is smaller than the
BDP, you can't fill the pipe — you send a burst, then stall waiting for ACKs. This is the
**"long fat network"** problem: a high-bandwidth, high-latency link throttled by latency +
window size, not bandwidth. Ties into the flow-control / sliding-window topic.

### Jitter

Jitter = variation in latency, packet to packet. Average can be great while jitter is terrible.
Irrelevant for downloads (TCP reassembles in order; only total throughput matters). The enemy of
**real-time media** (VoIP, video, gaming): irregular arrivals cause stutter. Fix = a **jitter
buffer** (hold packets a few ms to smooth timing, trading a little latency for consistency).
This is why **QoS** exists — prioritize jitter-sensitive voice over bulk traffic.

### Gotchas

- **Bits vs Bytes** (#1 practical confusion): bandwidth is in **bits** (Mb**p**s); files are in
  **bytes** (MB). 8 bits = 1 byte, so **100 Mbps ≈ 12.5 MB/s** max. A "1 Gbps" line is ~125 MB/s.
- **"More bandwidth = faster"** — only for bandwidth-bound work; useless for latency-bound work.
- **Latency ≠ throughput:** "slow to start responding" (latency) vs "slow to transfer bulk"
  (throughput) are different problems with different fixes.
- **RTT vs one-way:** latency is often quoted as RTT (what `ping` shows) ≈ 2× one-way.
  Interactive protocols pay RTTs.
- **You can't beat propagation delay** — only shorten distance (edge/CDN).

### Recall check

1. Satellite plan: 200 Mbps but 600 ms RTT. Great for (a) big game downloads or (b) video call?
   → (a) great (bandwidth-bound, delay amortized); (b) terrible (latency-bound, every
   interaction pays 600 ms). Bandwidth and latency are independent.
2. Slow webpage — upgrade server 1→10 Gbps: when does it help?
   → Only if bandwidth-bound (saturating the link with big/many transfers). If latency-bound
   (round trips, slow backend, far users), it changes ~nothing.
3. Two links avg 40 ms; A has 2 ms jitter, B has 35 ms jitter — which is worse for Zoom?
   → B — real-time audio needs consistent arrival; equal average doesn't save it because
   playback breaks on variation, forcing a larger jitter buffer that adds delay.

### One thing to walk away with

Bandwidth (lanes) and latency (road length) are **independent**. Bandwidth/throughput are
*rates*; latency/jitter are *times* — you can't trade one for the other. More bandwidth helps
bulk transfer; only lower latency helps interactivity, and latency is floored by physics, which
is why we move data closer (CDNs) rather than widen pipes. Always ask: **latency-bound or
bandwidth-bound?**
