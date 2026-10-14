from types import SimpleNamespace
import unittest
import discord
from bot import MorningBot
from commands.attendance import admin_only
from config import Settings


class CommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_management_permission_enforced_at_runtime(self):
        interaction = SimpleNamespace(guild=object(), permissions=SimpleNamespace(manage_guild=False))
        with self.assertRaises(discord.app_commands.CheckFailure):
            await admin_only(interaction)
        interaction.permissions.manage_guild = True
        self.assertTrue(await admin_only(interaction))

    async def test_dm_rejected(self):
        with self.assertRaises(discord.app_commands.CheckFailure):
            await admin_only(SimpleNamespace(guild=None,permissions=SimpleNamespace(manage_guild=True)))

    async def test_bot_commands_scoped_to_configured_guild(self):
        bot = MorningBot(Settings('unused',1,2,3,4))
        self.assertTrue(await bot.check_guild(SimpleNamespace(guild_id=1)))
        with self.assertRaises(discord.app_commands.CheckFailure):
            await bot.check_guild(SimpleNamespace(guild_id=2))
        with self.assertRaises(discord.app_commands.CheckFailure):
            await bot.check_guild(SimpleNamespace(guild_id=None))
        guild=discord.Object(id=1)
        bot.tree.copy_global_to(guild=guild)
        bot.tree.clear_commands(guild=None)
        self.assertEqual(len(bot.tree.get_commands(guild=guild)),11)
        self.assertEqual(len(bot.tree.get_commands()),0)
        admin_names = {'기상게시글','휴무관리','출결판정','출결정정','멤버등록','멤버상태변경'}
        for command in bot.tree.get_commands(guild=guild):
            if command.name in admin_names:
                self.assertTrue(command.checks,command.name)
                self.assertTrue(command.default_permissions.manage_guild,command.name)
