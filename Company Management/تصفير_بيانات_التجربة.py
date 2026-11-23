"""يحذف بيانات التجربة كلها (شركات، موظفين، متعهدين، مناديب، حركات، سندات، عقود، وثائق...)
ويُبقي المستخدمين وكلمات المرور والإعدادات. يعمل نسخة احتياطية من قاعدة البيانات أولاً.

التشغيل (من مجلد المشروع، بعد إغلاق البرنامج):
    py -3 تصفير_بيانات_التجربة.py
"""
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
KEEP = {"users", "app_settings"}


def find_db():
    for p in (BASE / "database" / "app.db", BASE / "app.db"):
        if p.exists():
            return p
    return None


def main():
    db = find_db()
    if not db:
        print("لا توجد قاعدة بيانات بعد (لا شيء لتصفيره).")
        return 0
    print("قاعدة البيانات:", db)
    print("سيتم حذف كل بيانات التجربة، ويبقى المستخدمون والإعدادات.")
    if "--yes" not in sys.argv:
        if input("للمتابعة اكتب YES ثم Enter: ").strip().upper() != "YES":
            print("أُلغي التصفير. لم يتغير شيء.")
            return 1
    bak = db.with_name(f"{db.stem}_قبل_التصفير_{datetime.now():%Y%m%d_%H%M%S}.db")
    shutil.copy2(db, bak)
    print("نسخة احتياطية:", bak)

    conn = sqlite3.connect(str(db))
    try:
        conn.execute("PRAGMA foreign_keys = OFF;")
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        targets = [t for t in tables if t not in KEEP]
        # protective triggers (immutability) would block the delete: drop them, the app re-creates them at start
        for t in targets:
            for (trg,) in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (t,)).fetchall():
                conn.execute(f'DROP TRIGGER IF EXISTS "{trg}"')
        for t in targets:
            conn.execute(f'DELETE FROM "{t}"')
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='sqlite_sequence'").fetchone():
            for t in targets:
                conn.execute("DELETE FROM sqlite_sequence WHERE name=?", (t,))
        conn.commit()
        conn.execute("VACUUM")
    finally:
        conn.close()
    print(f"تم حذف بيانات {len(targets)} جدولاً. شغّل البرنامج الآن، وستُعاد حمايات الجداول تلقائياً.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
