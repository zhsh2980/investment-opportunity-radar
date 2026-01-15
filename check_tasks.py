from src.app.database import SessionLocal
from src.app.domain.models import SlotRun
from datetime import datetime

db = SessionLocal()
try:
    running = db.query(SlotRun).filter(SlotRun.status == 0).all()
    print(f"Found {len(running)} running tasks:")
    for r in running:
        print(f"ID: {r.id}, Date: {r.run_date}, Slot: {r.slot}, Started: {r.started_at}, Stats: {r.stats}")
        # Check if it's stale (e.g. > 1 hour)
        if (datetime.utcnow() - r.started_at).total_seconds() > 3600:
            print("  [WARNING] This task seems stale (> 1 hour).")
finally:
    db.close()
