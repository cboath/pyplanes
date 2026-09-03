# pyplanes

Live terminal display of nearby aircraft, decoded from an RTL-SDR ADS-B
antenna on a Raspberry Pi.

## How it works

Raw 1090MHz ADS-B signals are demodulated by **readsb** (a maintained
fork of dump1090), which talks to the RTL-SDR USB dongle and publishes
decoded messages over the network in BaseStation/SBS format on port
30003. [adsb_display.py](adsb_display.py) connects to that feed and
renders a live-updating table in the terminal.

```
RTL-SDR dongle --> readsb (decodes RF) --> SBS feed :30003 --> adsb_display.py
```

## 1. Hardware

- Raspberry Pi (3/4/5, or Zero 2 W) running Raspberry Pi OS
- An RTL-SDR dongle (e.g. RTL-SDR Blog v3/v4, or a cheap RTL2832U/R820T2 stick)
- A 1090MHz ADS-B antenna connected to the dongle, with reasonable line of sight/height

## 2. Install the decoder (readsb)

On the Pi:

```bash
sudo apt update
sudo apt install -y curl gnupg
curl -fsSL https://github.com/wiedehopf/adsb-scripts/raw/master/readsb-install.sh -o readsb-install.sh
sudo bash readsb-install.sh
```

This installs readsb as a systemd service, blacklists the kernel DVB
drivers that conflict with the RTL-SDR, and starts decoding automatically
on boot. Verify it's running:

```bash
sudo systemctl status readsb
```

Once running, readsb listens on `127.0.0.1:30003` for SBS-format
connections (also available on other ports for Beast format and
`aircraft.json`, which this script doesn't need).

If you'd rather use FlightAware's dump1090-fa instead, that also exposes
an SBS feed on port 30003 and works as a drop-in alternative -- follow
FlightAware's own install instructions for that package.

## 3. Run the display

Needs only the Python 3 standard library (`curses`, `socket`,
`threading`) -- no extra packages to install.

```bash
python3 adsb_display.py
```

By default it connects to `127.0.0.1:30003`. To view it from another
machine on the network, either run the script on the Pi directly over
SSH, or point it at the Pi's IP:

```bash
python3 adsb_display.py --host <pi-ip-address> --port 30003
```

(Ensure port 30003 is reachable if connecting remotely; readsb binds it
to all interfaces by default.)

### Options

- `--host` -- decoder host (default `127.0.0.1`)
- `--port` -- SBS feed port (default `30003`)
- `--stale-after` -- seconds without an update before an aircraft is dropped from the table (default `60`)
- `--refresh-rate` -- screen redraw interval in seconds (default `1.0`)

Press `q` to quit.

## What you'll see

A live table with one row per aircraft currently being received: ICAO24
address, callsign, altitude, ground speed, track, vertical rate, squawk,
last known lat/lon, and seconds since last update. The header shows
connection status and total message count; the script auto-reconnects
if readsb restarts.

## 4. Feed FlightAware / ADS-B Exchange (optional)

readsb can serve multiple consumers off the same dongle at once, so you
can feed community networks alongside running `adsb_display.py` -- no
extra hardware needed. Feeder clients connect to readsb's Beast output
on port 30005 (more efficient than the SBS feed used for the display).

Most networks give you a free premium account tier ("feeder credit") in
exchange for feeding them your local data.

### FlightAware (piaware)

```bash
sudo apt install -y piaware
sudo piaware-config -receiver-type relay -receiver-host 127.0.0.1 -receiver-port 30005
sudo systemctl restart piaware
sudo piaware-status
```

`piaware-status` prints a site/claim number once it's connected. Claim
the station at
[flightaware.com/adsb/piaware/claim](https://flightaware.com/adsb/piaware/claim)
to link it to your FlightAware account and start earning feeder stats
(a free FlightAware Enterprise account tier while you keep feeding).

### ADS-B Exchange

```bash
curl -fsSL https://raw.githubusercontent.com/adsbxchange/adsb-exchange/master/install.sh | sudo bash
```

The installer prompts for the local Beast source (`127.0.0.1:30005`)
and registers a feeder UUID automatically. Create an ADS-B Exchange
account and associate that UUID to get feeder credit (free API/stats
access). Local feed stats are typically available at
`http://<pi-ip-address>:30053` once it's running.

Both feeders run as independent systemd services alongside readsb and
`adsb_display.py`, and don't require any changes to this script.
