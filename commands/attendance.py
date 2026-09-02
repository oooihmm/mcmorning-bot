import os
from datetime import date, time
from zoneinfo import ZoneInfo

import discord

from services.attendance import (
    calculate_final_attendance,
    create_daily_attendance,
    get_attendance,
    save_video_record,
    save_wake_record,
)

WAKE_CHANNEL_ID = int(os.getenv("WAKE_CHANNEL_ID"))
MORNING_CHANNEL_ID = int(os.getenv("MORNING_CHANNEL_ID"))

wake_thread_id = None


def setup_attendance(bot):

    @bot.tree.command(
        name="기상게시글",
        description="기상 인증 게시글을 생성합니다.",
    )
    async def create_wake_post(interaction: discord.Interaction):

        channel = bot.get_channel(WAKE_CHANNEL_ID)

        if channel is None:
            await interaction.response.send_message(
                "❌ 기상인증 채널을 찾을 수 없습니다.",
                ephemeral=True,
            )
            return

        thread = await channel.create_thread(
            name="☀️ 오늘의 기상 인증",
            content="8:00까지 이 게시글에 답글을 달아주세요!",
        )

        global wake_thread_id
        wake_thread_id = thread.thread.id

        today = discord.utils.utcnow().astimezone(ZoneInfo("Asia/Seoul")).date()

        create_daily_attendance(today)

        await interaction.response.send_message(
            f"☀️ 기상 인증 게시글을 생성했습니다!\n{thread.thread.jump_url}",
            ephemeral=True,
        )

    @bot.event
    async def on_message(message: discord.Message):

        if message.author.bot:
            return

        if message.channel.id != wake_thread_id:
            return

        kst_time = message.created_at.astimezone(ZoneInfo("Asia/Seoul"))

        print("☀️ 기상 인증 발견!")
        print(f"작성자: {message.author}")
        print(f"작성시간: {kst_time}")

        # 기상: 8시 0분 59초까지
        wake_time = time(8, 0, 59)
        # 지각: 8시 30분 59초까지
        late_time = time(8, 30, 59)

        if kst_time.time() <= wake_time:
            status = "기상"
        elif kst_time.time() <= late_time:
            status = "지각"
        else:
            status = "결석"
        print(f"기상 인증 결과: {status}")

        save_wake_record(
            date=kst_time.date(),
            discord_id=message.author.id,
            name=message.author.display_name,
            status=status,
        )

        await bot.process_commands(message)

    @bot.tree.command(
        name="스터디출첵",
        description="스터디 참여자를 확인합니다.",
    )
    async def check_video_attendance(interaction):
        channel = bot.get_channel(MORNING_CHANNEL_ID)

        if channel is None:
            print("❌ 모닝 채널을 찾을 수 없습니다.")
            return

        print("🎥 영상 참여 확인!")

        for member in channel.members:
            voice = member.voice

            camera_on = voice.self_video
            screen_share_on = voice.self_stream
            status = "참여" if (camera_on or screen_share_on) else "미참여"

            save_video_record(
                date=discord.utils.utcnow().astimezone(ZoneInfo("Asia/Seoul")).date(),
                discord_id=member.id,
                status=status,
            )

        await interaction.response.send_message(
            f"🎥 현재 모닝 채널 참여자: {len(channel.members)}명"
        )

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
