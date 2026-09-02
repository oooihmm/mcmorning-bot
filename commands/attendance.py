from datetime import date

import discord

from services.attendance import (
    calculate_final_attendance,
    get_attendance,
)


def setup_attendance(bot):

    @bot.tree.command(
        name="출결판정",
        description="선택한 날짜의 최종 출결을 판정합니다.",
    )
    async def calculate_attendance(
        interaction: discord.Interaction,
        날짜: str,
    ):
        # 날짜 형식 확인
        try:
            target_date = date.fromisoformat(날짜)
        except ValueError:
            await interaction.response.send_message(
                "❌ 날짜는 `YYYY-MM-DD` 형식으로 입력해주세요.\n예: `2026-09-02`",
                ephemeral=True,
            )
            return

        calculate_final_attendance(target_date)

        await interaction.response.send_message(
            f"✅ {target_date} 출결 판정이 완료되었습니다."
        )

    @bot.tree.command(
        name="출결확인",
        description="선택한 날짜의 출결을 확인합니다.",
    )
    async def check_attendance(
        interaction: discord.Interaction,
        날짜: str,
    ):
        # 날짜 형식 확인
        try:
            target_date = date.fromisoformat(날짜)
        except ValueError:
            await interaction.response.send_message(
                "❌ 날짜는 `YYYY-MM-DD` 형식으로 입력해주세요.\n예: `2026-09-02`",
                ephemeral=True,
            )
            return

        records = get_attendance(target_date)

        if not records:
            await interaction.response.send_message(
                f"❌ {target_date}의 출결 기록이 없습니다.",
                ephemeral=True,
            )
            return

        result = [f"📋 **{target_date} 출결 현황**", ""]

        for name, wake_status, video_status, final_status in records:
            result.append(
                f"**{name}** | "
                f"기상: {wake_status or '-'} | "
                f"영상: {video_status or '-'} | "
                f"최종: {final_status or '-'}"
            )

        await interaction.response.send_message("\n".join(result))
