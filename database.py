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


def calculate_final_attendance(date):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # 해당 날짜의 출석 기록 조회
    cursor.execute(
        """
        SELECT id, wake_status, video_status
        FROM attendance
        WHERE date = ?
        """,
        (date,),
    )

    records = cursor.fetchall()

    for attendance_id, wake_status, video_status in records:
        # 기상 또는 영상 참여 기록이 하나라도 없으면 결석
        if wake_status is None or video_status is None:
            final_status = "결석"

        # 기상 + 영상 참여 → 출석
        elif wake_status == "기상" and video_status == "참여":
            final_status = "출석"

        # 지각 + 영상 참여 → 지각
        elif wake_status == "지각" and video_status == "참여":
            final_status = "지각"

        # 그 외 → 결석
        else:
            final_status = "결석"

        cursor.execute(
            """
            UPDATE attendance
            SET final_status = ?
            WHERE id = ?
            """,
            (final_status, attendance_id),
        )

    conn.commit()
    conn.close()
