import os

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()

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


bot.run(TOKEN)