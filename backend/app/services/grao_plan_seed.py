"""Grão-style plan seed: extra expense categories + recurring monthly targets.

Mirrors the user's "Meu Plano" from the Grão app (app.dashplan.com.br): a set
of expense categories, each with a *general* monthly target. Targets are
materialised as **recurring** budgets anchored at ``ANCHOR_MONTH`` — a recurring
budget applies to its anchor month and every month after it (see
``budget_service._build_budget_map``), so a single row per category expresses a
target valid for all months.

This fork is single-user, so names are hard-coded in pt-BR.
"""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import Budget
from app.models.category import Category
from app.schemas.budget import BudgetCreate
from app.services import budget_service

# Anchor month for the recurring targets — the month shown as the Grão example.
# The target then applies to this month and every later one.
ANCHOR_MONTH = date(2026, 5, 1)

# Categories the Grão plan needs that Securo's defaults don't cover. Existing
# Securo categories (Moradia, Mercado, Saúde, ...) are reused, not recreated —
# they're absent from this list on purpose. Categories the Grão keeps separate
# from an existing one (Restaurantes vs Alimentação, Despesas Médicas vs Saúde)
# are created so the granularity matches the Grão.
GRAO_NEW_CATEGORIES = [
    {"name": "Viagens",                "group": "lifestyle", "icon": "plane",        "color": "#0EA5E9"},
    {"name": "Roupas e Acessórios",    "group": "lifestyle", "icon": "shirt",        "color": "#F472B6"},
    {"name": "Despesas Médicas",       "group": "lifestyle", "icon": "stethoscope",  "color": "#EF4444"},
    {"name": "Restaurantes",           "group": "food",      "icon": "utensils",     "color": "#F59E0B"},
    {"name": "Prestadores de Serviço", "group": "other",     "icon": "wrench",       "color": "#78716C"},
    {"name": "Seguros",                "group": "other",     "icon": "shield",       "color": "#64748B"},
    {"name": "Esportes",               "group": "lifestyle", "icon": "dumbbell",     "color": "#22C55E"},
    {"name": "Pets",                   "group": "lifestyle", "icon": "dog",          "color": "#D946EF"},
    {"name": "Serviços Financeiros",   "group": "other",     "icon": "landmark",     "color": "#6366F1"},
    {"name": "Ferramentas",            "group": "other",     "icon": "hammer",       "color": "#6B7280"},
]

# Securo category name -> general monthly target (BRL). Mix of reused defaults
# and the new categories above. Grão categories whose target is R$0 are omitted
# — a zero target is not a target.
GRAO_BUDGETS: dict[str, Decimal] = {
    # reused Securo categories
    "Moradia":                 Decimal("5000"),
    "Mercado":                 Decimal("2000"),
    "Transporte":              Decimal("1500"),
    "Saúde":                   Decimal("1400"),
    "Compras":                 Decimal("800"),
    "Cuidados Pessoais":       Decimal("800"),
    "Educação":                Decimal("800"),
    "Assinaturas":             Decimal("400"),
    "Lazer":                   Decimal("100"),
    "Doações":                 Decimal("500"),
    # new categories
    "Viagens":                 Decimal("6000"),
    "Roupas e Acessórios":     Decimal("3000"),
    "Despesas Médicas":        Decimal("2500"),
    "Restaurantes":            Decimal("1500"),
    "Prestadores de Serviço":  Decimal("1480"),
    "Seguros":                 Decimal("712"),
    "Esportes":                Decimal("600"),
    "Pets":                    Decimal("500"),
    "Serviços Financeiros":    Decimal("400"),
    "Ferramentas":             Decimal("60"),
}


async def create_grao_categories(
    session: AsyncSession,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    groups: dict,
) -> None:
    """Create the Grão-only categories that don't yet exist in the workspace.

    ``groups`` maps a group internal key -> CategoryGroup (the same dict
    ``create_default_groups`` returns). Idempotent: skips a category whose name
    already exists in the workspace.
    """
    existing = set(
        (
            await session.execute(
                select(Category.name).where(Category.workspace_id == workspace_id)
            )
        ).scalars()
    )
    for cat in GRAO_NEW_CATEGORIES:
        if cat["name"] in existing:
            continue
        group = groups.get(cat["group"])
        session.add(
            Category(
                user_id=user_id,
                workspace_id=workspace_id,
                name=cat["name"],
                icon=cat["icon"],
                color=cat["color"],
                is_system=True,
                group_id=group.id if group else None,
            )
        )
    await session.commit()


async def seed_grao_plan_budgets(
    session: AsyncSession,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> int:
    """Create one recurring budget per Grão target, reusing ``create_budget``.

    Idempotent: skips a category that already has a recurring budget. Returns
    the number of budgets created. Categories missing from the workspace are
    skipped (defensive — the category seed should have created them).
    """
    cats = (
        await session.execute(
            select(Category).where(Category.workspace_id == workspace_id)
        )
    ).scalars().all()
    id_by_name = {c.name: c.id for c in cats}

    existing_recurring = {
        cat_id
        for cat_id in (
            await session.execute(
                select(Budget.category_id).where(
                    Budget.workspace_id == workspace_id,
                    Budget.is_recurring.is_(True),
                )
            )
        ).scalars()
    }

    created = 0
    for name, amount in GRAO_BUDGETS.items():
        cat_id = id_by_name.get(name)
        if cat_id is None or cat_id in existing_recurring:
            continue
        await budget_service.create_budget(
            session,
            workspace_id,
            user_id,
            BudgetCreate(
                category_id=cat_id,
                amount=amount,
                month=ANCHOR_MONTH,
                is_recurring=True,
            ),
        )
        created += 1
    return created
