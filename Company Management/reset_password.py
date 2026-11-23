"""Emergency password reset (run on the machine that holds the database).

Usage:   py -3 reset_password.py
Asks for the username and a new password (typed hidden). Also clears any lockout.
Anyone who can run this already has the database file, so it is not a new exposure.
"""
import getpass
import sys

import db
import security


def reset(username: str, new_password: str) -> str:
    db.init_db()
    security.ensure_security_schema()
    row = db.query_one("SELECT id, username FROM users WHERE username=? COLLATE NOCASE", (username.strip(),))
    if not row:
        raise ValueError("لا يوجد مستخدم بهذا الاسم.")
    security.reset_password(row["id"], new_password)
    return row["username"]


def main() -> int:
    db.init_db()
    security.ensure_security_schema()
    users = security.list_users()
    if not users:
        print("لا يوجد مستخدمون بعد. افتح التطبيق وأنشئ حساب المدير الأول.")
        return 1
    print("المستخدمون:", ", ".join(u["username"] for u in users))
    username = input("اسم المستخدم المراد إعادة تعيين كلمة مروره: ").strip()
    pw1 = getpass.getpass("كلمة المرور الجديدة: ")
    pw2 = getpass.getpass("تأكيد كلمة المرور: ")
    if pw1 != pw2:
        print("كلمتا المرور غير متطابقتين.")
        return 1
    try:
        name = reset(username, pw1)
    except ValueError as ex:
        print(str(ex))
        return 1
    print(f"تمت إعادة تعيين كلمة مرور المستخدم {name} وفك أي قفل عنه.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
