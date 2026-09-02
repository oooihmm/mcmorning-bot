import sqlite3

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
