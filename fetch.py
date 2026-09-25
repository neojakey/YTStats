#!/usr/bin/env python3
"""Take one daily snapshot of public stats for each channel in config.json,
and for every public video on those channels.

Snapshots are keyed by (channel or video, local date): re-running on the same
day overwrites that day's row instead of adding a duplicate.
"""
import json
import re
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

import dashboard

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "ytstats.db"
API_BASE = "https://www.googleapis.com/youtube/v3"

SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    channel_id TEXT PRIMARY KEY,
    handle     TEXT NOT NULL UNIQUE,
    title      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS channel_snapshots (
    channel_id    TEXT NOT NULL REFERENCES channels(channel_id),
    snapshot_date TEXT NOT NULL,  -- local date, YYYY-MM-DD
    subscribers   INTEGER,        -- NULL when the channel hides its count
    views         INTEGER NOT NULL,
    videos        INTEGER NOT NULL,
    fetched_at    TEXT NOT NULL,  -- UTC ISO timestamp
    PRIMARY KEY (channel_id, snapshot_date)
);
CREATE TABLE IF NOT EXISTS videos (
    video_id         TEXT PRIMARY KEY,
    channel_id       TEXT NOT NULL REFERENCES channels(channel_id),
    title            TEXT NOT NULL,  -- refreshed daily, so renames show up
    published_at     TEXT NOT NULL,  -- UTC ISO timestamp from YouTube
    duration_seconds INTEGER,
    last_seen_date   TEXT NOT NULL   -- older than today = no longer public
);
CREATE TABLE IF NOT EXISTS video_snapshots (
    video_id      TEXT NOT NULL REFERENCES videos(video_id),
    snapshot_date TEXT NOT NULL,  -- local date, YYYY-MM-DD
    views         INTEGER NOT NULL,
    likes         INTEGER,        -- NULL when likes are hidden
    comments      INTEGER,        -- NULL when comments are off
    PRIMARY KEY (video_id, snapshot_date)
);
"""


class ApiError(Exception):
    pass


def load_api_key():
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() == "YOUTUBE_API_KEY" and value.strip():
                return value.strip()
    sys.exit("No API key found. Put YOUTUBE_API_KEY=... in .env")


def call_api(api_key, endpoint, **params):
    """Return the whole JSON response. Each call costs 1 quota unit."""
    query = urllib.parse.urlencode({"key": api_key, **params})
    try:
        with urllib.request.urlopen(f"{API_BASE}/{endpoint}?{query}", timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        # Report Google's error message, never the URL (it contains the key).
        try:
            message = json.load(e)["error"]["message"]
        except Exception:
            message = e.reason
        raise ApiError(f"YouTube API error {e.code} on {endpoint}: {message}") from None
    except urllib.error.URLError as e:
        raise ApiError(f"Network error on {endpoint}: {e.reason}") from None


def optional_int(stats, key):
    return int(stats[key]) if key in stats else None


def parse_duration(iso):
    """'PT1H2M3S' -> 3723. Returns None for anything unexpected."""
    m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", iso or "")
    if not m:
        return None
    d, h, mi, s = (int(g or 0) for g in m.groups())
    return ((d * 24 + h) * 60 + mi) * 60 + s


def resolve_channel_ids(db, api_key, handles):
    """Map each handle to a channel ID, looking up only unknown ones."""
    known = dict(db.execute("SELECT handle, channel_id FROM channels"))
    ids = {}
    for handle in handles:
        if handle in known:
            ids[handle] = known[handle]
            continue
        items = call_api(api_key, "channels", part="snippet", forHandle=handle).get("items", [])
        if not items:
            print(f"WARNING: no channel found for {handle}", file=sys.stderr)
            continue
        ids[handle] = items[0]["id"]
        db.execute(
            "INSERT INTO channels (channel_id, handle, title) VALUES (?, ?, ?)",
            (items[0]["id"], handle, items[0]["snippet"]["title"]),
        )
    return ids


def list_upload_ids(api_key, playlist_id):
    """All video IDs in a channel's uploads playlist (public videos only)."""
    ids, page_token = [], None
    while True:
        params = {"part": "contentDetails", "playlistId": playlist_id, "maxResults": 50}
        if page_token:
            params["pageToken"] = page_token
        resp = call_api(api_key, "playlistItems", **params)
        ids += [item["contentDetails"]["videoId"] for item in resp.get("items", [])]
        page_token = resp.get("nextPageToken")
        if not page_token:
            return ids


def save_videos(db, api_key, channel_id, playlist_id, today):
    """Snapshot every public video on one channel. Returns how many were saved."""
    video_ids = list_upload_ids(api_key, playlist_id)
    saved = 0
    for start in range(0, len(video_ids), 50):
        batch = video_ids[start:start + 50]
        resp = call_api(api_key, "videos", part="snippet,statistics,contentDetails", id=",".join(batch))
        for item in resp.get("items", []):
            snippet, stats = item["snippet"], item.get("statistics", {})
            if snippet.get("liveBroadcastContent") == "upcoming":
                continue  # scheduled premiere: 0 views until it airs
            db.execute(
                """INSERT INTO videos
                       (video_id, channel_id, title, published_at, duration_seconds, last_seen_date)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT (video_id) DO UPDATE SET
                       title = excluded.title, published_at = excluded.published_at,
                       duration_seconds = excluded.duration_seconds,
                       last_seen_date = excluded.last_seen_date""",
                (item["id"], channel_id, snippet["title"], snippet["publishedAt"],
                 parse_duration(item.get("contentDetails", {}).get("duration")), today),
            )
            db.execute(
                """INSERT INTO video_snapshots (video_id, snapshot_date, views, likes, comments)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT (video_id, snapshot_date) DO UPDATE SET
                       views = excluded.views, likes = excluded.likes, comments = excluded.comments""",
                (item["id"], today, int(stats.get("viewCount", 0)),
                 optional_int(stats, "likeCount"), optional_int(stats, "commentCount")),
            )
            saved += 1
    return saved


def main():
    handles = [c["handle"] for c in json.loads((ROOT / "config.json").read_text())["channels"]]
    api_key = load_api_key()
    db = sqlite3.connect(DB_PATH)
    db.executescript(SCHEMA)
    today = date.today().isoformat()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    problems = []

    try:
        ids = resolve_channel_ids(db, api_key, handles)
        items = call_api(api_key, "channels", part="snippet,statistics,contentDetails",
                         id=",".join(ids.values())).get("items", []) if ids else []
    except ApiError as e:
        sys.exit(str(e))

    for item in items:
        stats = item["statistics"]
        subs = None if stats.get("hiddenSubscriberCount") else int(stats["subscriberCount"])
        db.execute(
            "UPDATE channels SET title = ? WHERE channel_id = ?",
            (item["snippet"]["title"], item["id"]),
        )
        db.execute(
            """INSERT INTO channel_snapshots
                   (channel_id, snapshot_date, subscribers, views, videos, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT (channel_id, snapshot_date) DO UPDATE SET
                   subscribers = excluded.subscribers, views = excluded.views,
                   videos = excluded.videos, fetched_at = excluded.fetched_at""",
            (item["id"], today, subs, int(stats["viewCount"]), int(stats["videoCount"]), now),
        )
        subs_text = "hidden" if subs is None else f"{subs:,}"
        print(f"{item['snippet']['title']}: {subs_text} subs, "
              f"{int(stats['viewCount']):,} views, {int(stats['videoCount'])} videos")
    # Commit channel stats first, so a video-fetch failure can't lose them.
    db.commit()
    if len(items) < len(handles):
        problems.append(f"only {len(items)} of {len(handles)} channels were saved")

    for item in items:
        title = item["snippet"]["title"]
        try:
            playlist_id = item["contentDetails"]["relatedPlaylists"]["uploads"]
            saved = save_videos(db, api_key, item["id"], playlist_id, today)
            db.commit()
            print(f"  {title}: saved stats for {saved} videos")
        except (ApiError, KeyError) as e:
            db.rollback()
            problems.append(f"video stats for {title} failed: {e}")

    db.close()
    print(f"Dashboard: {dashboard.build()}")

    # Non-zero exit makes a failed daily run visible in systemd.
    if problems:
        sys.exit("Problems: " + "; ".join(problems))


if __name__ == "__main__":
    main()
