import sqlite3

from database import DB_NAME


def create_daily_attendance(date):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id
        FROM users
        WHERE status = '활성'
        """
    )

    users = cursor.fetchall()

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
        if wake_status is None or video_status is None:
            final_status = "결석"

        elif wake_status == "기상" and video_status == "참여":
            final_status = "출석"

        elif wake_status == "지각" and video_status == "참여":
            final_status = "지각"

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


def get_attendance(date):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT users.name, attendance.wake_status,
               attendance.video_status, attendance.final_status
        FROM attendance
        JOIN users ON attendance.user_id = users.id
        WHERE attendance.date = ?
        ORDER BY users.name
        """,
        (date,),
    )

    records = cursor.fetchall()

    conn.close()

    return records
