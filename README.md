# Flight Tracker for Kodi

A Kodi addon for watching aircraft out of the window. It shows **where the
aircraft you are looking at came from and where it is going**, as a split-flap
departure board.

Built for a high floor in Bangkok with a view of Suvarnabhumi, but the location,
window bearing and reference airports are all settings, so it works anywhere.

<img src="script.flighttracker/resources/media/icon.png" width="96" alt="">

## What it shows

Not a list to scan. The board shows what is happening **right now**: the aircraft
currently on final approach, and the one currently climbing out.

```
  ┌──────────┐   ARRIVAL                                    LANDING
  │   THAI   │   TOKYO  >  BANGKOK
  └──────────┘   THA641   787 8   HS-TQE

  ┌──────────┐   DEPARTURE                               TAKING OFF
  │ Air Asia │   BANGKOK  >  KRABI
  └──────────┘   AIQ3215   A21N   HS-EAD
```

Amber on black, in the register a real airport board uses: `LANDING`, `ON FINAL`,
`APPROACHING`, `TAKING OFF`, `CLIMBING OUT`. Each row carries the airline's logo,
the route, the flight number and the airframe. When a row changes, the letters
flip over to the new text a character at a time.

### Three views

Switch with the **View** button, or in Settings → Display.

| View | What you get |
| --- | --- |
| **Board only** | The board, full width. The default. |
| **Board with radar** | Range rings and traffic on the left, board on the right. |
| **Board with map** | The upper Gulf coastline, the Chao Phraya and real runway layouts, drawn from vectors shipped inside the addon. No network, no map tiles. |

In both split views the surrounding traffic is drawn dim, and **the aircraft that
are on the board are drawn bright and labelled** — so the row that says `LANDING`
and the aeroplane on the screen are obviously the same thing. By default the
panel is **rotated to match your window**, so straight up on screen is straight
ahead through the glass, and dotted lines mark the edges of what you can see.

### Choosing what appears

Arrivals and departures are independent switches, and overflights are a third,
off by default — so you can have an arrivals-only board, a departures-only board,
or both, and optionally a third row for something merely passing over.

Only airline traffic reaches the board. Police helicopters, survey aircraft and
light singles pottering about near the runway look exactly like an arrival to the
geometry, so anything reporting a light, rotorcraft, glider or ground-vehicle
ADS-B category is kept off it. They still appear on the radar and map.

## Install

Kodi 19 (Matrix) or newer. Built and tested against the Python 3 addon API.

### From the repository — recommended, updates handled for you

Kodi cannot install from a GitHub URL directly. What it understands is a small
*repository addon*: install it once, and every later version turns up in Kodi's
normal add-on update flow.

1. **Settings → System → Add-ons → Unknown sources** → on.
2. **Settings → File manager → Add source**, and enter this as the path:

   ```
   https://raw.githubusercontent.com/schrutefarmbeets/kodi-flighttracker/main/repo/
   ```

   Give it a name like `flighttracker`.
3. **Settings → Add-ons → Install from zip file** → `flighttracker` →
   `repository.flighttracker` → `repository.flighttracker-1.0.0.zip`.
4. **Settings → Add-ons → Install from repository → Flight Tracker Repository →
   Program add-ons → Flight Tracker → Install.**

That is the last time you need to touch a zip. To publish an update: bump
`version` in `script.flighttracker/addon.xml`, then

```powershell
.\tools\make_repo.ps1 -GitHubUser schrutefarmbeets
```

and commit and push. The TV picks it up on its next check.

### From a zip — one-off, no auto-updates

The zip is `dist/script.flighttracker-1.0.0.zip`.

#### Android TV box / Shield / Fire TV

1. Get the zip onto the device. Easiest options:
   - **Send Files to TV** (app on both phone/PC and the TV box), or
   - a USB stick, or
   - the **Downloader** app if you host the zip somewhere on your LAN, or
   - a network share the box can already see.
2. In Kodi: **Settings → System → Add-ons → Unknown sources** → turn on.
   Kodi warns you here; that is expected for any addon not from the official repo.
3. **Settings → Add-ons → Install from zip file**, browse to the zip, select it.
4. It appears under **Add-ons → Program add-ons → Flight Tracker**.

To update later, install the new zip the same way over the top.

> If "Install from zip file" fails with a "not a valid addon structure" style
> error, the zip was probably rebuilt with a tool that stores Windows-style
> backslashes in the archive. `tools/build.ps1` writes forward slashes
> specifically to avoid that.

## First-run setup

Open the addon, press the **Settings** button at the bottom right, and fill in
the **Location** tab. Nothing else needs touching.

### Latitude and longitude

The single most important setting. Everything — distance, bearing, angle above
the horizon — is measured from here.

- On a computer, open Google Maps, right-click your building, and click the
  coordinates at the top of the menu to copy them. Paste in the two numbers.
- Or press **Detect position from internet connection**, which fills in an
  approximate position from your IP address. Expect to be a few kilometres off,
  so treat it as a starting point and correct it afterwards.

### Height above sea level

Your floor height plus local ground level, in metres. This is what makes the
"degrees above the horizon" figure meaningful.

A rough guide: about 3 m per residential floor. **Floor 33 in Bangkok is
roughly 100 m of building plus a couple of metres of ground, so ~110 m** — which
is the default.

### Compass bearing the window faces

Stand at the window and read a phone compass, then enter that number: 0 is north,
90 east, 180 south, 270 west. From central Bangkok, Suvarnabhumi sits at roughly
**110 degrees (east-southeast)**, which is the default.

This drives three things: which aircraft count as visible, which way the radar is
rotated, and the "12 degrees to your right" part of the detail line. Getting it
roughly right is worth more than getting anything else exactly right.

### Field of view

How wide a slice of sky the window actually gives you. 140 degrees suits a large
window; a balcony or corner unit sees more, a narrow window less. Set it to 360
to stop filtering by direction at all.

## Settings reference

| Tab | Setting | Notes |
| --- | --- | --- |
| Location | Latitude / Longitude | Decimal degrees. Required. |
| Location | Height above sea level | Metres. Drives the horizon angle. |
| Location | Compass bearing | Direction the window faces. |
| Location | Field of view | Width of sky visible, in degrees. |
| Location | Only show aircraft I can see | Hides everything outside the window view. |
| Location | Rotate radar to match the window | On by default. Off gives you north-up. |
| Data source | Source | adsb.lol, adsb.fi, or your own receiver. |
| Data source | Local receiver URL | e.g. `http://192.168.1.50:8080` for tar1090/dump1090. |
| Data source | Search radius | Up to 250 nm. 60 is a good default for one airport. |
| Data source | Refresh interval | Seconds between polls. 8 is smooth without being rude. |
| Data source | Primary airport | ICAO code. `VTBS` is Suvarnabhumi. This is the airport the board is for. |
| Data source | Secondary airport | Empty by default. Only add one if you can genuinely see it too — see below. |
| Data source | Look up origin and destination | The route lookups. Cached on disk. |
| Filters | Min / Max altitude | Hide ground clutter, or hide high overflights. |
| Filters | Show arrivals / departures / overflights | Independent switches. Overflights off by default. |
| Display | View | Board only, board with radar, or board with map. |
| Display | Show airline logos | Fetched once per airline and cached on disk forever. |
| Display | Split-flap animation | Letters flip over when a row changes. Turn off for a plain switch. |
| Display | Label the board aircraft on the radar | Only the board's aircraft are ever labelled. |
| Display | Units | Aviation (nm/ft/kt) or metric (km/m/km-h). |
| Alerts | Notify when an aircraft passes close | Off by default. See below. |

## Background alerts

Off by default. When switched on, a small Kodi notification pops up with the
route whenever a low aircraft passes close — so when something rattles the
windows you can find out what it was without leaving what you were watching.

It only runs while the Flight Tracker window is closed, so it never doubles up on
the polling, and it respects a cooldown so the same aircraft cannot nag you.

## Where the data comes from

Everything used here is free, public, and needs no account or API key.

| Source | Used for | Notes |
| --- | --- | --- |
| [adsb.lol](https://adsb.lol) | Aircraft positions | Community ADS-B aggregator. Default. |
| [adsb.fi](https://adsb.fi) | Aircraft positions | Alternative aggregator. |
| [adsbdb.com](https://www.adsbdb.com) | Airline, route, airframe | Community route database. |
| [pics.avs.io](https://pics.avs.io) / [daisycon](https://daisycon.io) | Airline logos | Tried in that order. Cached on disk. |
| Local dump1090 / tar1090 | Aircraft positions | If you run your own receiver. |

Logos are worth a note: neither logo service returns a 404 for an airline it does
not have. daisycon answers with a placeholder graphic, and avs.io will hand back
a confidently wrong logo — asking it for the nonsense code `ZZ` returns American
Eagle. So a fetched image is rejected if it matches a known placeholder, or if it
is byte-identical to an image already served for a *different* airline, which is
what a placeholder always is. When nothing trustworthy comes back the board falls
back to a plain text badge with the airline code, which suits it fine.

The addon is deliberately gentle with the free services:

- Route lookups are **capped at 10 HTTP requests per refresh**, hard.
- Where possible one request fetches the route *and* the airframe together,
  using adsbdb's combined endpoint.
- Every answer is **cached on disk** — routes for 30 days, misses for 3 — so a
  given flight number is only ever looked up once. Airport coordinates learned
  from those lookups are cached too, and the seed airport table fills itself in
  as you watch.
- Nearest aircraft are resolved first, so the interesting ones fill in immediately
  and the rest catch up over the following refreshes.

In practice the first minute of watching is the only time it does real work.
After that an evening at the window is almost entirely cache hits.

## Things worth knowing

- **Some routes will say "Route unknown."** adsbdb is a community database with
  excellent coverage of scheduled airline flights and patchy coverage of cargo,
  charter, business and general aviation. Those aircraft still show up with
  position, altitude, type and registration; they just have no route.
- **Public feeds are volunteer coverage, not your own antenna.** Bangkok is well
  covered, but very low aircraft on short final can drop out briefly. If that
  bothers you, a receiver of your own plugged into the "Local receiver" option
  fixes it completely.
- **Arrival/departure is inferred.** It uses the route's origin and destination
  against your two reference airports where the route is known, and falls back to
  "close to the airport and climbing or descending" where it is not.
- **The horizon angle accounts for the curvature of the earth**, using the usual
  4/3-radius refraction correction. This is not pedantry: at 60 nm the drop is
  about 700 m, which is the difference between an aircraft being low in your
  window and being behind the horizon entirely.

## Development

```bash
python tools/selftest.py
```

Exercises geometry, parsing, the airport book, the route cache and a live poll,
then prints the flight table as the addon would build it. 63 checks.

```bash
python tools/uitest.py
```

Runs the Kodi-facing code against stub bindings in `tools/kodistubs/`. Catches
missing textures, text too long for the box it was measured for, aircraft
plotted off the panel, board slots captured by helicopters, and any drift
between `settings.xml`, `config.py` and `strings.po`. 73 checks.

```bash
python tools/preview.py
```

Renders the window to `dist/preview-*.svg` without Kodi. It is not a mockup: it
parses the real skin XML for the fixed furniture and runs the real `gui.py`
against the stubs, so every board row, radar blip and map line is placed by the
code that ships. Layout bugs show up here rather than on the telly. Add
`--view board|radar|map` for a single view.

All three take `--offline` to skip the parts that need network.

```powershell
.\tools\gen_assets.ps1   # redraw sprites, flap panel, logo card, icon, fanart
.\tools\build.ps1        # validate XML + Python + media, then package dist/*.zip
```

`build.ps1` refuses to produce a zip that is missing expected files or that has
picked up `__pycache__` or test leftovers.

### Layout

```
script.flighttracker/
  addon.xml               addon manifest
  default.py              entry point: opens the window, or the location helper
  service.py              optional background alert watcher
  resources/
    settings.xml          settings definitions
    language/             en_gb strings
    media/                flap panel, logo card, 24 rotated sprites, radar, icon
    skins/Default/1080i/  background, header and buttons; rows are built in code
    lib/
      config.py           settings snapshot, no Kodi imports
      geo.py              distance, bearing, horizon angle, panel projection
      feeds.py            adsb.lol / adsb.fi / local receiver
      routes.py           adsbdb lookups + on-disk cache
      airports.py         seed airport table + learned entries
      logos.py            airline logos + placeholder rejection
      mapdata.py          coastline and runway vectors
      model.py            the Flight object, board wording, unit formatting
      tracker.py          poll, filter, enrich, and pick what is happening now
      gui.py              the board, radar and map
tools/
  selftest.py  uitest.py  preview.py  kodistubs/  gen_assets.ps1  build.ps1
```

Everything below `gui.py` is free of Kodi imports on purpose, which is what lets
the test scripts run the real code outside Kodi.

## Licence

MIT. See `script.flighttracker/LICENSE.txt`.

Aircraft data is supplied by volunteers who run receivers and maintain the route
database. If you find this useful, consider feeding data to adsb.lol or adsb.fi,
or contributing corrections to adsbdb.
