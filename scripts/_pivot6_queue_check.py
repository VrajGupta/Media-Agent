"""One-shot: show upload queue and cancel non-uploaded queued clips."""
import sqlite3, sys

conn = sqlite3.connect("data/state.db")
conn.row_factory = sqlite3.Row

statuses = ("quality_pass", "approved", "uploaded")
rows = conn.execute(
    "SELECT clip_id, status, publish_at_utc, youtube_video_id, hook "
    "FROM clips WHERE status IN (?, ?, ?) ORDER BY publish_at_utc",
    statuses,
).fetchall()

print(f"{'clip_id':<40} {'status':<14} {'publish_at_utc':<22} {'yt_id':<15} hook")
print("-" * 120)
for r in rows:
    print(f"{r['clip_id']:<40} {r['status']:<14} {str(r['publish_at_utc']):<22} {str(r['youtube_video_id']):<15} {str(r['hook'])[:50]}")

if "--cancel-queued" in sys.argv:
    # Cancel clips that are quality_pass/approved (not yet uploaded = no youtube_video_id)
    to_cancel = [r["clip_id"] for r in rows if r["youtube_video_id"] is None]
    if to_cancel:
        for cid in to_cancel:
            conn.execute(
                "UPDATE clips SET status='cancelled', publish_at_utc=NULL WHERE clip_id=?",
                (cid,),
            )
        conn.commit()
        print(f"\nCancelled {len(to_cancel)} queued clip(s): {to_cancel}")
    else:
        print("\nNo unuploaded queued clips to cancel.")
else:
    unuploaded = [r["clip_id"] for r in rows if r["youtube_video_id"] is None]
    if unuploaded:
        print(f"\n{len(unuploaded)} unuploaded queued clip(s) found. Re-run with --cancel-queued to cancel.")

conn.close()
