#!/usr/bin/env python3
"""Live terminal display for ADS-B traffic decoded by dump1090/readsb.

Connects to the SBS (BaseStation) feed that dump1090/readsb publishes on
port 30003, tracks aircraft state by ICAO24 address, and renders a live
table with curses. Run dump1090/readsb separately -- this script only
consumes its network feed.
"""

import argparse
import curses
import threading
import time

from adsb_feed import STALE_AFTER_SEC, AircraftTable, feed_reader


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
