import sqlite3
import streamlit as st
import security
import app_settings
import branding
import backup
import db
import integrity
from ui import toast_flash, number_field


def _perform_factory_reset(password):
    user = security.current_user()
    if not user or user.get("role") != "admin":
        raise PermissionError("ضبط المصنع متاح لمدير النظام فقط.")
    fresh_user = security.get_user(user["id"])
    if not fresh_user or fresh_user["role"] != "admin" or not fresh_user["is_active"]:
        raise PermissionError("ضبط المصنع متاح لمدير النظام النشط فقط.")
    verified_user, message = security.authenticate(fresh_user["username"], password or "")
    if not verified_user:
        raise ValueError(message or "كلمة مرور المدير غير صحيحة.")
    if verified_user["id"] != fresh_user["id"] or verified_user["role"] != "admin":
        raise PermissionError("ضبط المصنع متاح لمدير النظام النشط فقط.")

    safety_backup = backup.create_backup("نسخة أمان قبل ضبط المصنع")
    db.reset_all_data()
    return safety_backup


def render():
    user = security.current_user()
    if not user or user["role"] != "admin":
        st.error("الإعدادات متاحة لمدير النظام فقط.")
        return
    toast_flash("_set_flash")
    cur = app_settings.get_all()
    with st.form("settings_form"):
        st.markdown("**بيانات المنشأة** (يظهر الاسم في القائمة الجانبية)")
        org_name = st.text_input("اسم المنشأة *", value=cur["org_name"], key="set_org_name")
        c1, c2 = st.columns(2)
        with c1:
            cr = st.text_input("السجل التجاري", value=cur["org_commercial_register"], key="set_cr")
            phone = st.text_input("الهاتف", value=cur["org_phone"], key="set_phone")
        with c2:
            tax = st.text_input("الرقم الضريبي", value=cur["org_tax_number"], key="set_tax")
            addr = st.text_input("العنوان", value=cur["org_address"], key="set_addr")
        st.markdown("**التنبيهات**")
        d1, d2, d3 = st.columns(3)
        with d1:
            alert_days = number_field("تنبيه انتهاء العقود قبل (يوماً)", "set_alert_days", value=int(app_settings.get_int("contract_alert_days")), integer=True) or 0
        with d2:
            bk_days = number_field("تذكير النسخ الاحتياطي بعد (يوماً)", "set_bk_days", value=int(app_settings.get_int("backup_reminder_days")), integer=True) or 0
        with d3:
            doc_days = number_field("تنبيه انتهاء الوثائق قبل (يوماً)", "set_doc_days", value=int(app_settings.get_int("doc_alert_days")), integer=True) or 0
        d4, _x, _y = st.columns(3)
        with d4:
            dues_days = number_field("تنبيه المستحقات غير المسددة بعد (يوماً من نهاية الشهر)", "set_dues_days", value=int(app_settings.get_int("dues_alert_days")), integer=True) or 0
        st.markdown("**تفعيل أنواع التنبيه**")
        n1, n2, n3 = st.columns(3)
        with n1:
            contract_alerts = st.checkbox("انتهاء العقود", value=app_settings.get_bool("contract_alerts_enabled"), key="set_contract_alerts")
        with n2:
            doc_alerts = st.checkbox("انتهاء الوثائق", value=app_settings.get_bool("doc_alerts_enabled"), key="set_doc_alerts")
        with n3:
            backup_alerts = st.checkbox("النسخ الاحتياطي", value=app_settings.get_bool("backup_alerts_enabled"), key="set_backup_alerts")
        n4, n5 = st.columns(2)
        with n4:
            month_alerts = st.checkbox("الأشهر غير المقفلة وملاحظات المراجعة", value=app_settings.get_bool("month_alerts_enabled"), key="set_month_alerts")
        with n5:
            dues_alerts = st.checkbox("المستحقات والتحصيلات المتأخرة", value=app_settings.get_bool("dues_alerts_enabled"), key="set_dues_alerts")
        st.markdown("**الفواتير**")
        vat = number_field("نسبة ضريبة القيمة المضافة (%)", "set_vat", value=int(app_settings.get_int("vat_rate")), integer=True) or 0
        sub = st.form_submit_button("حفظ الإعدادات", type="primary")
    if sub:
        try:
            changed = app_settings.save({
                "org_name": org_name, "org_commercial_register": cr, "org_tax_number": tax,
                "org_phone": phone, "org_address": addr,
                "contract_alert_days": int(alert_days), "backup_reminder_days": int(bk_days),
                "doc_alert_days": int(doc_days), "dues_alert_days": int(dues_days), "vat_rate": int(vat),
                "contract_alerts_enabled": contract_alerts, "doc_alerts_enabled": doc_alerts,
                "backup_alerts_enabled": backup_alerts, "month_alerts_enabled": month_alerts,
                "dues_alerts_enabled": dues_alerts,
            })
            st.session_state.pop("_alerts", None)
            st.session_state.pop("_alerts_ts", None)
            st.session_state["_set_flash"] = "تم حفظ الإعدادات." if changed else "لا توجد تغييرات."
            st.rerun()
        except ValueError as ex:
            st.error(str(ex))

    st.info("التنبيهات داخل التطبيق تعمل محلياً. ربط Gmail أو WhatsApp مؤجل إلى مرحلة لاحقة، ولن تُحفظ بيانات دخول خارجية في قاعدة البيانات.")
    st.markdown("---")
    st.markdown("**الشعار** (يظهر في القائمة وشاشة الدخول والمطبوعات)")
    lp = branding.logo_path()
    c1, c2 = st.columns([1, 3])
    if lp:
        c1.image(lp, width=110)
    up = c2.file_uploader("رفع شعار جديد (PNG أو JPG)", type=["png", "jpg", "jpeg"], key="set_logo")
    if up is not None and isinstance(up.getvalue(), bytes) and c2.button("حفظ الشعار", key="set_logo_go"):
        try:
            st.session_state["_set_flash"] = branding.save_logo(up.getvalue())
            st.rerun()
        except ValueError as ex:
            st.error(str(ex))

    st.markdown("---")
    st.markdown("**فحص وإصلاح البرنامج**")
    st.caption("يفحص ملفات الإصدار وسلامة قاعدة البيانات، ثم يعيد تهيئة مخططها وذاكرة التطبيق دون حذف السجلات.")
    if st.button("فحص وإصلاح الآن", key="settings_repair"):
        release = integrity.check()
        if not release.get("no_manifest") and not release.get("ok"):
            st.error("بعض ملفات البرنامج ناقصة أو مختلفة. أعد تنزيل ملفات الإصدار قبل المتابعة.")
            for path in release["missing"]:
                st.caption(f"ملف ناقص: {path}")
            for path in release["different"]:
                st.caption(f"ملف مختلف: {path}")
        else:
            if release.get("no_manifest"):
                st.warning("تعذر التحقق من ملفات البرنامج لعدم وجود release_manifest.json.")
            try:
                check = db.check_database_integrity()
                if check != ["ok"]:
                    st.error("قاعدة البيانات تحتاج إلى استعادة نسخة احتياطية قبل الإصلاح.")
                    st.code("\n".join(check))
                else:
                    db.init_db()
                    st.cache_resource.clear()
                    st.cache_data.clear()
                    st.session_state["_set_flash"] = "اكتمل الفحص وإعادة تهيئة قاعدة البيانات دون حذف بياناتك."
                    st.rerun()
            except (OSError, sqlite3.Error) as ex:
                st.error(f"تعذر إصلاح قاعدة البيانات: {ex}")

    st.markdown("---")
    st.markdown("**ضبط المصنع**")
    st.warning(
        "تأكد من إنشاء نسخة احتياطية قبل المتابعة. سينشئ النظام نسخة أمان تلقائياً، "
        "ثم يحذف كل السجلات وحسابات المستخدمين والإعدادات. ستحتاج بعدها إلى إنشاء حساب مدير جديد. "
        "لن تُحذف ملفات النسخ الاحتياطية."
    )
    if st.button("ضبط المصنع", type="primary", key="factory_reset_button"):
        _factory_reset_dialog()


@st.dialog("تأكيد ضبط المصنع")
def _factory_reset_dialog():
    st.warning(
        "هذه العملية تحذف كل البيانات نهائياً من قاعدة البيانات. "
        "سيتم إنشاء نسخة أمان تلقائية قبل الحذف، ويمكنك إلغاء العملية بإغلاق النافذة."
    )
    with st.form("factory_reset_form"):
        password = st.text_input(
            "أدخل كلمة مرور مدير النظام",
            type="password",
            key="factory_reset_password",
        )
        confirmed = st.form_submit_button("التحقق من كلمة المرور وحذف البيانات", type="primary")
    if not confirmed:
        return
    try:
        safety_backup = _perform_factory_reset(password)
    except PermissionError as ex:
        st.error(str(ex))
    except ValueError as ex:
        st.error(str(ex))
    except (OSError, sqlite3.Error) as ex:
        st.error(f"تعذر إكمال ضبط المصنع: {ex}")
    else:
        st.session_state.clear()
        st.session_state["_factory_reset_notice"] = (
            f"تم ضبط المصنع. نسخة الأمان محفوظة في: {safety_backup}"
        )
        st.cache_resource.clear()
        st.cache_data.clear()
        st.rerun()
