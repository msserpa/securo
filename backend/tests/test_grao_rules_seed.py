"""Tests for the Grão merchant categorization rules seed.

Derived from 6 months (Jan–Jun) of the user's Grão app: strong commercial
merchants mapped to Securo categories. One rule per category, OR-matching the
merchant tokens via `contains`, setting the category. Auto-classifies future
transactions.
"""
import uuid
import pytest
from sqlalchemy import select

from app.models.rule import Rule
from app.models.category import Category
from app.services.category_service import create_default_categories
from app.services.grao_rules_seed import seed_grao_rules


async def _seed_cats(session, test_user):
    from app.models.workspace import Workspace, WorkspaceMember
    ws_id = (await session.execute(
        select(Workspace.id).join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(WorkspaceMember.user_id == test_user.id).limit(1)
    )).scalar()
    await create_default_categories(session, test_user.id, "pt-BR", workspace_id=ws_id)
    return ws_id


@pytest.mark.asyncio
async def test_creates_one_rule_per_category(session, test_user):
    ws_id = await _seed_cats(session, test_user)
    # _seed_cats -> create_default_categories already seeds the Grão rules
    # automatically; calling again is a no-op (idempotent).
    again = await seed_grao_rules(session, test_user.id, ws_id)
    assert again == 0
    rules = [
        r for r in (await session.execute(select(Rule).where(Rule.workspace_id == ws_id))).scalars().all()
        if r.name.startswith("Grão: ")
    ]
    assert len(rules) > 0
    # every rule is OR with contains conditions and a set_category action
    for r in rules:
        assert r.conditions_op == "or"
        assert all(c["op"] == "contains" for c in r.conditions)
        assert r.actions[0]["op"] == "set_category"
        # action points at a real category in the workspace
        cat = (await session.execute(select(Category).where(Category.id == uuid.UUID(r.actions[0]["value"])))).scalar_one_or_none()
        assert cat is not None


@pytest.mark.asyncio
async def test_known_merchants_route_to_expected_category(session, test_user):
    ws_id = await _seed_cats(session, test_user)
    await seed_grao_rules(session, test_user.id, ws_id)
    rules = (await session.execute(select(Rule).where(Rule.workspace_id == ws_id))).scalars().all()
    # build merchant-token -> category-name lookup
    cats = {str(c.id): c.name for c in (await session.execute(select(Category).where(Category.workspace_id == ws_id))).scalars()}
    token_cat = {}
    for r in rules:
        cname = cats.get(r.actions[0]["value"])
        for c in r.conditions:
            token_cat[c["value"].upper()] = cname
    assert token_cat.get("LATAM") == "Viagens"
    assert token_cat.get("NETFLIX") == "Assinaturas"
    assert token_cat.get("POSTO") == "Transporte"
    assert token_cat.get("FARMACIA") == "Saúde"


@pytest.mark.asyncio
async def test_idempotent(session, test_user):
    ws_id = await _seed_cats(session, test_user)
    await seed_grao_rules(session, test_user.id, ws_id)
    n1 = len((await session.execute(select(Rule).where(Rule.workspace_id == ws_id))).scalars().all())
    await seed_grao_rules(session, test_user.id, ws_id)
    n2 = len((await session.execute(select(Rule).where(Rule.workspace_id == ws_id))).scalars().all())
    assert n1 == n2
