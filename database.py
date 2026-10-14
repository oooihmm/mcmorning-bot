import os
from datetime import date, datetime
import sqlite3
from pathlib import Path
from contextlib import contextmanager

sqlite3.register_adapter(date, lambda value: value.isoformat())
sqlite3.register_adapter(datetime, lambda value: value.isoformat())

DB_NAME = os.getenv("DATABASE_PATH", str(Path(__file__).resolve().parent / "mcmorning.db"))


@contextmanager
def connect():
    conn = sqlite3.connect(DB_NAME, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def create_tables():
    path = Path(DB_NAME)
    if path.exists():
        with sqlite3.connect(DB_NAME) as source:
            columns = {row[1] for row in source.execute('PRAGMA table_info(attendance)')}
            if columns and 'final_reason' not in columns:
                suffix = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
                backup_path = str(path) + f'.pre-migration-{suffix}.bak'
                with sqlite3.connect(backup_path) as backup:
                    source.backup(backup)
                os.chmod(backup_path, 0o600)
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # 유저
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            discord_id INTEGER NOT NULL UNIQUE,
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT '활성'
        )
    """)

    # 출석
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date DATE NOT NULL,
            user_id INTEGER NOT NULL,
            wake_status TEXT,
            video_status TEXT,
            final_status TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id),
            UNIQUE (date, user_id)
        )
    """)

    # 벌점
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS penalties (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date DATE NOT NULL,
            user_id INTEGER NOT NULL,
            score INTEGER NOT NULL,
            reason TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # 휴무
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS leaves (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date DATE NOT NULL,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT '대기',
            evidence TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id),
            UNIQUE (date, user_id)
        )
    """)

    # 목표
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date DATE NOT NULL,
            user_id INTEGER NOT NULL,
            goal_list TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id),
            UNIQUE (date, user_id)
        )
    """)

    # 기존 기록을 보존한다. 과거 휴무의 신청/승인 시각은 추정하지 않는다.
    for table, columns in {
        'attendance': {'wake_at': 'TEXT', 'wake_message_id': 'INTEGER', 'final_reason': 'TEXT'},
        'leaves': {'requested_at': 'TEXT', 'approved_at': 'TEXT', 'processed_by': 'INTEGER'},
        'penalties': {'source': 'TEXT'},
    }.items():
        existing = {row[1] for row in cursor.execute(f'PRAGMA table_info({table})')}
        for column, kind in columns.items():
            if column not in existing:
                cursor.execute(f'ALTER TABLE {table} ADD COLUMN {column} {kind}')
    cursor.executescript("""
        CREATE UNIQUE INDEX IF NOT EXISTS penalty_attendance_once
        ON penalties(date, user_id, source) WHERE source = 'attendance';
        CREATE TABLE IF NOT EXISTS daily_threads (
            date TEXT PRIMARY KEY, thread_id INTEGER NOT NULL UNIQUE
        );
        CREATE TABLE IF NOT EXISTS video_snapshots (
            date TEXT NOT NULL, slot TEXT NOT NULL, user_id INTEGER NOT NULL,
            status TEXT NOT NULL, captured_at TEXT NOT NULL,
            PRIMARY KEY(date, slot, user_id), FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS jobs (
            date TEXT NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL,
            updated_at TEXT NOT NULL, detail TEXT,
            PRIMARY KEY(date, name)
        );
        CREATE TABLE IF NOT EXISTS leave_events (
            id INTEGER PRIMARY KEY, leave_id INTEGER NOT NULL,
            action TEXT NOT NULL, actor_id INTEGER NOT NULL, created_at TEXT NOT NULL,
            FOREIGN KEY(leave_id) REFERENCES leaves(id)
        );
        CREATE TABLE IF NOT EXISTS attendance_corrections (
            id INTEGER PRIMARY KEY, date TEXT NOT NULL, user_id INTEGER NOT NULL,
            result TEXT NOT NULL, reason TEXT NOT NULL, actor_id INTEGER NOT NULL,
            created_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS leave_windows (
            start_date TEXT PRIMARY KEY, end_date TEXT NOT NULL, published_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS calendar_overrides (
            date TEXT PRIMARY KEY, is_holiday INTEGER NOT NULL, reason TEXT NOT NULL
        );
    """)
    cursor.execute("""INSERT OR IGNORE INTO leave_windows(start_date,end_date,published_at)
        SELECT date(date,'+2 days'), date(date,'+6 days'), updated_at FROM jobs
        WHERE name='weekly_leave' AND status='done'""")
    conn.commit()
    conn.close()


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / '.env')
    DB_NAME = os.getenv('DATABASE_PATH', DB_NAME)
    create_tables()
    print("✅ DB 테이블 생성 완료!")
