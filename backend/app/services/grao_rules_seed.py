"""Grão merchant categorization rules seed.

Derived from 6 months (Jan–Jun) of the user's Grão app (app.dashplan.com.br):
strong commercial merchants observed in the transaction history, mapped to the
Securo categories. One rule per category, OR-matching the merchant tokens via
`contains` on the description, with a single `set_category` action — so future
transactions auto-classify. Single-user fork: names are hard-coded in pt-BR.

Only high-confidence commercial tokens are included (no person names, no weak
generic tokens). Ambiguous merchants the user resolves manually. The RGE/Vivo
split (parents → Doações, spouse → Casa) is encoded by distinct, fully-qualified
tokens.
"""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category
from app.models.rule import Rule

# Securo category name -> list of description tokens (matched case-insensitively
# via `contains`). Curated from the Grão history; high confidence only.
GRAO_RULES = {
    'Viagens': ['LATAM', 'AZUL LINHAS', 'AZUL ', 'AIRBNB', 'RENTCARS', 'INTERCITY', 'ESTAPAR', 'CLUBE LATAM', 'LIVELO', 'PARKING', 'HOTEL', 'POUSADA', 'CHALEZINHO'],
    'Restaurantes': ['RESTAURANTE', 'BOTECO', 'LANCHONETE', 'CAFETERIA', 'THE COFFEE', 'BACIO DI LATTE', 'BACIODILATTE', 'ESPETINO', 'BELLAGULA', 'ENCANTO SORVETERIA', 'MILK SHAKE', 'IFD BR', 'IFOOD', 'PONTO VINTE'],
    'Transporte': ['POSTO', 'UBER', 'MOVIDA', 'LOCALIZA', 'ESTACIONAMENTO', 'FLPARK', 'INDIGO', 'METRO RJ', 'AUTOPEL', 'VELOE', 'NEO AUTOPOSTO', 'SW COMERCIO DE COMBUTIV', 'NEW AUTOPOSTO'],
    'Assinaturas': ['NETFLIX', 'SPOTIFY', 'APPLE.COM', 'APPLECOMBILL', 'GOOGLE', 'OPENAI', 'CHATGPT', 'YOUTUBE', 'FOLHADESPAULO', 'DISNEY', 'AMAZON PRIME', 'HBO', 'PARAMOUNT'],
    'Compras': ['AMAZON BR', 'AMAZON MARKETPLACE', 'AMAZONMKTPLC', 'MERCADOLIVRE', 'MERCADO LIVRE', 'HAVAN', 'BAGAGGIO', 'CHILLIBEANS', 'GOCASE', 'ALIEXPRESS', 'SHOPEE', 'MAGAZINE'],
    'Saúde': ['FARMACIA', 'DROGARIA', 'DROGASIL', 'PANVEL', 'PANVEL FARMACIAS', 'RAIA', 'DIMED', 'LABIMED', 'UNIMED', 'PAGUE MENOS', 'PACHECO', 'HOSPITAL'],
    'Roupas e Acessórios': ['LOJAS RENNER', 'RENNER', 'CEA ', 'C&A', 'RIACHUELO', 'ASICSBR', 'ASICS', 'NIKE', 'ADIDAS', 'INSIDER', 'ATELIE VIP'],
    'Mercado': ['SUPERMERCAD', 'MERCADO BOM', 'STOK CENTER', 'BELLO MAR', 'NOVO SUPER', 'ATACADAO', 'CARREFOUR', 'ASSAI', 'BIG ', 'ZAFFARI'],
    'Seguros': ['AZOS SEGUROS', 'TOKIO MARINE', 'MONGERAL', 'ASSIST CARD', 'PORTO SEGURO', 'SULAMERICA', 'BRADESCO SEGUROS'],
    'Pets': ['PET SERVICOS', 'VETCENTER', 'CIA DOS BICHOS', 'PETZ', 'COBASI', 'PETLOVE'],
    'Investimentos': ['RENTAB.INVEST', 'APLICACAO RDB', 'APLICAÇÃO RDB', 'RESGATE RDB', 'RESGATE CDB', 'RESGATE INVEST', 'BANCO XP'],
    'Cuidados Pessoais': ['GUAPOBARBER', 'BARBER', 'LA MAFIA'],
    'Lazer': ['SALUTEEVENTOS', 'CLUBE RECREATIVO', 'AGROTURISMO', 'CINEMA', 'CINEPOLIS'],
    'Esportes': ['PELEA ESPORTES', 'SMARTFIT', 'SMART FIT', 'ACADEMIA'],
    'Educação': ['EF ENGLISH', 'UDEMY', 'ALURA', 'HOTMART'],
    'Impostos & Taxas': ['IOF', 'TRIBUTO'],
    'Doações': ['CONTA DE AGUA - CORSAN', 'CONTA DE TELEFONE - VIVO MOVEL', 'ONG ', 'PROJETO LIBERTAR'],
    'Moradia': ['CONTA DE LUZ - RGE', 'RESIDENCIAL FIORI', 'TRIPLE AAA', 'PLANO NUCEL', 'FERRAGEM'],
}


async def seed_grao_rules(
    session: AsyncSession,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> int:
    """Create one OR-contains rule per Grão category in the workspace.

    Resolves the target category by name. Idempotent: skips a category that
    already has a Grão rule (matched by rule name). Returns rules created.
    Categories absent from the workspace are skipped.
    """
    cats = (
        await session.execute(
            select(Category).where(Category.workspace_id == workspace_id)
        )
    ).scalars().all()
    id_by_name = {c.name: c.id for c in cats}

    existing_names = {
        n
        for n in (
            await session.execute(
                select(Rule.name).where(Rule.workspace_id == workspace_id)
            )
        ).scalars()
    }

    created = 0
    for category_name, tokens in GRAO_RULES.items():
        rule_name = f"Grão: {category_name}"
        if rule_name in existing_names:
            continue
        cat_id = id_by_name.get(category_name)
        if cat_id is None:
            continue
        session.add(
            Rule(
                user_id=user_id,
                workspace_id=workspace_id,
                name=rule_name,
                conditions_op="or",
                conditions=[
                    {"field": "description", "op": "contains", "value": t}
                    for t in tokens
                ],
                actions=[{"op": "set_category", "value": str(cat_id)}],
                priority=20,
                is_active=True,
            )
        )
        created += 1
    await session.commit()
    return created
