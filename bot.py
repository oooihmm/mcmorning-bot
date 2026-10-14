import logging
import os
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / '.env')

import discord
from discord.ext import commands
from commands.attendance import setup_attendance
from commands.member import setup_member
from config import Settings
from database import create_tables
from services.automation import Automation

log = logging.getLogger(__name__)


class MorningBot(commands.Bot):
    def __init__(self, settings):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.voice_states = True
        super().__init__(command_prefix='!', intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.settings = settings
        self.automation = Automation(self, settings)
        setup_attendance(self)
        setup_member(self)
        self.tree.interaction_check = self.check_guild
        self.tree.error(self.command_error)

    async def check_guild(self, interaction):
        if interaction.guild_id != self.settings.guild_id:
            raise discord.app_commands.CheckFailure('설정된 스터디 서버에서만 사용할 수 있습니다.')
        return True

    async def command_error(self, interaction, error):
        original = getattr(error, 'original', error)
        if isinstance(original, (ValueError, discord.app_commands.CheckFailure)):
            message = str(original)
        else:
            log.error('명령 실패', exc_info=(type(original), original, original.__traceback__))
            message = '처리에 실패했습니다. 관리자에게 로그 확인을 요청해주세요.'
        if interaction.response.is_done():
            await interaction.followup.send('❌ ' + message, ephemeral=True)
        else:
            await interaction.response.send_message('❌ ' + message, ephemeral=True)

    async def setup_hook(self):
        create_tables()
        # 기존 전역 명령은 제거하고 지정된 스터디 서버에만 등록한다.
        guild = discord.Object(id=self.settings.guild_id)
        self.tree.copy_global_to(guild=guild)
        self.tree.clear_commands(guild=None)
        await self.tree.sync(guild=guild)
        await self.tree.sync()
        self.automation.loop.start()

    async def on_ready(self):
        try:
            self.automation.validate_channels()
            self.automation.reset_voice_baseline()
        except Exception:
            log.exception('채널 설정 오류 — 실행을 중단합니다.')
            await self.close()
            return
        log.info('맥집사 로그인: %s', self.user)

    async def on_resumed(self):
        self.automation.reset_voice_baseline()

    async def on_disconnect(self):
        self.automation.disconnected()

    async def on_voice_state_update(self, member, before, after):
        await self.automation.voice_changed(member, before, after)

    async def on_message(self, message):
        try:
            await self.automation.record_message(message)
        except Exception:
            log.exception('기상 인증 저장 실패 — 최종 판정 전 기록 복구 예정')
        await self.process_commands(message)

    async def close(self):
        self.automation.loop.cancel()
        await super().close()


def main():
    import fcntl
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
    settings = Settings.from_env()
    # 로컬/서버에서 같은 봇 프로세스를 두 번 실행하지 않는다.
    lock_path = Path(os.getenv('BOT_LOCK_PATH', str(Path(__file__).with_name('.bot.lock'))))
    with lock_path.open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError('맥집사가 이미 실행 중입니다.') from error
        MorningBot(settings).run(settings.token)


if __name__ == '__main__':
    main()
