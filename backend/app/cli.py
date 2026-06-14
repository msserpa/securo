"""CLI commands for managing the application."""
import asyncio
import sys
import uuid

from sqlalchemy import select

from app.core.database import async_session_maker
from app.models.user import User


async def generate_recurring() -> None:
    """Generate pending recurring transactions for all users."""
    from app.models.user import User as UserModel
    from app.services import recurring_transaction_service

    async with async_session_maker() as session:
        result = await session.execute(select(UserModel))
        users = result.scalars().all()
        total = 0
        for user in users:
            count = await recurring_transaction_service.generate_pending(session, user.id)
            if count > 0:
                print(f"Generated {count} transactions for {user.email}")
                total += count
        print(f"Total generated: {total}")


async def create_user(email: str, password: str) -> None:
    """Create a new user with the given email and password."""
    from pwdlib import PasswordHash

    hasher = PasswordHash.recommended()

    async with async_session_maker() as session:
        # Check if user already exists
        result = await session.execute(select(User).where(User.email == email))
        existing = result.scalar_one_or_none()
        if existing:
            print(f"Error: User with email '{email}' already exists.")
            sys.exit(1)

        user = User(
            id=uuid.uuid4(),
            email=email,
            hashed_password=hasher.hash(password),
            is_active=True,
            is_superuser=False,
            is_verified=True,
            preferences={
                "language": "pt-BR",
                "date_format": "DD/MM/YYYY",
                "timezone": "America/Sao_Paulo",
                "currency_display": "USD",
            },
        )
        session.add(user)
        await session.commit()
        print(f"User created successfully: {email}")


async def seed_grao_plan(email: str) -> None:
    """Seed the Grão-style categories + recurring budgets for an existing user.

    Idempotent — safe to run on a workspace that already has some of the
    categories/budgets. Used to backfill the plan for a user created before
    the seed existed (the auto-seed in create_default_categories only runs for
    brand-new workspaces).
    """
    from app.models.workspace import Workspace, WorkspaceMember
    from app.services.category_group_service import create_default_groups
    from app.services.grao_plan_seed import (
        create_grao_categories,
        seed_grao_plan_budgets,
    )

    async with async_session_maker() as session:
        user = (
            await session.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        if user is None:
            print(f"Error: no user with email '{email}'.")
            sys.exit(1)

        ws_id = (
            await session.execute(
                select(Workspace.id)
                .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
                .where(WorkspaceMember.user_id == user.id)
                .limit(1)
            )
        ).scalar()
        if ws_id is None:
            print(f"Error: user '{email}' has no workspace.")
            sys.exit(1)

        groups = await create_default_groups(session, user.id, "pt-BR", workspace_id=ws_id)
        await create_grao_categories(session, user.id, ws_id, groups)
        created = await seed_grao_plan_budgets(session, user.id, ws_id)
        print(f"Grão plan seeded for {email}: {created} recurring budgets created.")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python -m app.cli create-user <email> <password>")
        sys.exit(1)

    command = sys.argv[1]

    if command == "create-user":
        if len(sys.argv) != 4:
            print("Usage: python -m app.cli create-user <email> <password>")
            sys.exit(1)
        email, password = sys.argv[2], sys.argv[3]
        asyncio.run(create_user(email, password))
    elif command == "generate-recurring":
        asyncio.run(generate_recurring())
    elif command == "seed-grao-plan":
        if len(sys.argv) != 3:
            print("Usage: python -m app.cli seed-grao-plan <email>")
            sys.exit(1)
        asyncio.run(seed_grao_plan(sys.argv[2]))
    else:
        print(f"Unknown command: {command}")
        print("Available commands: create-user, generate-recurring, seed-grao-plan")
        sys.exit(1)


if __name__ == "__main__":
    main()
