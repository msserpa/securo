"""Tests for the Grão-style plan seed: extra categories + recurring budgets.

The seed mirrors the user's "Meu Plano" from the Grão app — a set of expense
categories each with a general (recurring) monthly target. Categories that
already exist in Securo are reused; the rest are created. Targets become
recurring budgets anchored at ANCHOR_MONTH, so they apply to every month from
the anchor onwards.
"""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.category import Category
from app.models.budget import Budget
from app.services.category_service import create_default_categories
from app.services import budget_service
from app.services.grao_plan_seed import (
    GRAO_BUDGETS,
    GRAO_NEW_CATEGORIES,
    ANCHOR_MONTH,
    seed_grao_plan_budgets,
)


async def _seed_base(session, test_user):
    """Seed the default Securo categories (incl. the Grão extras) for the
    user's workspace, returning the workspace_id."""
    from app.models.workspace import Workspace, WorkspaceMember

    ws_id = (
        await session.execute(
            select(Workspace.id)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .where(WorkspaceMember.user_id == test_user.id)
            .limit(1)
        )
    ).scalar()
    await create_default_categories(session, test_user.id, "pt-BR", workspace_id=ws_id)
    return ws_id


@pytest.mark.asyncio
async def test_creates_new_grao_categories(session, test_user):
    ws_id = await _seed_base(session, test_user)
    names = {
        c.name
        for c in (
            await session.execute(
                select(Category).where(Category.workspace_id == ws_id)
            )
        ).scalars()
    }
    # Every new Grão category must be present.
    for cat in GRAO_NEW_CATEGORIES:
        assert cat["name"] in names, f"missing new category {cat['name']}"
    # Reused ones are not duplicated (exactly one "Saúde", one "Moradia").
    for reused in ("Saúde", "Moradia", "Mercado"):
        count = len([n for n in names if n == reused])
        assert count == 1, f"{reused} duplicated"


@pytest.mark.asyncio
async def test_seeds_twenty_recurring_budgets(session, test_user):
    ws_id = await _seed_base(session, test_user)
    await seed_grao_plan_budgets(session, test_user.id, ws_id)

    budgets = (
        await session.execute(select(Budget).where(Budget.workspace_id == ws_id))
    ).scalars().all()
    assert len(budgets) == len(GRAO_BUDGETS) == 20
    assert all(b.is_recurring for b in budgets), "all budgets must be recurring"
    assert all(b.month == ANCHOR_MONTH for b in budgets)

    by_cat = {}
    cats = (
        await session.execute(select(Category).where(Category.workspace_id == ws_id))
    ).scalars().all()
    name_by_id = {c.id: c.name for c in cats}
    for b in budgets:
        by_cat[name_by_id[b.category_id]] = b.amount

    assert by_cat["Viagens"] == Decimal("6000")
    assert by_cat["Moradia"] == Decimal("5000")
    assert by_cat["Ferramentas"] == Decimal("60")


@pytest.mark.asyncio
async def test_recurring_targets_apply_to_later_months(session, test_user):
    """A recurring budget anchored in May must show up in June, July, etc."""
    ws_id = await _seed_base(session, test_user)
    await seed_grao_plan_budgets(session, test_user.id, ws_id)

    june = date(2026, 6, 1)
    july = date(2026, 7, 1)
    for m in (june, july):
        got = await budget_service.get_budgets(session, ws_id, month=m)
        amounts = {b.category_id: b.amount for b in got}
        assert len(amounts) == 20, f"recurring targets missing for {m}"


@pytest.mark.asyncio
async def test_idempotent(session, test_user):
    ws_id = await _seed_base(session, test_user)
    await seed_grao_plan_budgets(session, test_user.id, ws_id)
    # Running the whole seed again must not duplicate categories or budgets.
    await create_default_categories(session, test_user.id, "pt-BR", workspace_id=ws_id)
    await seed_grao_plan_budgets(session, test_user.id, ws_id)

    cats = (
        await session.execute(select(Category).where(Category.workspace_id == ws_id))
    ).scalars().all()
    budgets = (
        await session.execute(select(Budget).where(Budget.workspace_id == ws_id))
    ).scalars().all()
    assert len([c for c in cats if c.name == "Viagens"]) == 1
    assert len(budgets) == 20


@pytest.mark.asyncio
async def test_zero_target_categories_have_no_budget(session, test_user):
    """Grão categories with a R$0 target are not in GRAO_BUDGETS at all."""
    ws_id = await _seed_base(session, test_user)
    await seed_grao_plan_budgets(session, test_user.id, ws_id)
    # No budget should have amount 0.
    budgets = (
        await session.execute(select(Budget).where(Budget.workspace_id == ws_id))
    ).scalars().all()
    assert all(b.amount > 0 for b in budgets)
