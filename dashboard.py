#!/usr/bin/env python3
"""Build dashboard.html from the snapshots in ytstats.db.

The page is static: the data is embedded as JSON in dashboard_template.html,
so it opens straight from disk with no server. Run on its own, or it is
called by fetch.py after every fetch.
"""
import json
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "ytstats.db"
TEMPLATE_PATH = ROOT / "dashboard_template.html"
OUT_PATH = ROOT / "dashboard.html"
PLACEHOLDER = "/*__DATA__*/null"


def load_data(db):
    # Show channels in config.json order; a channel removed from the config
    # keeps its history in the database but drops off the page.
    configured = json.loads((ROOT / "config.json").read_text())["channels"]
    channels = []
    for entry in configured:
        handle = entry["handle"]
        row = db.execute(
            "SELECT channel_id, title FROM channels WHERE handle = ?", (handle,)
        ).fetchone()
        if row is None:
            continue  # not fetched yet
        snapshots = db.execute(
            """SELECT snapshot_date, subscribers, views, videos
               FROM channel_snapshots WHERE channel_id = ?
               ORDER BY snapshot_date""",
            (row[0],),
        ).fetchall()
        channels.append({
            "handle": handle,
            "format": entry.get("format", ""),
            "title": row[1],
            "snapshots": [
                {"date": d, "subscribers": s, "views": v, "videos": n}
                for d, s, v, n in snapshots
            ],
            "videos": load_videos(db, row[0]),
        })
    return {
        "generatedAt": datetime.now().astimezone().isoformat(timespec="minutes"),
        # The latest fetch date; a video last seen before this is no longer public.
        "latestDate": db.execute("SELECT MAX(snapshot_date) FROM channel_snapshots").fetchone()[0],
        "channels": channels,
    }


def load_videos(db, channel_id):
    videos = db.execute(
        """SELECT video_id, title, published_at, duration_seconds, last_seen_date
           FROM videos WHERE channel_id = ? ORDER BY published_at DESC""",
        (channel_id,),
    ).fetchall()
    result = []
    for video_id, title, published_at, duration, last_seen in videos:
        snaps = db.execute(
            """SELECT snapshot_date, views, likes, comments FROM video_snapshots
               WHERE video_id = ? ORDER BY snapshot_date""",
            (video_id,),
        ).fetchall()
        result.append({
            "id": video_id,
            "title": title,
            "publishedAt": published_at,
            "duration": duration,
            "lastSeen": last_seen,
            "snapshots": [
                {"date": d, "views": v, "likes": l, "comments": c} for d, v, l, c in snaps
            ],
        })
    return result


def build():
    db = sqlite3.connect(DB_PATH)
    try:
        data = load_data(db)
    finally:
        db.close()
    # Escape "</" so a channel title can never close the <script> tag early.
    data_json = json.dumps(data).replace("</", "<\\/")
    template = TEMPLATE_PATH.read_text()
    if PLACEHOLDER not in template:
        raise SystemExit(f"{TEMPLATE_PATH.name} is missing the {PLACEHOLDER} placeholder")
    # Write to a temp file and rename, so a browser refresh never sees half a page.
    tmp_path = OUT_PATH.with_suffix(".tmp")
    tmp_path.write_text(template.replace(PLACEHOLDER, data_json))
    tmp_path.replace(OUT_PATH)
    return OUT_PATH


if __name__ == "__main__":
    print(f"Wrote {build()}")
