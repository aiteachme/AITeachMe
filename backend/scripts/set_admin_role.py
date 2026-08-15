"""Promote or revoke an administrator using the configured application database."""

from __future__ import annotations

import argparse

from sqlmodel import select

from app.models import User
from app.shared.infra.database import managed_session
from app.utils.time import utcnow


def main() -> None:
    parser = argparse.ArgumentParser(description="设置 AITeachMe 管理员角色")
    identity = parser.add_mutually_exclusive_group(required=True)
    identity.add_argument("--user-id")
    identity.add_argument("--email")
    parser.add_argument("--revoke", action="store_true", help="撤销管理员角色")
    args = parser.parse_args()

    with managed_session() as session:
        if args.user_id:
            user = session.get(User, args.user_id)
        else:
            user = session.exec(select(User).where(User.email == args.email.strip().lower())).first()
        if user is None or not user.is_registered:
            raise SystemExit("未找到已注册用户。")
        user.role = "user" if args.revoke else "admin"
        user.updated_at = utcnow()
        session.add(user)
        session.commit()
        print(f"{user.id}: role={user.role}")


if __name__ == "__main__":
    main()
