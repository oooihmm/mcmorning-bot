import sqlite3

DB_NAME = "mcmorning.db"


def create_tables():
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

    conn.commit()
    conn.close()


if __name__ == "__main__":
    create_tables()
    print("✅ DB 테이블 생성 완료!")


def create_daily_attendance(date):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # 활성 멤버 조회
    cursor.execute(
        """
        SELECT id
        FROM users
        WHERE status = '활성'
        """
    )

    users = cursor.fetchall()

    # 오늘 출석 기록 미리 생성
    for (user_id,) in users:
        cursor.execute(
            """
            INSERT OR IGNORE INTO attendance (date, user_id)
            VALUES (?, ?)
            """,
            (date, user_id),
        )

    conn.commit()
    conn.close()


def save_wake_record(date, discord_id, name, status):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # 유저 조회
    cursor.execute(
        """
        SELECT id
        FROM users
        WHERE discord_id = ?
        """,
        (discord_id,),
    )

    user = cursor.fetchone()

    if user is None:
        conn.close()
        return

    user_id = user[0]

    # 기존 출석 기록의 기상 상태 업데이트
    cursor.execute(
        """
        UPDATE attendance
        SET wake_status = ?
        WHERE date = ? AND user_id = ?
        """,
        (status, date, user_id),
    )

    conn.commit()
    conn.close()


def save_video_record(date, discord_id, status):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # 유저 조회
    cursor.execute(
        "SELECT id FROM users WHERE discord_id = ?",
        (discord_id,),
    )

    user = cursor.fetchone()

    if user is None:
        conn.close()
        return

    user_id = user[0]

    # 해당 날짜의 출석 기록에 영상 참여 결과 저장
    cursor.execute(
        """
        UPDATE attendance
        SET video_status = ?
        WHERE date = ? AND user_id = ?
        """,
        (status, date, user_id),
    )

    conn.commit()
    conn.close()
