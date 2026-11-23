import sqlite3
import streamlit as st
import pandas as pd
import security
from ui import toast_flash


def _tab_account(me):
    st.markdown(f"**المستخدم:** {me['display_name']} ({me['username']}) — {security.ROLES[me['role']]}")
    st.markdown("#### تغيير كلمة المرور")
    with st.form("pw_change_form"):
        cur = st.text_input("كلمة المرور الحالية", type="password", key="pw_cur")
        new1 = st.text_input("كلمة المرور الجديدة", type="password", key="pw_new1")
        new2 = st.text_input("تأكيد كلمة المرور الجديدة", type="password", key="pw_new2")
        sub = st.form_submit_button("تغيير كلمة المرور")
    if sub:
        if new1 != new2:
            st.error("كلمتا المرور الجديدتان غير متطابقتين.")
        else:
            try:
                security.change_own_password(me["id"], cur, new1)
                st.success("تم تغيير كلمة المرور.")
            except ValueError as ex:
                st.error(str(ex))


def _tab_users(me):
    users = security.list_users()
    df = pd.DataFrame(users)
    df["role"] = df["role"].map(security.ROLES)
    df["can_view_sensitive"] = df["can_view_sensitive"].map({1: "نعم", 0: "لا"})
    df["is_active"] = df["is_active"].map({1: "نشط", 0: "موقوف"})
    df = df[["id", "username", "display_name", "role", "can_view_sensitive", "is_active", "last_login"]]
    df.columns = ["الرقم", "اسم المستخدم", "الاسم", "الدور", "يرى البيانات الحساسة", "الحالة", "آخر دخول"]
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.caption("المدير يرى البيانات الحساسة دائماً. المحاسب والمطّلع لا يرونها إلا إذا مُنحا الصلاحية هنا.")

    st.markdown("#### إضافة مستخدم")
    with st.form("user_add_form"):
        username = st.text_input("اسم المستخدم (إنجليزي)", key="ua_user")
        display = st.text_input("الاسم الظاهر", key="ua_display")
        role = st.selectbox("الدور", list(security.ROLES.keys()), index=1,
                            format_func=lambda r: security.ROLES[r], key="ua_role")
        sens = st.checkbox("يسمح له برؤية وتعديل البيانات الحساسة (الهوية والآيبان)", key="ua_sens")
        pw1 = st.text_input("كلمة المرور المؤقتة", type="password", key="ua_pw1")
        pw2 = st.text_input("تأكيد كلمة المرور", type="password", key="ua_pw2")
        sub = st.form_submit_button("إضافة المستخدم")
    if sub:
        if pw1 != pw2:
            st.error("كلمتا المرور غير متطابقتين.")
        else:
            try:
                uid = security.create_user(username, display, pw1, role, sens)
                st.session_state["_us_flash"] = f"تمت إضافة المستخدم رقم {uid}."
                st.rerun()
            except ValueError as ex:
                st.error(str(ex))

    st.markdown("#### تعديل صلاحيات مستخدم")
    labels = {f"#{u['id']} - {u['username']} ({u['display_name']})": u for u in users}
    sel = st.selectbox("المستخدم", list(labels.keys()), key="um_sel")
    u = labels[sel]
    is_self = u["id"] == me["id"]
    if is_self:
        st.info("لا يمكنك تغيير دورك أو إيقاف حسابك بنفسك. اطلب ذلك من مدير آخر.")
    with st.form("user_edit_form"):
        keys = list(security.ROLES.keys())
        role = st.selectbox("الدور", keys, index=keys.index(u["role"]), format_func=lambda r: security.ROLES[r],
                            key="um_role", disabled=is_self)
        sens = st.checkbox("يسمح له برؤية وتعديل البيانات الحساسة", value=bool(u["can_view_sensitive"]), key="um_sens")
        active = st.checkbox("الحساب نشط", value=bool(u["is_active"]), key="um_active", disabled=is_self)
        sub = st.form_submit_button("حفظ التعديلات")
    if sub:
        try:
            security.update_user_access(u["id"], u["role"] if is_self else role, sens,
                                        True if is_self else active)
            st.session_state["_us_flash"] = f"تم تحديث المستخدم {u['username']}."
            st.rerun()
        except (ValueError, sqlite3.IntegrityError) as ex:
            st.error(str(ex))

    st.markdown("#### إعادة تعيين كلمة مرور مستخدم")
    with st.form("user_reset_form"):
        pw1 = st.text_input("كلمة المرور الجديدة للمستخدم المختار أعلاه", type="password", key="ur_pw1")
        pw2 = st.text_input("تأكيد كلمة المرور", type="password", key="ur_pw2")
        sub = st.form_submit_button("إعادة التعيين")
    if sub:
        if pw1 != pw2:
            st.error("كلمتا المرور غير متطابقتين.")
        else:
            try:
                security.reset_password(u["id"], pw1)
                st.session_state["_us_flash"] = f"تمت إعادة تعيين كلمة مرور {u['username']}."
                st.rerun()
            except ValueError as ex:
                st.error(str(ex))


def render():
    toast_flash("_us_flash")
    me = security.current_user()
    if me["role"] == "admin":
        t1, t2 = st.tabs(["المستخدمون", "حسابي"])
        with t1:
            _tab_users(me)
        with t2:
            _tab_account(me)
    else:
        _tab_account(me)
