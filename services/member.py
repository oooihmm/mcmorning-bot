import sqlite3

from database import DB_NAME


def get_member(discord_id):
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

    conn.close()

    return user


def register_member(discord_id, name):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO users (discord_id, name, status)
        VALUES (?, ?, ?)
        """,
        (discord_id, name, "활성"),
    )

    conn.commit()
    conn.close()


def change_member_status(discord_id, status):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE users
        SET status = ?
        WHERE discord_id = ?
        """,
        (status, discord_id),
    )

    conn.commit()
    conn.close()
