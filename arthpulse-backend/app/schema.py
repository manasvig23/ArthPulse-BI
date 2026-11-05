"""Add missing columns when the database already existed before a model change."""

from sqlalchemy import text
from .database import engine


def _add(conn, table, column, ddl):
    # Use a nested transaction (savepoint) so if the column already exists 
    # and ALTER TABLE throws an error, it safely ignores it without hanging or aborting.
    trans = conn.begin_nested()
    try:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))
        trans.commit()
    except Exception:
        trans.rollback()


def ensure_schema():
    with engine.begin() as conn:
        extras = [
            ("vouchers", "discount_pct", "discount_pct FLOAT DEFAULT 0"),
            ("vouchers", "discount_amount", "discount_amount FLOAT DEFAULT 0"),
            ("vouchers", "city", "city VARCHAR"),
            ("vouchers", "state", "state VARCHAR"),
            ("vouchers", "pincode", "pincode VARCHAR"),
            ("vouchers", "godown", "godown VARCHAR"),
            ("vouchers", "tally_guid", "tally_guid VARCHAR"),
            ("inventory_items", "safety_stock", "safety_stock FLOAT DEFAULT 10"),
            ("inventory_items", "lead_time_days", "lead_time_days FLOAT DEFAULT 7"),
            ("inventory_items", "last_movement_date", "last_movement_date DATE"),
        ]
        for table, col, ddl in extras:
            _add(conn, table, col, ddl)