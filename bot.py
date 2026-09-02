import os

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
WAKE_CHANNEL_ID = int(os.getenv("CHANNEL_ID"))

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"맥집사 등장! 로그인 계정: {bot.user}")


@bot.tree.command(name="출석", description="오늘 스터디 출석을 체크합니다.")
async def attendance(interaction: discord.Interaction):
    await interaction.response.send_message(
        f"☕ {interaction.user.mention}님 출석 완료!"
    )

@bot.tree.command(
    name="기상게시글",
    description="기상 인증 게시글을 생성합니다."
)
async def create_wake_post(interaction: discord.Interaction):

    channel = bot.get_channel(WAKE_CHANNEL_ID)

    if channel is None:
        await interaction.response.send_message(
            "❌ 기상인증 채널을 찾을 수 없습니다.",
            ephemeral=True
        )
        return

    thread = await channel.create_thread(
        name="☀️ 오늘의 기상 인증",
        content="8:00까지 이 게시글에 답글을 달아주세요!"
    )

    await interaction.response.send_message(
        f"☀️ 기상 인증 게시글을 생성했습니다!\n"
        f"{thread.thread.jump_url}",
        ephemeral=True
    )

bot.run(TOKEN)