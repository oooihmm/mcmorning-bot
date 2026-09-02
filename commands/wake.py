import os
from datetime import time
from zoneinfo import ZoneInfo

import discord

from database import save_wake_record

WAKE_CHANNEL_ID = int(os.getenv("CHANNEL_ID"))

wake_thread_id = None


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
