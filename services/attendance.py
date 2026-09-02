import sqlite3
from datetime import timedelta

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


def get_leave(date, discord_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT leaves.id, leaves.type, leaves.status, leaves.evidence
        FROM leaves
        JOIN users ON leaves.user_id = users.id
        WHERE leaves.date = ?
          AND users.discord_id = ?
        """,
        (date, discord_id),
    )

    leave = cursor.fetchone()

    conn.close()

    return leave


def get_weekly_leave_amount(date, discord_id):
    week_start = date - timedelta(days=date.weekday())
    week_end = week_start + timedelta(days=6)

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT leaves.type
        FROM leaves
        JOIN users ON leaves.user_id = users.id
        WHERE users.discord_id = ?
          AND leaves.date BETWEEN ? AND ?
          AND leaves.status != '반려'
        """,
        (discord_id, week_start, week_end),
    )

    records = cursor.fetchall()

    conn.close()

    amount = 0.0

    for (leave_type,) in records:
        if leave_type == "종일":
            amount += 1.0

        elif leave_type in (
            "반휴(늦게 참여)",
            "반휴(일찍 퇴장)",
        ):
            amount += 0.5

        # 기타 → 0
        # 주간 한도에 포함하지 않음

    return amount


def create_leave(date, discord_id, leave_type, evidence=None):
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
        return False, "미등록"

    user_id = user[0]

    # 종일 / 반휴는 주간 한도 확인
    if leave_type != "기타":
        weekly_amount = get_weekly_leave_amount(
            date=date,
            discord_id=discord_id,
        )

        leave_amount = 1.0 if leave_type == "종일" else 0.5

        if weekly_amount + leave_amount > 1.0:
            conn.close()
            return False, "주간한도초과"

    status = "대기" if leave_type == "기타" else "승인"

    cursor.execute(
        """
        INSERT INTO leaves (
            date,
            user_id,
            type,
            status,
            evidence
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            date,
            user_id,
            leave_type,
            status,
            evidence,
        ),
    )

    conn.commit()
    conn.close()

    return True, status


def get_pending_leaves():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT leaves.id,
               leaves.date,
               users.name,
               leaves.type,
               leaves.evidence
        FROM leaves
        JOIN users ON leaves.user_id = users.id
        WHERE leaves.status = '대기'
        ORDER BY leaves.date, users.name
        """
    )

    records = cursor.fetchall()

    conn.close()

    return records


def change_leave_status(leave_id, status):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE leaves
        SET status = ?
        WHERE id = ?
          AND status = '대기'
        """,
        (status, leave_id),
    )

    success = cursor.rowcount > 0

    conn.commit()
    conn.close()

    return success
