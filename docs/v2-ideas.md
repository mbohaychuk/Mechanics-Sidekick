# v2 ideas — form factor & connectivity (phone-centric)

Captured during v1 design. **Not committed work — a parking lot for later.** v1 is
decided: laptop-hosted local web UI (NiceGUI), `obd-mcp` over MCP for live vehicle
data, cloud generation (pluggable, Ollama optional), local embeddings/RAG.

These ideas explore going **laptop-free / phone-centric** in a future version.

## The hard constraint that shapes everything

A **browser cannot open a raw TCP socket**, and a WiFi ELM327 speaks raw TCP on
`:35000`. So a web app **cannot** reach a WiFi scanner. Only two things can talk to a
scanner from a phone:

- a **native mobile app** (native BT/WiFi sockets), or
- a **browser + Bluetooth adapter** via the **Web Bluetooth API** (BLE only).

Web Bluetooth is **Chrome/Android + desktop Chrome/Edge only — not iOS Safari**. So any
browser-driven BLE path is Android-only unless wrapped in a native app.

This means a phone-centric v2 implies a **BLE adapter** (not the current WiFi unit).

---

## Idea A — all-in-browser (Web Bluetooth + WASM/TS decode + cloud backend)

Browser connects to the BLE adapter via Web Bluetooth; OBD decoding runs client-side
(either python-OBD's decode logic in **Pyodide/WASM**, or a **TypeScript** port); LLM +
RAG live in a cloud backend.

- **Pyodide caveat:** runs pure-Python decode, but python-OBD's transport is `pyserial`
  (OS sockets) which does **not** exist in WASM — you'd feed Web Bluetooth bytes into the
  Python decode and replace the transport. And the MCP-server framing dissolves in-browser.
- Since you're already in JS-land, **porting the (small) decode layer to TS** is likely
  cleaner than hauling a multi-MB Python runtime into a phone browser. Pyodide's only win
  is "reuse the exact Python."

**Verdict:** reuses the *decode brains* but rebuilds the plumbing; Android-only; loses the
`obd-mcp`/MCP reuse. A substantial rewrite, not an extension.

---

## Idea B — thin bridge + cloud `obd-mcp` tunnel  *(preferred)*

Keep the phone **dumb**: it only (1) talks BLE to the adapter and (2) relays bytes over a
WebSocket. The real brains run in the cloud, where `obd-mcp` runs **unchanged in its
logic** with a transport whose "serial port" is the tunnel back to the phone's Bluetooth.

```
ELM327 ─BLE─ Phone (thin BLE↔WS bridge) ═══wss═══ Cloud
                                                    ├─ obd-mcp  (WebSocket→PTY transport)
                                                    ├─ LLM (Claude API) → calls obd-mcp tools (MCP)
                                                    └─ RAG/manuals + web UI → served to phone browser
```

python-OBD opens the tunnel-backed port, sends `010C`, the bytes ride the WebSocket to the
car and back. The cloud LLM connects to `obd-mcp` as an MCP host and calls the tools
normally — it never knows the car is remote. Bidirectional, transparent.

**Why this is the better v2:**

- The phone stays a **trivial relay** — a Web Bluetooth page (Android) *or* a tiny native
  app (~one screen; works on **iOS too** via native BT). A fraction of a full native OBD app.
- `obd-mcp` is reused **wholesale** — only a new transport backend.
- **MCP earns its keep again** — `obd-mcp` is a real server the cloud LLM connects to.

**The hook already exists:** the v1 `obd-mcp` transport seam (`resolve_transport` → a
`Transport` that owns a bridge and hands python-OBD a PTY) is exactly this. A
`WebSocketTransport` is just a new backend — the same `bleak→PTY` pattern, byte source =
WebSocket instead of local BLE. v2 reuses v1's architecture.

**Gotchas:**

- **Latency** — every OBD query is phone→cloud→phone over the internet, *on top of* BLE +
  the already-slow ELM327. Live dashboards sample slower; batch reads. This is the real cost.
- **Reliability** — more failure points (BLE drop, WS drop); reconnection logic matters
  (the hardened open/close lifecycle helps).
- **Privacy** — car data goes to the cloud (same trade as cloud generation; fully-local gone).
- **Security & sessions** — `wss://` + auth tokens; cloud maps each phone socket to its own
  `obd-mcp` connection.

---

## Status

Deferred. v1 (laptop + local web UI) ships first and proves the experience. Idea B is the
natural phone-centric follow-up because it preserves the `obd-mcp` reuse and the MCP seam;
Idea A is a fallback only if a fully client-side (no backend) app is ever wanted.
