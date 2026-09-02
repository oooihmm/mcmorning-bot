import sqlite3
from typing import Literal

import discord

from database import DB_NAME


def setup_member(bot):

    @bot.tree.command(
        name="멤버등록",
        description="스터디 멤버를 등록합니다.",
    )
    async def register_member(
        interaction: discord.Interaction,
        member: discord.Member,
    ):
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        # 이미 등록된 멤버인지 확인
        cursor.execute(
            """
            SELECT id
            FROM users
            WHERE discord_id = ?
            """,
            (member.id,),
        )

        user = cursor.fetchone()

        if user is not None:
            conn.close()

            await interaction.response.send_message(
                f"❌ {member.display_name}님은 이미 등록되어 있습니다.",
                ephemeral=True,
            )
            return

        # 멤버 등록
        cursor.execute(
            """
            INSERT INTO users (discord_id, name, status)
            VALUES (?, ?, ?)
            """,
            (
                member.id,
                member.display_name,
                "활성",
            ),
        )

        conn.commit()
        conn.close()

        await interaction.response.send_message(
            f"✅ {member.display_name}님을 스터디 멤버로 등록했습니다."
        )

    @bot.tree.command(
        name="멤버상태변경",
        description="스터디 멤버의 상태를 변경합니다.",
    )
    async def change_member_status(
        interaction: discord.Interaction,
        member: discord.Member,
        status: Literal["활성", "휴면", "강퇴"],
    ):

        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        # 등록된 멤버인지 확인
        cursor.execute(
            """
            SELECT id
            FROM users
            WHERE discord_id = ?
            """,
            (member.id,),
        )

        user = cursor.fetchone()

        if user is None:
            conn.close()

            await interaction.response.send_message(
                f"❌ {member.display_name}님은 등록된 멤버가 아닙니다.",
                ephemeral=True,
            )
            return

        # 상태 변경
        cursor.execute(
            """
            UPDATE users
            SET status = ?
            WHERE discord_id = ?
            """,
            (status, member.id),
        )

        conn.commit()
        conn.close()

        await interaction.response.send_message(
            f"✅ {member.display_name}님의 상태를 **{status}**으로 변경했습니다."
        )
