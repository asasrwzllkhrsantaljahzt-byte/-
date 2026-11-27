"""One-screen entry and ledger for all financial movements."""
from datetime import date

import pandas as pd
import streamlit as st

import hub_engine as E
import security
import vouchers as V
from db import query_all
from ui import excel_button, flash_set, number_field, pdf_button, row_action_bar, select_table, show_flash, tbump

_FLASH = "_fa_flash"
_EDIT = "_fa_edit"

_OPERATION_LABELS = {
    "transfer": "تحويل العميل للموظف",
    "employee_receipt": "استلام من الموظف",
    "settlement": "سداد مستحقات",
    "operating_expense": "مصروف تشغيلي",
    "owner_draw": "مسحوبات صاحب الشركة",
    "other_receipt": "استلام من جهة أخرى",
}
_SETTLEMENT_PARTIES = [
    ("representative", "مندوب"),
    ("contractor", "متعهد"),
    ("company", "عميل (مردود مستحق)"),
]


def _operation_for_voucher(row):
    if row["kind"] == "receipt" and row["party_type"] == "employee":
        return "employee_receipt"
    if row["kind"] == "payment" and row["party_type"] == "other":
        category = row.get("entry_category") or "settlement"
        if category in ("operating_expense", "owner_draw"):
            return category
    if row["kind"] == "payment":
        return "settlement"
    return "other_receipt"


def _collect_rows(allowed):
    rows = []
    if "التحويلات والحساب الشهري" in allowed:
        for item in E.list_transfers(status="all"):
            rows.append({
                "source": "transfer", "id": item["id"], "raw": item, "operation": "transfer",
                "date": item["transfer_date"], "month": item["work_month"],
                "party": item["company_name"], "employee": item["full_name"],
                "amount": float(item["amount"]), "method": "—",
                "description": item["notes"] or item["void_reason"] or "",
                "status": "ساري" if item["status"] == "active" else "ملغى",
                "active": item["status"] == "active",
            })
    if "التحويلات والحساب الشهري" in allowed:
        for item in V.list_vouchers():
            operation = _operation_for_voucher(item)
            rows.append({
                "source": "voucher", "id": item["id"], "raw": item, "operation": operation,
                "date": item["voucher_date"], "month": V.voucher_month(item),
                "party": item["party_name"],
                "employee": item["party_name"] if item["party_type"] == "employee" else "",
                "amount": float(item["amount"]), "method": V.METHOD_AR[item["method"]],
                "description": item["description"] or "",
                "status": "ساري" if item["status"] == "issued" else "ملغى",
                "active": item["status"] == "issued",
            })
    return sorted(rows, key=lambda row: (row["date"], row["id"]), reverse=True)


def _display_frame(rows):
    return pd.DataFrame([{
        "رقم الحركة": f"{'تحويل' if row['source'] == 'transfer' else 'سند'}-{row['id']:06d}",
        "التاريخ": row["date"], "نوع الحركة": _OPERATION_LABELS.get(row["operation"], "حركة مالية"),
        "الجهة": row["party"], "الموظف": row["employee"], "المبلغ": row["amount"],
        "طريقة الدفع": row["method"], "الشهر": row["month"] or "", "البيان": row["description"],
        "الحالة": row["status"],
    } for row in rows])


def _party_options(party_type):
    table, column = V.PARTY_TABLE[party_type]
    return query_all(f"SELECT id, {column} AS name FROM {table} ORDER BY {column}")


def _render_transfer_fields(key, edit_row):
    if edit_row:
        item = edit_row["raw"]
        months = E.month_options(item["work_month"])
        month = st.selectbox("شهر العمل", months, index=months.index(item["work_month"]), key=key + "month")
        st.caption(f"الشركة: {item['company_name']} · الموظف: {item['full_name']}")
        tdate = st.date_input("تاريخ التحويل", value=date.fromisoformat(item["transfer_date"]), key=key + "date")
        amount = number_field("المبلغ المحوّل", key + "amount", value=item["amount"], minimum=0)
        notes = st.text_area("ملاحظات", value=item["notes"] or "", key=key + "description")
        return {"placement_id": item["placement_id"], "month": month, "date": tdate, "amount": amount, "description": notes}

    companies = query_all("SELECT id, name FROM companies ORDER BY name")
    if not companies:
        st.info("أضف شركة وموظفاً أولاً من صفحة الشركات والموظفين.")
        return None
    company_ids = [item["id"] for item in companies]
    company_names = {item["id"]: item["name"] for item in companies}
    company_id = st.selectbox("الشركة العميلة", company_ids, format_func=company_names.get, key=key + "company")
    months = E.month_options()
    if not months:
        st.info("لا توجد أشهر عمل متاحة.")
        return None
    month = st.selectbox("شهر العمل", months, key=key + "month")
    from modules.monthly_page import _placements_for
    placements = _placements_for(company_id, month)
    if not placements:
        st.info("لا يوجد موظفون يعملون لدى هذه الشركة خلال الشهر المحدد.")
        return None
    placement_ids = [item["id"] for item in placements]
    placement_names = {item["id"]: item["full_name"] for item in placements}
    placement_id = st.selectbox("الموظف", placement_ids, format_func=placement_names.get, key=key + "employee")
    amount = number_field("المبلغ المحوّل", key + "amount", minimum=0)
    tdate = st.date_input("تاريخ التحويل", value=date.today(), key=key + "date")
    notes = st.text_area("ملاحظات", key=key + "description")
    return {"placement_id": placement_id, "month": month, "date": tdate, "amount": amount, "description": notes}


def _render_voucher_fields(key, operation, edit_row):
    item = edit_row["raw"] if edit_row else None
    is_edit = item is not None
    voucher_kind = item["kind"] if is_edit else ("receipt" if operation == "employee_receipt" else "payment")
    party_type = item["party_type"] if is_edit else None
    party_id = item["party_id"] if is_edit else None
    other_name = item["party_name"] if is_edit and party_type == "other" else ""

    if operation == "employee_receipt":
        party_type = "employee"
        parties = _party_options(party_type)
        if not parties:
            st.info("لا يوجد موظفون مسجلون بعد.")
            return None
        ids = [row["id"] for row in parties]
        names = {row["id"]: row["name"] for row in parties}
        index = ids.index(party_id) if is_edit and party_id in ids else 0
        party_id = st.selectbox("الموظف", ids, index=index, format_func=names.get, key=key + "employee")
    elif operation == "settlement":
        choices = list(_SETTLEMENT_PARTIES)
        if is_edit and party_type == "other":
            choices.append(("other", "جهة أخرى"))
        types = [kind for kind, _ in choices]
        party_type = st.selectbox("نوع الجهة", types,
                                  index=types.index(party_type) if is_edit and party_type in types else 0,
                                  format_func=dict(choices).get, key=key + "party_type")
        if party_type == "other":
            other_name = st.text_input("اسم الجهة *", value=other_name, key=key + "party_name")
            party_id = None
        else:
            parties = _party_options(party_type)
            if not parties:
                st.info(f"لا يوجد {dict(choices)[party_type]} مسجل بعد.")
                return None
            ids = [row["id"] for row in parties]
            names = {row["id"]: row["name"] for row in parties}
            index = ids.index(party_id) if is_edit and party_type == item["party_type"] and party_id in ids else 0
            party_id = st.selectbox("الجهة", ids, index=index, format_func=names.get, key=key + "party")
    elif operation in ("operating_expense", "owner_draw"):
        party_type = "other"
        other_name = st.text_input("اسم المصروف أو الجهة *", value=other_name, key=key + "party_name")
    elif operation == "other_receipt":
        if party_type == "other":
            other_name = st.text_input("اسم الجهة *", value=other_name, key=key + "party_name")
        else:
            st.caption(f"الجهة: {item['party_name']}")

    cols = st.columns(2)
    voucher_date = cols[0].date_input("التاريخ", value=date.fromisoformat(item["voucher_date"]) if item else date.today(),
                                      key=key + "date")
    amount = number_field("المبلغ", key + "amount", value=item["amount"] if item else None, minimum=0)
    methods = list(V.METHOD_AR)
    method = st.selectbox("طريقة الدفع", methods,
                          index=methods.index(item["method"]) if item else 0,
                          format_func=V.METHOD_AR.get, key=key + "method")
    reference = st.text_input("المرجع", value=(item["reference"] or "") if item else "", key=key + "reference")
    month = st.text_input("شهر العمل المتعلق", value=(item["month_ref"] or "") if item else "", key=key + "month")
    category = "settlement"
    if operation in ("operating_expense", "owner_draw"):
        category = operation
    elif is_edit:
        category = item.get("entry_category") or "settlement"
    description = st.text_area("البيان أو الملاحظة", value=(item["description"] or "") if item else "", key=key + "description")
    reason = st.text_input("سبب التصحيح *", key=key + "reason") if is_edit else ""
    return {"kind": voucher_kind, "party_type": party_type, "party_id": party_id,
            "other_name": other_name, "date": voucher_date, "amount": amount, "method": method,
            "reference": reference, "month": month, "description": description, "category": category,
            "reason": reason}


def _begin_edit(row, mode):
    st.session_state[_EDIT] = {"source": row["source"], "id": row["id"], "mode": mode}
    st.rerun()


def _bulk_preview_frame(items):
    return pd.DataFrame([{
        "المسلسل": serial,
        "صف Excel": item["row"],
        "الشركة": item.get("company", ""),
        "الموظف": item.get("employee", ""),
        "التاريخ": item["date"].isoformat() if item.get("date") else "",
        "المبلغ": f"{item['amount']:,.2f}" if item.get("amount") is not None else "",
        "الحالة": "جاهز" if item["action"] == "add" else "خطأ",
        "التفاصيل": item.get("error", ""),
    } for serial, item in enumerate(items, start=1)])


def _render_bulk_import(operation):
    import financial_import as FI

    warnings = st.session_state.pop("_fa_bulk_warnings", [])
    failures = st.session_state.pop("_fa_bulk_failures", [])
    for row, warning in warnings:
        st.warning(f"صف Excel {row}: {warning}")
    for row, error in failures:
        st.error(f"صف Excel {row}: {error}")

    upload_version = st.session_state.get("_fa_bulk_upload_version", 0)
    title = "تحويلات العملاء" if operation == "transfer" else "استلامات الموظفين"
    filename = (
        "تحويلات_العملاء_بالأسماء.xlsx"
        if operation == "transfer"
        else "استلامات_الموظفين_بالأسماء.xlsx"
    )
    with st.expander(f"تنزيل نموذج فارغ أو استيراد {title} من Excel"):
        st.caption(f"الحد الأقصى {FI.MAX_IMPORT_ROWS} حركة في الملف الواحد.")
        st.caption("املأ ورقة «الحركات» باستخدام أسماء الشركة والموظف كما تظهر في ورقة «المرجع». تظهر المعاينة قبل الحفظ.")
        if operation == "transfer":
            st.caption("التحويلان المتطابقان في الشركة والموظف والشهر والتاريخ والمبلغ والملاحظات يُعاملان كحركة مكررة.")
        else:
            st.caption("الاستلامان المتطابقان في الموظف والتاريخ والمبلغ وطريقة الدفع والمرجع والشهر والبيان يُعاملان كحركة مكررة.")
        st.download_button(
            "⬇️ تنزيل النموذج الفارغ",
            FI.template_bytes(operation),
            file_name=filename,
            key=f"fa_bulk_template_{operation}",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        uploaded = st.file_uploader(
            "ارفع النموذج بعد تعبئته",
            type=["xlsx"],
            key=f"fa_bulk_upload_{operation}_{upload_version}",
        )
        if uploaded is None:
            return
        try:
            items = FI.plan(FI.read_sheet(uploaded.getvalue(), operation), operation)
        except ValueError as ex:
            st.error(str(ex))
            return
        if not items:
            st.info("النموذج فارغ؛ أضف الحركات في ورقة «الحركات».")
            return

        preview = _bulk_preview_frame(items)
        st.dataframe(preview, use_container_width=True, hide_index=True, height=400)
        valid_count = sum(item["action"] == "add" for item in items)
        st.caption(f"{valid_count} صف صالح للاستيراد، و{len(items) - valid_count} صف يحتاج إلى تصحيح.")
        if not valid_count:
            st.info("لا توجد حركات صالحة للحفظ. صحّح الصفوف التي عليها أخطاء ثم ارفع الملف مجدداً.")
            return
        st.info(
            "اضغط «موافق - اعتماد وحفظ» لحفظ الصفوف الصالحة مباشرة. "
            "لا تضغط زر «حفظ الحركة» أسفل النموذج لهذه الحركات؛ الصفوف التي عليها أخطاء لن تُحفظ."
        )
        if st.button(
            f"✅ موافق - اعتماد وحفظ {valid_count} حركة",
            type="primary",
            key=f"fa_bulk_import_{operation}_{upload_version}",
        ):
            result = FI.apply(items, operation)
            st.session_state["_fa_bulk_failures"] = result["failed"]
            st.session_state["_fa_bulk_warnings"] = result["warnings"]
            if result["added"]:
                flash_set(
                    f"تم استيراد {result['added']} حركة مالية."
                    + (f" تعذر استيراد {len(result['failed'])} صف." if result["failed"] else ""),
                    "_fa_bulk_upload_version",
                )
                tbump("fa_ledger")
                st.rerun()
            for row, error in result["failed"]:
                st.error(f"صف Excel {row}: {error}")
            for row, warning in result["warnings"]:
                st.warning(f"صف Excel {row}: {warning}")


def _render_entry_form(rows, allowed, can):
    show_flash()
    edit_ref = st.session_state.get(_EDIT)
    edit_row = next((row for row in rows if edit_ref and row["source"] == edit_ref["source"]
                     and row["id"] == edit_ref["id"]), None)
    if edit_ref and not edit_row:
        st.session_state.pop(_EDIT, None)
        edit_ref = None
    editing = bool(edit_ref and edit_row)
    if edit_ref and edit_row and edit_ref["mode"] == "void":
        title = "إلغاء الحركة المالية"
    elif editing:
        title = "تعديل الحركة المالية"
    else:
        title = "إضافة حركة مالية"
    st.subheader(title)
    if not can:
        st.caption("ليست لديك صلاحية إضافة أو تعديل الحركات المالية.")
        return

    transfer_allowed = "التحويلات والحساب الشهري" in allowed
    vouchers_allowed = transfer_allowed
    operations = []
    if transfer_allowed:
        operations.append("transfer")
    if vouchers_allowed:
        operations.extend(["employee_receipt", "settlement", "operating_expense", "owner_draw"])
    if editing and edit_row["operation"] not in operations:
        operations.append(edit_row["operation"])
    if not operations:
        st.info("لا توجد صلاحية لإضافة حركات مالية.")
        return

    key = f"fa_{'edit_' + edit_ref['source'] + '_' + str(edit_ref['id']) if editing else 'new_' + str(st.session_state.get('_fa_version', 0))}_"
    operation = edit_row["operation"] if editing else st.selectbox(
        "نوع الحركة", operations, format_func=_OPERATION_LABELS.get, key=key + "operation")
    if editing:
        st.selectbox("نوع الحركة", operations, index=operations.index(operation),
                     format_func=_OPERATION_LABELS.get, key=key + "operation", disabled=True)

    if not editing and operation in ("transfer", "employee_receipt"):
        _render_bulk_import(operation)

    with st.container(border=True):
        if edit_ref and edit_ref["mode"] == "void":
            st.write(f"إلغاء: {_OPERATION_LABELS.get(edit_row['operation'], 'حركة مالية')} · {edit_row['party']} · {edit_row['amount']:,.2f} ر.س")
            reason = st.text_input("سبب الإلغاء *", key=key + "reason")
            save = st.button("تأكيد الإلغاء", type="primary", key=key + "void")
            cancel = st.button("إلغاء العملية", key=key + "cancel")
            if cancel:
                st.session_state.pop(_EDIT, None)
                st.rerun()
            if save:
                try:
                    if edit_ref["source"] == "transfer":
                        message = E.void_transfer(edit_ref["id"], reason)
                    else:
                        message = V.void_voucher(edit_ref["id"], reason)
                    flash_set(message, "_fa_version")
                except ValueError as ex:
                    st.error(str(ex))
                    return
                st.session_state.pop(_EDIT, None)
                tbump("fa_ledger")
                st.rerun()
            return

        if operation == "transfer":
            values = _render_transfer_fields(key, edit_row if editing and edit_ref["source"] == "transfer" else None)
        else:
            values = _render_voucher_fields(key, operation,
                                            edit_row if editing and edit_ref["source"] == "voucher" else None)
        if values is None:
            if editing:
                st.button("إلغاء التعديل", key=key + "cancel_empty", on_click=lambda: st.session_state.pop(_EDIT, None))
            return
        col1, col2 = st.columns(2)
        save_label = "حفظ التعديل" if editing else "حفظ الحركة"
        save = col1.button(save_label, type="primary", key=key + "save")
        cancel = col2.button("إلغاء التعديل", key=key + "cancel") if editing else False
        if cancel:
            st.session_state.pop(_EDIT, None)
            st.rerun()
        if not save:
            return
        try:
            if editing and edit_ref["source"] == "transfer":
                message = E.update_transfer(edit_ref["id"], values["month"], values["date"],
                                            values["amount"], values["description"])
            elif editing:
                if values["party_type"] == "other" and not (values["other_name"] or "").strip():
                    raise ValueError("اسم المصروف مطلوب.")
                reason = values["reason"].strip()
                if not reason:
                    raise ValueError("سبب التعديل مطلوب.")
                V.replace_voucher(edit_ref["id"], values["date"], values["amount"], values["method"],
                                  values["reference"], values["month"], values["description"],
                                  values["category"], reason, values["other_name"],
                                  values["party_type"], values["party_id"])
                message = "تم حفظ التصحيح وإلغاء الإذن السابق بسبب موثق."
            elif operation == "transfer":
                _, message, warnings = E.add_transfer(values["placement_id"], values["month"], values["date"],
                                                       values["amount"], values["description"])
                if warnings:
                    message += " " + warnings[0]
            else:
                V.issue_voucher(values["kind"], values["date"], values["party_type"], values["party_id"],
                                values["amount"], values["method"], values["reference"], values["month"],
                                values["description"], values["other_name"], values["category"])
                message = "تم تسجيل الحركة المالية."
        except ValueError as ex:
            st.error(str(ex))
            return
        except Exception as ex:  # noqa: BLE001
            from ui import friendly_error
            st.error(friendly_error(ex, "تعذر حفظ الحركة"))
            return
        flash_set(message, "_fa_version")
        st.session_state.pop(_EDIT, None)
        tbump("fa_ledger")
        st.rerun()


def _render_movements(allowed, can):
    rows = _collect_rows(allowed)
    _render_entry_form(rows, allowed, can)
    st.divider()
    st.subheader("سجل الحركات المالية")

    months = sorted({row["month"] for row in rows if row["month"]}, reverse=True)
    operation_values = sorted({_OPERATION_LABELS.get(row["operation"], "حركة مالية") for row in rows})
    col1, col2, col3 = st.columns(3)
    month_filter = col1.selectbox("شهر العمل", ["الكل"] + months, key="fa_month_filter")
    operation_filter = col2.selectbox("نوع الحركة", ["الكل"] + operation_values, key="fa_operation_filter")
    status_filter = col3.selectbox("الحالة", ["الكل", "ساري", "ملغى"], key="fa_status_filter")
    search = st.text_input("بحث في الجهة أو الموظف أو البيان", key="fa_search").strip()
    filtered = rows
    if month_filter != "الكل":
        filtered = [row for row in filtered if row["month"] == month_filter]
    if operation_filter != "الكل":
        filtered = [row for row in filtered if _OPERATION_LABELS.get(row["operation"], "حركة مالية") == operation_filter]
    if status_filter != "الكل":
        filtered = [row for row in filtered if row["status"] == status_filter]
    if search:
        filtered = [row for row in filtered if any(search in str(row[field]) for field in ("party", "employee", "description"))]
    if not filtered:
        st.info("لا توجد حركات مالية مطابقة.")
        return

    df = _display_frame(filtered)
    excel_button(df, "الحركات_المالية", "fa_excel")
    pdf_button(df, "سجل الحركات المالية", "الحركات_المالية", "fa_pdf")
    pos = select_table(df, "fa_ledger")
    st.caption(f"عدد الحركات المعروضة: {len(filtered)}")
    if pos is None:
        return
    row = filtered[pos]
    actions = row_action_bar(edit=can and row["active"], delete=can and row["active"],
                             print_=True, view=True, prefix=f"fa_row_{row['source']}_{row['id']}")
    if actions["view"]:
        st.write({"نوع الحركة": _OPERATION_LABELS.get(row["operation"], "حركة مالية"),
                  "التاريخ": row["date"], "الجهة": row["party"], "الموظف": row["employee"],
                  "المبلغ": f"{row['amount']:,.2f} ر.س", "الشهر": row["month"],
                  "البيان": row["description"], "الحالة": row["status"]})
    if actions["edit"]:
        _begin_edit(row, "edit")
    if actions["delete"]:
        _begin_edit(row, "void")
    if actions["print"]:
        pdf_button(df.iloc[[pos]], "تفاصيل الحركة المالية", f"حركة_{row['id']}",
                   f"fa_row_pdf_{row['source']}_{row['id']}")


def render(allowed):
    can = security.can_write()
    _render_movements(allowed, can)
