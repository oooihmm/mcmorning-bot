import discord


def setup_attendance(bot):

    @bot.tree.command(
        name="출석",
        description="오늘 스터디 출석을 체크합니다.",
    )
    async def attendance(interaction: discord.Interaction):

        await interaction.response.send_message(
            f"☕ {interaction.user.mention}님 출석 완료!"
        )
