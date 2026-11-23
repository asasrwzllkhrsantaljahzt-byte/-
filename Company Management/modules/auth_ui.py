import streamlit as st
import security


def _setup_screen():
    st.markdown("## إعداد النظام لأول مرة")
    st.info("لا يوجد أي مستخدم بعد. أنشئ حساب **مدير النظام** الأول. احتفظ بكلمة المرور في مكان آمن، "
            "فلا توجد طريقة لاستعادتها إلا بواسطة مدير آخر.")
    with st.form("setup_form"):
        username = st.text_input("اسم المستخدم (إنجليزي، من 3 أحرف)", key="setup_user")
        display = st.text_input("الاسم الظاهر", key="setup_display")
        pw1 = st.text_input("كلمة المرور (8 أحرف على الأقل)", type="password", key="setup_pw1")
        pw2 = st.text_input("تأكيد كلمة المرور", type="password", key="setup_pw2")
        sub = st.form_submit_button("إنشاء حساب المدير وبدء الاستخدام")
    if sub:
        if pw1 != pw2:
            st.error("كلمتا المرور غير متطابقتين.")
            return
        try:
            uid = security.create_user(username, display, pw1, "admin")
            st.session_state["auth_user"] = security.session_user(security.get_user(uid))
            st.rerun()
        except ValueError as ex:
            st.error(str(ex))


def _login_screen():
    import branding
    if branding.logo_path():
        st.image(branding.logo_path(), width=110)
    st.markdown("## تسجيل الدخول")
    with st.form("login_form"):
        username = st.text_input("اسم المستخدم", key="login_user")
        password = st.text_input("كلمة المرور", type="password", key="login_pw")
        sub = st.form_submit_button("دخول")
    if sub:
        user, msg = security.authenticate(username, password)
        if user:
            st.session_state["auth_user"] = user
            st.rerun()
        else:
            st.error(msg)


def gate():
    """Returns the logged-in user dict, or draws the setup/login screen and stops the script."""
    user = st.session_state.get("auth_user")
    if user:
        fresh = security.get_user(user["id"])          # re-check every run: deactivation/role changes apply at once
        if fresh and fresh["is_active"]:
            st.session_state["auth_user"] = security.session_user(fresh)
            return st.session_state["auth_user"]
        st.session_state.pop("auth_user", None)
    if not security.has_users():
        _setup_screen()
    else:
        _login_screen()
    st.stop()


def logout_button():
    if st.button("تسجيل الخروج", key="logout_btn"):
        st.session_state.pop("auth_user", None)
        st.rerun()
