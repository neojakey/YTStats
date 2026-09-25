# YTStats

Local dashboard tracking public stats for two YouTube channels:
`@AfterTheScreenYT` and `@themexicanplate` (listed in `config.json`).

## Stack
- Python 3 standard library only (no pip packages). Tested on Python 3.14, Fedora.
- SQLite (`ytstats.db`) for storage.
- YouTube Data API v3, public data only, via an API key. No OAuth.
- Static `dashboard.html`: data embedded as JSON, charts drawn as inline SVG, no CDN or server.

## Files
- `fetch.py`: takes one snapshot per channel per local date, then rebuilds the dashboard.
- `dashboard.py`: reads the DB and writes `dashboard.html` from `dashboard_template.html`
  (replaces the `/*__DATA__*/null` placeholder).
- `config.json`: channel handles plus a `format` label (Long-form / Shorts, set by the owner,
  not detected); order sets card and colour order.
- DB tables: `channels`, `channel_snapshots`, `videos`, `video_snapshots`. Videos come from each
  channel's uploads playlist (public only); `videos.last_seen_date` older than today means no longer public.
- `.env`: `YOUTUBE_API_KEY=...` (chmod 600, gitignored). Never print or commit it.

## Scheduling
- systemd user units: `~/.config/systemd/user/ytstats.{service,timer}`, every 15 min (`OnCalendar=*:0/15`).
- Each run overwrites today's row, so the stored daily value is the last run before midnight.
- Logs: `journalctl --user -u ytstats.service`. Status: `systemctl --user list-timers ytstats.timer`.
- Linger is off (as of 2026-09-25), so the timer only runs while the owner is logged in.

## Behaviour to preserve
- Snapshots are keyed by (channel_id, snapshot_date); re-running a day upserts, never duplicates.
- Handles resolve to channel IDs once and are cached in `channels`; later fetches use IDs.
- Hidden subscriber counts are stored as NULL, not 0.
- API errors print Google's message, never the request URL (it contains the key).
- `fetch.py` exits non-zero if any configured channel wasn't saved.
- Missing days are gaps in the charts (lines break), not zeros.
- The page reloads itself at :03/:18/:33/:48 (just after each fetch); a hidden tab waits until shown.
  Range, per-channel sort and open video charts are kept across reloads in sessionStorage.
- Video "Last 7 days" = latest views minus the last snapshot on/before 7 days ago. A video published
  inside the window counts all its views ("new"); an older video with under a week of history shows "—".
- Channel titles from the API go into the DOM via `textContent` only; `</` is escaped in the embedded JSON.

## Known limits
- Subscriber counts from the API are rounded to 3 significant figures above 1,000.
- History starts from the first fetch (2026-09-25); the API has no past daily snapshots.
- API key is restricted to YouTube Data API v3 only, application restriction None
  (Google Cloud project `ytstats-509722`).
- Headless Chrome won't render narrower than 500px; screenshots taken at smaller window sizes are cropped, not the real layout.

## Rules
- No tests are written unless the owner asks (see global CLAUDE.md).
