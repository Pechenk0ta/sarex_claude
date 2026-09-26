"""Create the first administrator: `python -m app.scripts.create_admin EMAIL "ФИО"`.

The password is asked interactively and never appears in the shell history.
"""

import argparse
import asyncio
import getpass
import sys

from app.db import get_sessionmaker
from app.models import UserRole
from app.services.errors import ValidationError
from app.services.users import create_user


async def main(email: str, full_name: str, password: str) -> int:
    async with get_sessionmaker()() as session:
        try:
            user = await create_user(session, email, full_name, UserRole.ADMIN, password)
            await session.commit()
        except ValidationError as error:
            print(f"Ошибка: {error.message}", file=sys.stderr)
            return 1
    print(f"Администратор {user.email} создан.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Создать администратора")
    parser.add_argument("email")
    parser.add_argument("full_name")
    args = parser.parse_args()
    password = getpass.getpass("Пароль: ")
    if password != getpass.getpass("Пароль ещё раз: "):
        print("Ошибка: пароли не совпадают.", file=sys.stderr)
        sys.exit(1)
    sys.exit(asyncio.run(main(args.email, args.full_name, password)))
