# Trek Domane AL 3 watcher

Every morning this checks **Gumtree AU** and **eBay AU** (plus **bikesales.com.au**, off by default, see below) for a
second-hand Trek Domane AL 3 (disc, 58 cm) near Richmond VIC 3121, and pushes **new**
matches to your phone with [ntfy](https://ntfy.sh).

Facebook Marketplace is deliberately **not** scraped (it's against Meta's terms and
could get your account flagged). Use Marketplace's own saved-search alerts for that.

Each alert looks like this:

```
🚲 Trek Domane AL 3 Disc 2022 - $1,150
$1,150 · Richmond VIC (~0 km)
[58 CM] [DISC] [GEN 3+]
via Gumtree
https://www.gumtree.com.au/s-ad/...
```

Tapping the notification opens the listing. Labels:

| Label | Meaning |
|---|---|
| `58 CM` | the ad says 58 / 58cm / XL |
| `SIZE UNKNOWN` | no size given. Kept, because sellers often leave it out |
| `DISC` | mentions disc / thru axle / Gen 3 / a model year of 2020 or later |
| `CHECK BRAKES` | brakes unclear. Kept so you can check |
| `GEN 3+` | Gen 3 or later, or a 2022+ model (the ideal one) |
| `CHECK LOCATION` | the site didn't say where the bike is |

Dropped automatically: Domane SL/SLR, AL 2/4/5, rim-brake bikes, frames/parts only,
wanted ads, ads that state a different size, and anything outside 10 km.

## 1. One-time setup

You need Python 3.9 or newer.

**Mac** (keep the folder in your home folder, e.g. `~/bike-watcher`, not in
Downloads/Desktop/Documents: macOS won't let scheduled jobs read those):

```bash
cd ~/bike-watcher
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
```

Then use `.venv/bin/python` wherever this README says `python3`.

**Windows / Linux:** the same, with `py -m venv .venv` and `.venv\Scripts\python` on Windows.

**Phone:** install the **ntfy** app (iOS/Android, free, no account). Tap **+** and
subscribe to a topic name of your choice. Anyone who knows the name can read the
alerts, so make it hard to guess, e.g. `domane-richmond-8f3k2q`. Put the same name in
`config.yaml`:

```yaml
notify:
  ntfy:
    topic: "domane-richmond-8f3k2q"
```

Check it works:

```bash
python3 watcher.py --test-notify
```

## 2. Run it manually

```bash
python3 watcher.py --dry-run     # searches every source and prints what it found; sends nothing, remembers nothing
python3 watcher.py               # real run: alerts about new matches and records them in seen.json
python3 watcher.py --source gumtree --dry-run   # check one source only (gumtree, bikesales or ebay)
python3 watcher.py -v            # more detail
```

The output shows, for each source, how many listings were on the results page, how many
were new, and every match or skip with its reason. Everything also goes into `watcher.log`.

`seen.json` remembers every listing already alerted or rejected, so you only ever hear
about a listing once. Delete `seen.json` to start fresh. (The first real run may alert
you about matching listings that are already up.)

## 3. Daily schedule (7:00 am Melbourne time)

```bash
python3 watcher.py --install-schedule
```

This detects your OS and sets up:

* **macOS**: a launchd agent (`~/Library/LaunchAgents/com.user.trek-domane-watcher.plist`)
* **Windows**: a Task Scheduler task called `TrekDomaneWatcher`
* **Linux**: a crontab entry (tagged `# trek-domane-watcher`)

The scheduler wakes the script every hour, on the hour. The script only does a real
search **once per day**, the first time it's woken at or after 7:00 am Melbourne time
(it uses the Australia/Melbourne timezone whatever your computer is set to, daylight
saving included). Every other wake-up exits straight away without going online.

> **Your computer must be on and awake for this to run.** A sleeping or switched-off
> computer can't check anything. Because of the hourly design, a missed 7:00 run is
> caught up automatically at the first full hour the computer is awake (e.g. you open
> the laptop at 8:40 → it runs at 9:00). If you want it to run at 7:00 even when
> the computer is asleep:
>
> * **macOS:** `sudo pmset repeat wakeorpoweron MTWRFSU 06:55:00` (undo with `sudo pmset repeat cancel`)
> * **Windows:** Task Scheduler → `TrekDomaneWatcher` → Properties → Conditions → tick
>   *Wake the computer to run this task*
> * **Linux:** use `rtcwake`, or leave the machine on.

## 4. Turn it off

```bash
python3 watcher.py --uninstall-schedule
```

To pause a single source instead, set `enabled: false` for it in `config.yaml`.

## 5. Change the search

Everything is in `config.yaml`:

* `search`: keywords, suburb/postcode and `radius_km`
* `match`: model terms, size terms (`size_terms`), disc terms and the exclusion list.
  Terms are whole words and case-insensitive, and `-` counts as a space.
* `sources`: turn each site on or off, or change its search URL
* `notify`: ntfy topic, the optional daily "nothing new" line (`quiet_nothing_new`),
  failure alerts, email fallback
* `politeness`: delays between pages and how many new ads are opened per run

**Changing the Gumtree or bikesales search:** do the search on the website in a normal
browser (keywords, location, radius, newest first), copy the address bar, and paste it
into that source's `search_url`. For Gumtree the default already is Gumtree's own search:
Bicycles, Richmond VIC 3121, 10 km radius, newest first. For bikesales the default leaves
`search_url` empty and types the keywords into the site's search box, then filters by
the suburb/postcode on each listing. If you can set a location filter on the site,
pasting that URL is better.

**Distance filter:** for bikesales and eBay listings, the suburb is looked up in a
table of suburbs within ~12 km of Richmond (in `watcher.py`, `SUBURBS`). Add any missing
suburb under `extra_suburbs` in `config.yaml`.

## 6. Notifications

* **ntfy** is the default (see setup).
* **Email fallback:** set `notify.email.enabled: true` and fill in the SMTP details.
  `mode: fallback` emails only when ntfy can't be reached; `mode: always` sends both. Put
  the password in the environment variable `WATCHER_SMTP_PASSWORD` rather than in the file.
  For Gmail, create an *App password* (Google account → Security → App passwords) and
  use that, not your normal password.
* **When something breaks:** if a source fails (blocked, site down, page layout changed),
  you get a short alert naming the source and the reason, so the watcher never fails
  silently. If you get that alert every day for one source, its page layout probably
  changed: run `python3 watcher.py --source <name> --dry-run -v` and check the message.

## 7. eBay: official API (optional)

By default eBay is read from the normal search page (newest first, within 10 km of 3121).
The official Browse API is more reliable. To use it, create a free account at
[developer.ebay.com](https://developer.ebay.com), create a **Production** keyset, and
put the App ID (Client ID) and Cert ID (Client Secret) into `sources.ebay.api_client_id` /
`api_client_secret`, or into the env vars `EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET`. It then
looks for items with pickup within 10 km of 3121, plus items located in Melbourne.

## 8. Being polite

One real run a day, a normal desktop browser user agent, 2.5–5 s pauses between page
loads, and at most 20 newly listed ads opened per site per run (any extras wait until
the next day). Ads already in `seen.json` are never opened again.

## Troubleshooting

* `Playwright's Chromium is not installed`: run `python3 -m playwright install chromium`.
* **bikesales is off by default.** In a live test (Oct 2026) bikesales.com.au only listed
  motorbikes (no bicycle category) and showed a "press & hold" human check on search
  pages. Turn it on only if that changes.
* **A source says "blocked by the site's bot protection":** these sites block cloud/data-centre
  computers. From a normal home internet connection they usually work. bikesales in particular
  protects itself aggressively. Try `browser: headless: false` in `config.yaml` (a visible
  browser window opens briefly during the run), or turn that source off.
* **No alerts at all:** run `python3 watcher.py --test-notify`, and check the topic in
  the app matches `config.yaml` exactly.
* Logs are in `watcher.log` (plus `launchd.*.log` on macOS).

## Files

| File | What it is |
|---|---|
| `watcher.py` | the watcher |
| `config.yaml` | all settings |
| `seen.json` | listings already handled (created on first run) |
| `watcher.log` | run log |
| `test_watcher.py` | offline tests for the matching rules (`python3 -m pytest -q`) |
