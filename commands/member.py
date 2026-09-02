from typing import Literal

import discord

from services.member import (
    change_member_status,
    get_member,
    register_member,
)


def setup_member(bot):

    @bot.tree.command(
        name="멤버등록",
        description="스터디 멤버를 등록합니다.",
    )
    async def register_member_command(
        interaction: discord.Interaction,
        member: discord.Member,
    ):
        # 이미 등록된 멤버인지 확인
        user = get_member(member.id)

        if user is not None:
            await interaction.response.send_message(
                f"❌ {member.display_name}님은 이미 등록되어 있습니다.",
                ephemeral=True,
            )
            return

        # 멤버 등록
        register_member(
            discord_id=member.id,
            name=member.display_name,
        )

        await interaction.response.send_message(
            f"✅ {member.display_name}님을 스터디 멤버로 등록했습니다."
        )

    @bot.tree.command(
        name="멤버상태변경",
        description="스터디 멤버의 상태를 변경합니다.",
    )
    async def change_member_status_command(
        interaction: discord.Interaction,
        member: discord.Member,
        status: Literal["활성", "휴면", "강퇴"],
    ):
        # 등록된 멤버인지 확인
        user = get_member(member.id)

        if user is None:
            await interaction.response.send_message(
                f"❌ {member.display_name}님은 등록된 멤버가 아닙니다.",
                ephemeral=True,
            )
            return

        # 상태 변경
        change_member_status(
            discord_id=member.id,
            status=status,
        )

        await interaction.response.send_message(
            f"✅ {member.display_name}님의 상태를 **{status}**으로 변경했습니다."
        )
