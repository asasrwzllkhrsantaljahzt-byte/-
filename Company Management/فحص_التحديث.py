# تشغيل:  py -3 فحص_التحديث.py     (من داخل مجلد المشروع)
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import integrity

r = integrity.check()
if r.get("no_manifest"):
    print("لا يوجد ملف release_manifest.json — انسخه من حزمة التحديث الأخيرة.")
    sys.exit(1)
print(f"رقم الإصدار المطلوب: {r['build']}")
if r["ok"]:
    print("✅ كل الملفات محدّثة.")
else:
    if r["missing"]:
        print("\n❌ ملفات ناقصة (لم تُنسخ):")
        for f in r["missing"]:
            print("   -", f)
    if r["different"]:
        print("\n⚠️ ملفات مختلفة عن الإصدار (قديمة أو معدّلة):")
        for f in r["different"]:
            print("   -", f)
    print("\nانسخ هذه الملفات من آخر حزمة تحديث فوق مجلد المشروع ثم أعد التشغيل.")
