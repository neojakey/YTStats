# YTStats

A small local dashboard that tracks public stats for my YouTube channels, so I don't have
to keep opening YouTube Studio to check them.

Every 15 minutes it fetches subscriber, view and video counts for each channel, plus views,
likes and comments for every public video, and saves one snapshot per day to a local SQLite
database. It then rebuilds a single HTML page with:

- a card per channel with today's numbers and the change since yesterday and last week
- subscriber and view charts over time, with a 7 / 30 / 90 day / all-time range
- a sortable video table per channel, including views gained in the last 7 days
- a views-over-time chart for any video (click its title)

The page reloads itself every 15 minutes and follows your system's light or dark mode.

No packages to install: it's plain Python (standard library only), SQLite, and one HTML file.

## Setup

1. **Get a YouTube Data API key.** In the [Google Cloud console](https://console.cloud.google.com/):
   create a project, enable **YouTube Data API v3**, then go to *APIs & Services → Credentials →
   Create credentials → API key*. Under API restrictions, allow only YouTube Data API v3.
   No billing or OAuth is needed; the key only reads public data.

2. **Add the key** to a `.env` file in the project folder (it's gitignored):

   ```
   YOUTUBE_API_KEY=your-key-here
   ```

   ```bash
   chmod 600 .env
   ```

3. **List your channels** in `config.json`. `format` is just a label shown on the dashboard:

   ```json
   {
     "channels": [
       {"handle": "@AfterTheScreenYT", "format": "Long-form"},
       {"handle": "@themexicanplate", "format": "Shorts"}
     ]
   }
   ```

4. **Run it once:**

   ```bash
   python3 fetch.py
   ```

   Then open `dashboard.html` in your browser.

## Run it automatically (systemd)

Create `~/.config/systemd/user/ytstats.service` (adjust the paths):

```ini
[Unit]
Description=YTStats: snapshot YouTube channel and video stats
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/path/to/YTStats
ExecStart=/usr/bin/python3 /path/to/YTStats/fetch.py
```

and `~/.config/systemd/user/ytstats.timer`:

```ini
[Unit]
Description=YTStats: run the fetch every 15 minutes

[Timer]
OnCalendar=*:0/15
Persistent=true
RandomizedDelaySec=60

[Install]
WantedBy=timers.target
```

Then:

```bash
systemctl --user daemon-reload
systemctl --user enable --now ytstats.timer
```

Useful commands:

```bash
systemctl --user list-timers ytstats.timer      # last and next run
journalctl --user -u ytstats.service -n 20      # output of recent runs
systemctl --user disable --now ytstats.timer    # stop it
```

A user timer only runs while you're logged in. To keep it running while logged out, run
`loginctl enable-linger`.

## Files

| File | What it does |
|---|---|
| `fetch.py` | Fetches stats from the API, saves today's snapshot, rebuilds the dashboard |
| `dashboard.py` | Builds `dashboard.html` from the database (can be run on its own) |
| `dashboard_template.html` | The page design: layout, charts and tables |
| `config.json` | The channels to track |
| `.env` | Your API key (not committed) |
| `ytstats.db` | Your stats history (not committed; back it up if you care about it) |
| `dashboard.html` | The generated page (not committed) |

## Things to know

- **History starts from your first run.** The API has no past daily numbers.
- **One snapshot per day.** Each run overwrites today's row, so a day's stored value is the
  last fetch before midnight. Missing days (PC off) show as gaps in the charts, not zeros.
- **Subscriber counts are rounded** by YouTube to 3 significant figures once a channel has
  over 1,000 subscribers.
- **Only public data.** Watch time, impressions, CTR, retention and revenue need the YouTube
  Analytics API and signing in to each channel, which this doesn't do.
- **Only public videos are visible.** A video made private stays in the table, greyed out and
  marked "No longer public".
- **Per-video totals won't exactly match the channel total.** YouTube updates them at
  different times.
- **Quota:** each run uses about 5 of the 10,000 free daily API units.
