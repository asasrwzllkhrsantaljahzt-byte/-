import streamlit as st
import assistant

_SUGGEST = ["كم صافي الشهر الماضي؟", "مين لم يحوَّل لها هذا الشهر؟", "كيف يُحسب الشهر؟", "كيف أضيف موظفة؟", "ما التنبيهات؟"]


def render():
    st.caption("مساعد يعمل بدون إنترنت: يشرح طريقة استخدام البرنامج ويجيب من بياناتك. لا ينفّذ أي تعديل.")
    hist = st.session_state.setdefault("_chat", [])
    cols = st.columns(len(_SUGGEST))
    pick = None
    for i, s in enumerate(_SUGGEST):
        if cols[i].button(s, key=f"as_s{i}", use_container_width=True):
            pick = s
    q = st.chat_input("اكتب سؤالك هنا…") or pick
    if q:
        try:
            a = assistant.answer(q)
        except Exception as ex:  # noqa: BLE001
            a = f"تعذر الجواب: {ex}"
        hist.append((q, a))
    for q_, a_ in hist[-12:]:
        with st.chat_message("user"):
            st.write(q_)
        with st.chat_message("assistant"):
            st.markdown(a_)
    if hist and st.button("🧹 مسح المحادثة", key="as_clear"):
        st.session_state["_chat"] = []
        st.rerun()
