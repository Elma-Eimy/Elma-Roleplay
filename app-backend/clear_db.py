"""Reset the local SQLite/Chroma stores and rebuild SQLite through Alembic."""

import os
import shutil
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from core.database import BASE_DIR, engine
from core import models
from core.config import settings


def clear_databases() -> None:
    print("WARNING: this permanently deletes all SQLite and Chroma data.")
    if input("Continue? (y/n): ").lower() != "y":
        print("Cancelled.")
        return

    db_name = os.path.basename(settings.STORAGE_SQLITE_DB_PATH)
    print(f"\n[1/2] Resetting SQLite ({db_name})...")
    try:
        # Drop application tables, then remove Alembic's version marker too.
        # Recreating with Base.metadata.create_all() would leave a database
        # whose schema and alembic_version disagree on the next startup.
        models.Base.metadata.drop_all(bind=engine)
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS alembic_version"))

        alembic_cfg = Config(os.path.join(BASE_DIR, "alembic.ini"))
        alembic_cfg.set_main_option("script_location", os.path.join(BASE_DIR, "alembic"))
        command.upgrade(alembic_cfg, "head")
        print("  SQLite reset and rebuilt through Alembic.")
    except Exception as exc:
        print(f"  SQLite reset failed: {exc}")

    print("\n[2/2] Resetting ChromaDB...")
    chroma_path = settings.STORAGE_CHROMA_DB_PATH
    if os.path.exists(chroma_path):
        try:
            shutil.rmtree(chroma_path)
            print("  ChromaDB reset.")
        except Exception as exc:
            print(f"  ChromaDB reset failed: {exc}")
    else:
        print("  ChromaDB directory does not exist; skipped.")

    print("\nReset complete.")


if __name__ == "__main__":
    clear_databases()
