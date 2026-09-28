"""Automated tests verifying Alembic migrations apply, rollback, and reapply cleanly."""

import os
from alembic.config import Config
from alembic import command

MIGRATION_TEST_DB = "test_migration_cycle.db"


def test_migration_lifecycle():
    """Verify alembic upgrade head, downgrade base, and re-upgrade on isolated database."""
    if os.path.exists(MIGRATION_TEST_DB):
        try:
            os.remove(MIGRATION_TEST_DB)
        except OSError:
            pass

    alembic_cfg = Config("alembic.ini")
    db_abs_path = os.path.abspath(MIGRATION_TEST_DB)
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_abs_path}")

    try:
        # Step 1: Upgrade to head
        command.upgrade(alembic_cfg, "head")
        assert os.path.exists(MIGRATION_TEST_DB)

        # Step 2: Downgrade to base
        command.downgrade(alembic_cfg, "base")

        # Step 3: Re-upgrade to head
        command.upgrade(alembic_cfg, "head")
        assert os.path.exists(MIGRATION_TEST_DB)

    finally:
        if os.path.exists(MIGRATION_TEST_DB):
            try:
                os.remove(MIGRATION_TEST_DB)
            except OSError:
                pass
