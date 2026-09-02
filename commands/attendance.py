import os
from datetime import date, time
from typing import Literal
from zoneinfo import ZoneInfo

import discord

from services.attendance import (
    calculate_final_attendance,
    change_leave_status,
    create_daily_attendance,
    create_leave,
    get_attendance,
    get_leave,
    get_pending_leaves,
    save_video_record,
    save_wake_record,
)

WAKE_CHANNEL_ID = int(os.getenv("WAKE_CHANNEL_ID"))
MORNING_CHANNEL_ID = int(os.getenv("MORNING_CHANNEL_ID"))

wake_thread_id = None


def setup_attendance(bot):
    setup_wake(bot)
    setup_video(bot)
    setup_attendance_check(bot)
    setup_leave(bot)


def setup_wake(bot):

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


def setup_video(bot):

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


def setup_attendance_check(bot):

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


def setup_leave(bot):

    @bot.tree.command(
        name="휴무신청",
        description="휴무를 신청합니다.",
    )
    async def request_leave(
        interaction: discord.Interaction,
        날짜: str,
        유형: Literal[
            "종일",
            "반휴(늦게 참여)",
            "반휴(일찍 퇴장)",
            "기타",
        ],
        증빙: discord.Attachment | None = None,
    ):
        try:
            target_date = date.fromisoformat(날짜)
        except ValueError:
            await interaction.response.send_message(
                "❌ 날짜는 `YYYY-MM-DD` 형식으로 입력해주세요.\n예: `2026-09-04`",
                ephemeral=True,
            )
            return

        # 기타 휴무는 증빙 필수
        if 유형 == "기타" and 증빙 is None:
            await interaction.response.send_message(
                "❌ 기타 휴무는 증빙 자료를 첨부해야 합니다.",
                ephemeral=True,
            )
            return

        existing_leave = get_leave(
            date=target_date,
            discord_id=interaction.user.id,
        )

        if existing_leave is not None:
            await interaction.response.send_message(
                "❌ 해당 날짜에 이미 등록된 휴무가 있습니다.",
                ephemeral=True,
            )
            return

        evidence = 증빙.url if 증빙 else None

        success, result = create_leave(
            date=target_date,
            discord_id=interaction.user.id,
            leave_type=유형,
            evidence=evidence,
        )

        if not success:
            if result == "미등록":
                message = "❌ 등록된 스터디 멤버가 아닙니다."

            elif result == "주간한도초과":
                message = "❌ 이번 주 휴무 한도를 초과했습니다."

            else:
                message = "❌ 휴무 신청에 실패했습니다."

            await interaction.response.send_message(
                message,
                ephemeral=True,
            )
            return

        if 유형 == "기타":
            await interaction.response.send_message(
                f"🏖️ {target_date} **{유형}** 휴무 신청이 완료되었습니다.\n"
                "현재 상태: **대기**\n"
                "관리자 승인 후 휴무가 확정됩니다."
            )
        else:
            await interaction.response.send_message(
                f"🏖️ {target_date} **{유형}** 휴무 신청이 완료되었습니다.\n"
                "현재 상태: **승인**"
            )

    @bot.tree.command(
        name="휴무관리",
        description="대기 중인 휴무 신청을 확인합니다.",
    )
    async def manage_leave(interaction: discord.Interaction):
        records = get_pending_leaves()

        if not records:
            await interaction.response.send_message(
                "📋 현재 대기 중인 휴무 신청이 없습니다.",
                ephemeral=True,
            )
            return

        result = [
            "📋 **대기 중인 휴무 신청**",
            "",
        ]

        for leave_id, leave_date, name, leave_type, evidence in records:
            result.append(f"`{leave_id}` | {leave_date} | **{name}** | {leave_type}")

        result.append("")
        result.append("`/휴무처리 신청id 결과`로 승인 또는 반려할 수 있습니다.")

        await interaction.response.send_message(
            "\n".join(result),
            ephemeral=True,
        )

    @bot.tree.command(
        name="휴무처리",
        description="휴무 신청을 승인하거나 반려합니다.",
    )
    async def process_leave(
        interaction: discord.Interaction,
        신청id: int,
        결과: Literal["승인", "반려"],
    ):
        success = change_leave_status(
            leave_id=신청id,
            status=결과,
        )

        if not success:
            await interaction.response.send_message(
                "❌ 대기 중인 휴무 신청을 찾을 수 없습니다.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"✅ 휴무 신청 `{신청id}`을(를) **{결과}** 처리했습니다."
        )
