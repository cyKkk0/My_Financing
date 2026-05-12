from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


DEFAULT_ADMIN_USERNAME = "cykkk"
DEFAULT_ADMIN_PASSWORD_HASH = (
    "pbkdf2_sha256$260000$vdm_fNM6pqoCWai8tzFlUA$"
    "gD_U5v8Y9a_uH20XOGdDaiQyiUB4wTd6P5eW5fceo2g"
)


def ensure_lightweight_migrations(engine: Engine) -> None:
    if engine.dialect.name != "sqlite":
        ensure_default_admin_user(engine)
        return

    inspector = inspect(engine)
    if "dca_plans" not in inspector.get_table_names():
        _migrate_transactions(engine, inspector)
        ensure_default_admin_user(engine)
        return

    statements: list[str] = []
    columns = {column["name"] for column in inspector.get_columns("dca_plans")}
    if "start_date" not in columns:
        statements.append("ALTER TABLE dca_plans ADD COLUMN start_date DATE")
    if "end_date" not in columns:
        statements.append("ALTER TABLE dca_plans ADD COLUMN end_date DATE")
    if "fee" not in columns:
        statements.append("ALTER TABLE dca_plans ADD COLUMN fee NUMERIC(18,2) DEFAULT 0")

    snapshot_statements = _snapshot_migration_statements(inspector)
    statements.extend(snapshot_statements)

    transaction_statements = _transaction_migration_statements(inspector)
    statements.extend(transaction_statements)

    if not statements:
        ensure_default_admin_user(engine)
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
    ensure_default_admin_user(engine)


def ensure_default_admin_user(engine: Engine) -> None:
    inspector = inspect(engine)
    if "admin_users" not in inspector.get_table_names():
        return

    with engine.begin() as connection:
        admin_count = connection.execute(text("SELECT COUNT(*) FROM admin_users")).scalar_one()
        if admin_count:
            return
        connection.execute(
            text(
                """
                INSERT INTO admin_users (username, password_hash, is_active)
                VALUES (:username, :password_hash, 1)
                """
            ),
            {
                "username": DEFAULT_ADMIN_USERNAME,
                "password_hash": DEFAULT_ADMIN_PASSWORD_HASH,
            },
        )


def _migrate_transactions(engine: Engine, inspector) -> None:
    statements = _transaction_migration_statements(inspector)
    if not statements:
        return
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def _snapshot_migration_statements(inspector) -> list[str]:
    if "portfolio_snapshots" not in inspector.get_table_names():
        return []
    columns = {column["name"] for column in inspector.get_columns("portfolio_snapshots")}
    statements: list[str] = []
    if "cumulative_profit" not in columns:
        statements.append("ALTER TABLE portfolio_snapshots ADD COLUMN cumulative_profit NUMERIC(18,2)")
    if "cumulative_profit_rate" not in columns:
        statements.append("ALTER TABLE portfolio_snapshots ADD COLUMN cumulative_profit_rate NUMERIC(10,4)")
    return statements


def _transaction_migration_statements(inspector) -> list[str]:
    if "transactions" not in inspector.get_table_names():
        return []
    columns = {column["name"] for column in inspector.get_columns("transactions")}
    statements: list[str] = []
    if "external_id" not in columns:
        statements.append("ALTER TABLE transactions ADD COLUMN external_id VARCHAR(128)")
    if "import_source" not in columns:
        statements.append("ALTER TABLE transactions ADD COLUMN import_source VARCHAR(32)")
    if "initiated_at" not in columns:
        statements.append("ALTER TABLE transactions ADD COLUMN initiated_at DATETIME")
    if "confirmed_at" not in columns:
        statements.append("ALTER TABLE transactions ADD COLUMN confirmed_at DATETIME")
    if "status" not in columns:
        statements.append("ALTER TABLE transactions ADD COLUMN status VARCHAR(16) DEFAULT 'confirmed'")
    return statements
