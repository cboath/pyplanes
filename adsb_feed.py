"""Shared ADS-B feed logic: SBS parsing, aircraft state tracking, and the
background feed-reader thread. Used by both the curses display
(adsb_display.py) and the web display (adsb_web.py).
"""

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
