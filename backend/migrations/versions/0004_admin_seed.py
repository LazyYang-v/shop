"""Create or update the local demo administrator from environment settings."""

import os
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa


revision = "0004_admin_seed"
down_revision = "0003_identity"
branch_labels = None
depends_on = None
ADMIN_ID = str(uuid5(NAMESPACE_URL, "shop-portfolio:local-admin"))


def upgrade() -> None:
    email = os.getenv("SHOP_ADMIN_EMAIL", "").strip().lower()
    password_hash = os.getenv("SHOP_ADMIN_PASSWORD_HASH", "")
    if not email or not password_hash:
        return

    bind = op.get_bind()
    users = sa.table(
        "users",
        sa.column("id", sa.Uuid()),
        sa.column("email", sa.String()),
        sa.column("password_hash", sa.String()),
        sa.column("role", sa.String()),
        sa.column("is_active", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    existing = bind.execute(sa.select(users.c.id).where(users.c.email == email)).scalar_one_or_none()
    if existing is None:
        bind.execute(
            users.insert().values(
                id=ADMIN_ID,
                email=email,
                password_hash=password_hash,
                role="admin",
                is_active=True,
                created_at=datetime.now(timezone.utc),
            )
        )
    else:
        bind.execute(
            users.update().where(users.c.id == existing).values(
                password_hash=password_hash,
                role="admin",
                is_active=True,
            )
        )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM users WHERE id = :admin_id").bindparams(admin_id=ADMIN_ID))
