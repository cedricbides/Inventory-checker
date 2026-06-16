"""
database.py — SQLite setup for the OMS webapp.

Run this file ONCE to create oms.db:
    cd webapp
    python database.py

Tables created:
  - jobs                        (Job Scheduler entries)
  - discrepancies               (Discrepancy Engine entries)
  - retry_queue                 (Retry Queue entries)
  - users                       (App login accounts with roles)
  - unified_inventory_snapshot  (Latest marketplace pull per mp_id)
  - ordazzle_snapshot           (Last manual Ordazzle upload per warehouse)
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "oms.db")


def get_db():
    """Return a sqlite3 connection with row_factory set to Row (dict-like rows)."""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA cache_size=-65536")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA mmap_size=268435456")
    return conn


def init_db():
    with get_db() as conn:
        conn.executescript("""
            -- ── Job Scheduler ────────────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS jobs (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                job_name       TEXT    NOT NULL,
                channel        TEXT    NOT NULL DEFAULT '',
                shop           TEXT    NOT NULL DEFAULT '',
                fn             TEXT    NOT NULL DEFAULT '',
                freq           TEXT    NOT NULL DEFAULT 'Every 5 mins',
                active         INTEGER NOT NULL DEFAULT 1,
                last_exec      TEXT,
                last_status    TEXT,
                start_date     TEXT,
                notify_on_fail INTEGER NOT NULL DEFAULT 0,
                notify_users   TEXT    NOT NULL DEFAULT '[]',
                brand          TEXT    NOT NULL DEFAULT '',
                created_at     TEXT    NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_jobs_active      ON jobs(active);
            CREATE INDEX IF NOT EXISTS idx_jobs_channel     ON jobs(channel);
            CREATE INDEX IF NOT EXISTS idx_jobs_brand       ON jobs(brand);

            -- ── Discrepancy Engine ────────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS discrepancies (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                sku           TEXT    NOT NULL,
                brand         TEXT    NOT NULL DEFAULT '',
                channel       TEXT    NOT NULL DEFAULT '',
                shop          TEXT    NOT NULL DEFAULT '',
                ordazzle_qty  INTEGER NOT NULL DEFAULT 0,
                channel_qty   INTEGER NOT NULL DEFAULT 0,
                sap_qty       INTEGER NOT NULL DEFAULT 0,
                diff          INTEGER NOT NULL DEFAULT 0,
                severity      TEXT    NOT NULL DEFAULT 'low',
                last_checked  TEXT,
                status        TEXT    NOT NULL DEFAULT 'open',
                note          TEXT    NOT NULL DEFAULT '',
                created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_disc_sku          ON discrepancies(sku);
            CREATE INDEX IF NOT EXISTS idx_disc_brand        ON discrepancies(brand);
            CREATE INDEX IF NOT EXISTS idx_disc_channel      ON discrepancies(channel);
            CREATE INDEX IF NOT EXISTS idx_disc_severity     ON discrepancies(severity);
            CREATE INDEX IF NOT EXISTS idx_disc_status       ON discrepancies(status);
            CREATE INDEX IF NOT EXISTS idx_disc_brand_ch_status
                ON discrepancies(brand, channel, status);

            -- ── Retry Queue ───────────────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS retry_queue (
                id            TEXT    PRIMARY KEY,
                job_name      TEXT    NOT NULL,
                brand         TEXT    NOT NULL DEFAULT '',
                channel       TEXT    NOT NULL DEFAULT '',
                attempts      INTEGER NOT NULL DEFAULT 0,
                max_attempts  INTEGER NOT NULL DEFAULT 3,
                next_retry    TEXT,
                error         TEXT    NOT NULL DEFAULT '',
                last_attempt  TEXT,
                priority      TEXT    NOT NULL DEFAULT 'medium',
                created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_retry_priority    ON retry_queue(priority);
            CREATE INDEX IF NOT EXISTS idx_retry_brand       ON retry_queue(brand);
            CREATE INDEX IF NOT EXISTS idx_retry_created     ON retry_queue(created_at);

            -- ── Users ─────────────────────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT    NOT NULL UNIQUE,
                password_hash TEXT    NOT NULL,
                role          TEXT    NOT NULL DEFAULT 'user',
                full_name     TEXT    NOT NULL DEFAULT '',
                permissions   TEXT    NOT NULL DEFAULT '[]',
                created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
                last_login    TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_users_username    ON users(username);
            CREATE INDEX IF NOT EXISTS idx_users_role        ON users(role);

            -- ── Unified Inventory Snapshot ────────────────────────────────────
            -- One row per (mp_id, sku). Rows persist per mp_id until that
            -- marketplace is re-imported (never full-table wiped).
            CREATE TABLE IF NOT EXISTS unified_inventory_snapshot (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id         TEXT    NOT NULL,
                mp_id          TEXT    NOT NULL DEFAULT '',
                brand          TEXT    NOT NULL DEFAULT '',
                marketplace    TEXT    NOT NULL DEFAULT '',
                sku            TEXT    NOT NULL,
                article        TEXT    NOT NULL DEFAULT '',
                stock          INTEGER NOT NULL DEFAULT 0,
                status         TEXT    NOT NULL DEFAULT 'active',
                mp_id_1_label  TEXT,
                mp_id_1_value  TEXT,
                mp_id_2_label  TEXT,
                mp_id_2_value  TEXT,
                pulled_at      TEXT,
                created_at     TEXT    NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_uni_mp_id        ON unified_inventory_snapshot(mp_id);
            CREATE INDEX IF NOT EXISTS idx_uni_brand        ON unified_inventory_snapshot(brand);
            CREATE INDEX IF NOT EXISTS idx_uni_marketplace  ON unified_inventory_snapshot(marketplace);
            CREATE INDEX IF NOT EXISTS idx_uni_status       ON unified_inventory_snapshot(status);
            CREATE INDEX IF NOT EXISTS idx_uni_sku          ON unified_inventory_snapshot(sku);
            CREATE INDEX IF NOT EXISTS idx_uni_stock        ON unified_inventory_snapshot(stock);
            CREATE INDEX IF NOT EXISTS idx_uni_pulled_at    ON unified_inventory_snapshot(pulled_at);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_uni_mp_sku
                ON unified_inventory_snapshot(mp_id, sku);
            CREATE INDEX IF NOT EXISTS idx_uni_brand_mp_status
                ON unified_inventory_snapshot(brand, marketplace, status);

            -- ── Ordazzle Snapshot ─────────────────────────────────────────────
            -- Populated whenever a user runs Inventory Check with an Ordazzle
            -- file. Replaces the previous snapshot for that warehouse node.
            -- Used by the discrepancy engine instead of the (removed) fake API.
            CREATE TABLE IF NOT EXISTS ordazzle_snapshot (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                upload_id   TEXT    NOT NULL,
                sku         TEXT    NOT NULL,
                node_name   TEXT    NOT NULL DEFAULT '',
                brand       TEXT    NOT NULL DEFAULT '',
                inv_stock   INTEGER NOT NULL DEFAULT 0,
                uploaded_at TEXT    NOT NULL DEFAULT (datetime('now'))
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_ord_snap_node_sku
                ON ordazzle_snapshot(node_name, sku);
            CREATE INDEX IF NOT EXISTS idx_ord_snap_sku       ON ordazzle_snapshot(sku);
            CREATE INDEX IF NOT EXISTS idx_ord_snap_node      ON ordazzle_snapshot(node_name);
            CREATE INDEX IF NOT EXISTS idx_ord_snap_brand     ON ordazzle_snapshot(brand);
            CREATE INDEX IF NOT EXISTS idx_ord_snap_uploaded  ON ordazzle_snapshot(uploaded_at);

            -- Default admin account (password: admin) — change after first login
            INSERT OR IGNORE INTO users (username, password_hash, role, full_name, permissions)
            VALUES ('admin', '8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918', 'admin', 'Administrator', '["all"]');
        """)
        conn.commit()
    print(f"✓ Database ready: {DB_PATH}")


def migrate_db():
    """Add any missing columns/indexes to existing databases (safe to run repeatedly)."""
    with get_db() as conn:
        # ── users: permissions column ─────────────────────────────────────────
        cols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
        if "permissions" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN permissions TEXT NOT NULL DEFAULT '[]'")
            conn.execute("UPDATE users SET permissions = '[\"all\"]' WHERE role = 'admin'")
            conn.commit()
            print("✓ Migration: added permissions column to users")

        # ── unified_inventory_snapshot: create if missing ─────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS unified_inventory_snapshot (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id         TEXT    NOT NULL,
                mp_id          TEXT    NOT NULL DEFAULT '',
                brand          TEXT    NOT NULL DEFAULT '',
                marketplace    TEXT    NOT NULL DEFAULT '',
                sku            TEXT    NOT NULL,
                article        TEXT    NOT NULL DEFAULT '',
                stock          INTEGER NOT NULL DEFAULT 0,
                status         TEXT    NOT NULL DEFAULT 'active',
                mp_id_1_label  TEXT,
                mp_id_1_value  TEXT,
                mp_id_2_label  TEXT,
                mp_id_2_value  TEXT,
                pulled_at      TEXT,
                created_at     TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)

        # ── ordazzle_snapshot: create if missing (existing DBs) ───────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ordazzle_snapshot (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                upload_id   TEXT    NOT NULL,
                sku         TEXT    NOT NULL,
                node_name   TEXT    NOT NULL DEFAULT '',
                brand       TEXT    NOT NULL DEFAULT '',
                inv_stock   INTEGER NOT NULL DEFAULT 0,
                uploaded_at TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)

        # ── Apply all indexes (IF NOT EXISTS = safe to re-run) ────────────────
        index_ddls = [
            "CREATE INDEX IF NOT EXISTS idx_jobs_active      ON jobs(active)",
            "CREATE INDEX IF NOT EXISTS idx_jobs_channel     ON jobs(channel)",
            "CREATE INDEX IF NOT EXISTS idx_jobs_brand       ON jobs(brand)",
            "CREATE INDEX IF NOT EXISTS idx_disc_sku         ON discrepancies(sku)",
            "CREATE INDEX IF NOT EXISTS idx_disc_brand       ON discrepancies(brand)",
            "CREATE INDEX IF NOT EXISTS idx_disc_channel     ON discrepancies(channel)",
            "CREATE INDEX IF NOT EXISTS idx_disc_severity    ON discrepancies(severity)",
            "CREATE INDEX IF NOT EXISTS idx_disc_status      ON discrepancies(status)",
            "CREATE INDEX IF NOT EXISTS idx_disc_brand_ch_status ON discrepancies(brand, channel, status)",
            "CREATE INDEX IF NOT EXISTS idx_retry_priority   ON retry_queue(priority)",
            "CREATE INDEX IF NOT EXISTS idx_retry_brand      ON retry_queue(brand)",
            "CREATE INDEX IF NOT EXISTS idx_retry_created    ON retry_queue(created_at)",
            "CREATE INDEX IF NOT EXISTS idx_users_username   ON users(username)",
            "CREATE INDEX IF NOT EXISTS idx_users_role       ON users(role)",
            "CREATE INDEX IF NOT EXISTS idx_uni_mp_id        ON unified_inventory_snapshot(mp_id)",
            "CREATE INDEX IF NOT EXISTS idx_uni_brand        ON unified_inventory_snapshot(brand)",
            "CREATE INDEX IF NOT EXISTS idx_uni_marketplace  ON unified_inventory_snapshot(marketplace)",
            "CREATE INDEX IF NOT EXISTS idx_uni_status       ON unified_inventory_snapshot(status)",
            "CREATE INDEX IF NOT EXISTS idx_uni_sku          ON unified_inventory_snapshot(sku)",
            "CREATE INDEX IF NOT EXISTS idx_uni_stock        ON unified_inventory_snapshot(stock)",
            "CREATE INDEX IF NOT EXISTS idx_uni_pulled_at    ON unified_inventory_snapshot(pulled_at)",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_uni_mp_sku ON unified_inventory_snapshot(mp_id, sku)",
            "CREATE INDEX IF NOT EXISTS idx_uni_brand_mp_status ON unified_inventory_snapshot(brand, marketplace, status)",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_ord_snap_node_sku ON ordazzle_snapshot(node_name, sku)",
            "CREATE INDEX IF NOT EXISTS idx_ord_snap_sku      ON ordazzle_snapshot(sku)",
            "CREATE INDEX IF NOT EXISTS idx_ord_snap_node     ON ordazzle_snapshot(node_name)",
            "CREATE INDEX IF NOT EXISTS idx_ord_snap_brand    ON ordazzle_snapshot(brand)",
            "CREATE INDEX IF NOT EXISTS idx_ord_snap_uploaded ON ordazzle_snapshot(uploaded_at)",
        ]
        for ddl in index_ddls:
            try:
                conn.execute(ddl)
            except Exception as e:
                print(f"  ⚠ Index skipped ({e}): {ddl[:60]}")
        conn.commit()
        print("✓ Migration: all indexes applied")


if __name__ == "__main__":
    init_db()
    migrate_db()