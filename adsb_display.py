#!/usr/bin/env python3
"""Live terminal display for ADS-B traffic decoded by dump1090/readsb.

Connects to the SBS (BaseStation) feed that dump1090/readsb publishes on
port 30003, tracks aircraft state by ICAO24 address, and renders a live
table with curses. Run dump1090/readsb separately -- this script only
consumes its network feed.
"""

import argparse
import curses
import socket
import threading
import time

STALE_AFTER_SEC = 60
RECONNECT_DELAY_SEC = 3

# SBS (BaseStation) field indices -- see http://woodair.net/sbs/article/barebones42_socket_data.htm
FIELD_TRANSMISSION_TYPE = 1
FIELD_ICAO = 4
FIELD_CALLSIGN = 10
FIELD_ALTITUDE = 11
FIELD_GROUND_SPEED = 12
FIELD_TRACK = 13
FIELD_LAT = 14
FIELD_LON = 15
FIELD_VERTICAL_RATE = 16
FIELD_SQUAWK = 17
FIELD_ON_GROUND = 21


class AircraftTable:
    def __init__(self, stale_after=STALE_AFTER_SEC):
        self._aircraft = {}
        self._lock = threading.Lock()
        self._stale_after = stale_after
        self.messages_received = 0
        self.connected = False
        self.last_error = None

    def update_from_sbs_line(self, line):
        fields = line.strip().split(",")
        if len(fields) <= FIELD_ICAO or fields[0] != "MSG":
            return

        icao = fields[FIELD_ICAO].strip()
        if not icao:
            return

        with self._lock:
            self.messages_received += 1
            ac = self._aircraft.setdefault(icao, {"icao": icao})
            ac["last_seen"] = time.time()

            def field(idx):
                return fields[idx].strip() if idx < len(fields) and fields[idx].strip() else None

            callsign = field(FIELD_CALLSIGN)
            if callsign:
                ac["callsign"] = callsign

            altitude = field(FIELD_ALTITUDE)
            if altitude:
                ac["altitude"] = altitude

            speed = field(FIELD_GROUND_SPEED)
            if speed:
                ac["speed"] = speed

            track = field(FIELD_TRACK)
            if track:
                ac["track"] = track

            lat = field(FIELD_LAT)
            lon = field(FIELD_LON)
            if lat and lon:
                ac["lat"] = lat
                ac["lon"] = lon

            vrate = field(FIELD_VERTICAL_RATE)
            if vrate:
                ac["vrate"] = vrate

            squawk = field(FIELD_SQUAWK)
            if squawk:
                ac["squawk"] = squawk

            on_ground = field(FIELD_ON_GROUND)
            if on_ground:
                ac["on_ground"] = on_ground == "1" or on_ground == "-1"

    def snapshot(self):
        now = time.time()
        with self._lock:
            stale = [icao for icao, ac in self._aircraft.items()
                     if now - ac["last_seen"] > self._stale_after]
            for icao in stale:
                del self._aircraft[icao]
            return list(self._aircraft.values()), self.messages_received, self.connected, self.last_error


def feed_reader(table, host, port, stop_event):
    """Background thread: connect to the SBS feed and keep the table updated, reconnecting on failure."""
    while not stop_event.is_set():
        try:
            with socket.create_connection((host, port), timeout=10) as sock:
                sock.settimeout(1.0)
                table.connected = True
                table.last_error = None
                buf = b""
                while not stop_event.is_set():
                    try:
                        chunk = sock.recv(4096)
                    except socket.timeout:
                        continue
                    if not chunk:
                        raise ConnectionError("feed closed by remote host")
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        if line:
                            table.update_from_sbs_line(line.decode("ascii", errors="replace"))
        except OSError as exc:
            table.connected = False
            table.last_error = str(exc)
        if not stop_event.is_set():
            time.sleep(RECONNECT_DELAY_SEC)


def fmt(value, width, right=False):
    text = "" if value is None else str(value)
    if len(text) > width:
        text = text[:width]
    return text.rjust(width) if right else text.ljust(width)


COLUMNS = [
    ("ICAO", "icao", 6, False),
    ("Callsign", "callsign", 9, False),
    ("Alt(ft)", "altitude", 8, True),
    ("Spd(kt)", "speed", 7, True),
    ("Trk", "track", 5, True),
    ("VRate", "vrate", 7, True),
    ("Squawk", "squawk", 6, False),
    ("Lat", "lat", 10, True),
    ("Lon", "lon", 10, True),
    ("Age(s)", "age", 6, True),
]


def draw(stdscr, table, host, port, refresh_rate):
    curses.curs_set(0)
    stdscr.nodelay(True)
    sort_key = "callsign"

    while True:
        aircraft, msg_count, connected, last_error = table.snapshot()
        now = time.time()
        for ac in aircraft:
            ac["age"] = int(now - ac["last_seen"])

        aircraft.sort(key=lambda ac: (ac.get(sort_key) or "~", ac["icao"]))

        stdscr.erase()
        max_y, max_x = stdscr.getmaxyx()

        status = "CONNECTED" if connected else "DISCONNECTED"
        header = f" pyplanes ADS-B monitor  |  {host}:{port}  |  {status}  |  {len(aircraft)} aircraft  |  {msg_count} msgs "
        stdscr.addnstr(0, 0, header.ljust(max_x), max_x, curses.A_REVERSE)

        if not connected and last_error:
            stdscr.addnstr(1, 0, f" reconnecting... last error: {last_error}"[:max_x], max_x, curses.A_DIM)
            col_row = 2
        else:
            col_row = 1

        col_line = " ".join(fmt(name, width) for name, _, width, _ in COLUMNS)
        stdscr.addnstr(col_row, 0, col_line, max_x, curses.A_BOLD)

        row = col_row + 1
        for ac in aircraft:
            if row >= max_y - 1:
                break
            cells = []
            for _, key, width, right in COLUMNS:
                cells.append(fmt(ac.get(key), width, right))
            stdscr.addnstr(row, 0, " ".join(cells), max_x)
            row += 1

        footer = " q: quit "
        try:
            stdscr.addnstr(max_y - 1, 0, footer.ljust(max_x), max_x - 1, curses.A_REVERSE)
        except curses.error:
            pass  # writing to the bottom-right cell can raise even though the text painted fine

        stdscr.refresh()

        try:
            ch = stdscr.getch()
        except curses.error:
            ch = -1
        if ch in (ord("q"), ord("Q")):
            return

        time.sleep(refresh_rate)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="dump1090/readsb host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=30003, help="SBS feed port (default: 30003)")
    parser.add_argument("--stale-after", type=int, default=STALE_AFTER_SEC,
                         help="drop aircraft not heard from in this many seconds (default: %(default)s)")
    parser.add_argument("--refresh-rate", type=float, default=1.0,
                         help="screen refresh interval in seconds (default: %(default)s)")
    args = parser.parse_args()

    table = AircraftTable(stale_after=args.stale_after)
    stop_event = threading.Event()
    reader_thread = threading.Thread(
        target=feed_reader, args=(table, args.host, args.port, stop_event), daemon=True
    )
    reader_thread.start()

    try:
        curses.wrapper(draw, table, args.host, args.port, args.refresh_rate)
    finally:
        stop_event.set()


if __name__ == "__main__":
    main()
