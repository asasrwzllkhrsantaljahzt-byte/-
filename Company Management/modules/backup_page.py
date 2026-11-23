import streamlit as st
import pandas as pd
import backup
from audit import log_audit


def render():
    st.warning("الاستعادة ستستبدل قاعدة البيانات الحالية. يتم إنشاء نسخة أمان تلقائية قبل الاستعادة.")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**إنشاء نسخة احتياطية**")
        note = st.text_input("ملاحظة (اختياري)", key="bk_note")
        if st.button("إنشاء نسخة احتياطية الآن", type="primary"):
            try:
                path = backup.create_backup(note.strip())
                log_audit("database", 0, "STATUS_CHANGE", None, {"backup": str(path), "note": note.strip()}, note="إنشاء نسخة احتياطية")
                st.success(f"تم إنشاء النسخة الاحتياطية: {path}")
            except Exception as e:
                st.error(f"تعذر إنشاء النسخة الاحتياطية: {e}")

    with c2:
        st.markdown("**مجلد النسخ الاحتياطية**")
        st.code(str(backup.ensure_backup_dir()))

    st.markdown("---")
    st.markdown("**النسخ الاحتياطية المتوفرة**")
    items = backup.list_backups()
    if not items:
        st.info("لا توجد نسخ احتياطية بعد.")
        return

    df = pd.DataFrame(items)
    st.dataframe(df[["name","modified","size_bytes","note","path"]], use_container_width=True, hide_index=True)

    names = [i["name"] for i in items]
    sel = st.selectbox("اختر نسخة للاستعادة", names)
    confirm = st.checkbox("أؤكد أنني أريد استعادة هذه النسخة واستبدال قاعدة البيانات الحالية", value=False)
    if st.button("استعادة النسخة المحددة", disabled=not confirm):
        try:
            item = next(i for i in items if i["name"] == sel)
            backup.restore_backup(item["path"])
            st.cache_resource.clear(); st.cache_data.clear()
            log_audit("database", 0, "STATUS_CHANGE", {"restored_from": item["path"]}, {"restored_from": item["path"]}, note="استعادة نسخة احتياطية")
            st.success(f"تمت الاستعادة بنجاح من: {item['name']}. يُنصح بإعادة تحميل الصفحة.")
            st.rerun()
        except Exception as e:
            st.error(f"تعذر الاستعادة: {e}")
