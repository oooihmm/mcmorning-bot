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


def save_wake_record(date, discord_id, name, status):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # 유저 조회
    cursor.execute(
        "SELECT id FROM users WHERE discord_id = ?",
        (discord_id,),
    )

    user = cursor.fetchone()

    # 유저가 없으면 등록
    if user is None:
        cursor.execute(
            """
            INSERT INTO users (discord_id, name)
            VALUES (?, ?)
            """,
            (discord_id, name),
        )
        user_id = cursor.lastrowid

    else:
        user_id = user[0]

    # 오늘 이미 기상 인증 기록이 있는지 확인
    cursor.execute(
        """
        SELECT id
        FROM attendance
        WHERE date = ? AND user_id = ?
        """,
        (date, user_id),
    )

    record = cursor.fetchone()

    if record is not None:
        conn.close()
        return

    # 기상 결과 저장
    cursor.execute(
        """
        INSERT INTO attendance (date, user_id, wake_status)
        VALUES (?, ?, ?)
        """,
        (date, user_id, status),
    )

    conn.commit()
    conn.close()
