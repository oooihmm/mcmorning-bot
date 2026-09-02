import os

from dotenv import load_dotenv

load_dotenv()

import discord
from discord.ext import commands

from commands.attendance import setup_attendance
from commands.wake import setup_wake

TOKEN = os.getenv("DISCORD_TOKEN")


intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
)


@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"맥집사 등장! 로그인 계정: {bot.user}")


setup_attendance(bot)
setup_wake(bot)


bot.run(TOKEN)
