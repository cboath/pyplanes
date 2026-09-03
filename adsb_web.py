#!/usr/bin/env python3
"""Live web display for ADS-B traffic decoded by dump1090/readsb.

Same feed logic as adsb_display.py, but serves a browser-based table
over HTTP instead of drawing a curses UI -- useful for running headless
in a Docker container. Run dump1090/readsb separately -- this script
only consumes its network feed.
"""

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from adsb_feed import STALE_AFTER_SEC, AircraftTable, feed_reader

INDEX_HTML = b"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>pyplanes ADS-B monitor</title>
<style>
  :root { color-scheme: dark; }
  body { background: #0b0e14; color: #d6deeb; font: 14px/1.4 ui-monospace, "SF Mono", Menlo, monospace; margin: 0; }
  #status { background: #1c2333; padding: 8px 12px; display: flex; gap: 24px; align-items: center; }
  #status .dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; margin-right: 6px; }
  .connected .dot { background: #4fd671; }
  .disconnected .dot { background: #e05561; }
  table { width: 100%; border-collapse: collapse; }
  th, td { text-align: right; padding: 4px 10px; white-space: nowrap; }
  th:nth-child(1), td:nth-child(1), th:nth-child(2), td:nth-child(2) { text-align: left; }
  thead th { position: sticky; top: 0; background: #131826; border-bottom: 1px solid #2a3350; cursor: default; }
  tbody tr:nth-child(odd) { background: #10141f; }
  tbody tr:hover { background: #1c2333; }
  #error { color: #e0a561; padding: 4px 12px; }
</style>
</head>
<body>
  <div id="status" class="disconnected">
    <span><span class="dot"></span><span id="conn-text">connecting...</span></span>
    <span id="feed-addr"></span>
    <span id="count">0 aircraft</span>
    <span id="msgs">0 msgs</span>
  </div>
  <div id="error"></div>
  <table>
    <thead>
      <tr>
        <th>ICAO</th><th>Callsign</th><th>Alt(ft)</th><th>Spd(kt)</th>
        <th>Trk</th><th>VRate</th><th>Squawk</th><th>Lat</th><th>Lon</th><th>Age(s)</th>
      </tr>
    </thead>
    <tbody id="rows"></tbody>
  </table>
<script>
const COLS = ["icao", "callsign", "altitude", "speed", "track", "vrate", "squawk", "lat", "lon", "age"];

async function poll() {
  try {
    const res = await fetch("/api/aircraft");
    const data = await res.json();
    render(data);
  } catch (e) {
    document.getElementById("conn-text").textContent = "page disconnected from server";
  } finally {
    setTimeout(poll, 1000);
  }
}

function render(data) {
  const statusEl = document.getElementById("status");
  statusEl.className = data.connected ? "connected" : "disconnected";
  document.getElementById("conn-text").textContent = data.connected ? "CONNECTED" : "DISCONNECTED";
  document.getElementById("feed-addr").textContent = data.host + ":" + data.port;
  document.getElementById("count").textContent = data.aircraft.length + " aircraft";
  document.getElementById("msgs").textContent = data.messages_received + " msgs";
  document.getElementById("error").textContent =
    (!data.connected && data.last_error) ? "reconnecting... last error: " + data.last_error : "";

  const aircraft = data.aircraft.slice().sort((a, b) => {
    const ca = a.callsign || "~", cb = b.callsign || "~";
    return ca === cb ? a.icao.localeCompare(b.icao) : ca.localeCompare(cb);
  });

  const rows = document.getElementById("rows");
  rows.innerHTML = "";
  for (const ac of aircraft) {
    const tr = document.createElement("tr");
    tr.innerHTML = COLS.map(c => `<td>${ac[c] ?? ""}</td>`).join("");
    rows.appendChild(tr);
  }
}

poll();
</script>
</body>
</html>
"""


def make_handler(table, host, port):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass  # keep container logs quiet; readsb/docker already log connection state

        def do_GET(self):
            if self.path == "/" or self.path == "/index.html":
                self._send(200, "text/html; charset=utf-8", INDEX_HTML)
            elif self.path == "/api/aircraft":
                aircraft, msg_count, connected, last_error = table.snapshot()
                now = time.time()
                for ac in aircraft:
                    ac["age"] = int(now - ac["last_seen"])
                payload = {
                    "aircraft": [{k: v for k, v in ac.items() if k != "last_seen"} for ac in aircraft],
                    "messages_received": msg_count,
                    "connected": connected,
                    "last_error": last_error,
                    "host": host,
                    "port": port,
                }
                self._send(200, "application/json", json.dumps(payload).encode("utf-8"))
            else:
                self._send(404, "text/plain", b"not found")

        def _send(self, status, content_type, body):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="dump1090/readsb host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=30003, help="SBS feed port (default: 30003)")
    parser.add_argument("--stale-after", type=int, default=STALE_AFTER_SEC,
                         help="drop aircraft not heard from in this many seconds (default: %(default)s)")
    parser.add_argument("--listen-host", default="0.0.0.0", help="web server bind address (default: %(default)s)")
    parser.add_argument("--listen-port", type=int, default=8080, help="web server port (default: %(default)s)")
    args = parser.parse_args()

    table = AircraftTable(stale_after=args.stale_after)
    stop_event = threading.Event()
    reader_thread = threading.Thread(
        target=feed_reader, args=(table, args.host, args.port, stop_event), daemon=True
    )
    reader_thread.start()

    server = ThreadingHTTPServer((args.listen_host, args.listen_port), make_handler(table, args.host, args.port))
    print(f"pyplanes web display listening on http://{args.listen_host}:{args.listen_port}  "
          f"(feed: {args.host}:{args.port})")
    try:
        server.serve_forever()
    finally:
        stop_event.set()


if __name__ == "__main__":
    main()
