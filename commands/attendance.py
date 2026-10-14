from datetime import date
from typing import Literal
import discord
from discord import app_commands

from database import connect
from services import attendance as store
from services.automation import attendance_lines
from services.calendar import set_holiday
from services.rules import at, now_kst, timestamp


async def admin_only(interaction):
    if not interaction.guild or not interaction.permissions.manage_guild:
        raise app_commands.CheckFailure('서버 관리 권한이 필요합니다.')
    return True


def admin_command(function):
    function = app_commands.default_permissions(manage_guild=True)(function)
    return app_commands.check(admin_only)(function)


async def reply_lines(interaction, lines):
    await interaction.response.defer(ephemeral=True)
    page = ''
    for line in lines:
        if len(page) + len(line) > 1800:
            await interaction.followup.send(page, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
            page = ''
        page += line[:1700] + '\n'
    await interaction.followup.send(page or '기록이 없습니다.', ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


def setup_attendance(bot):
    @bot.tree.command(name='기상게시글', description='오늘 기상 게시글을 생성하거나 기존 게시글을 확인합니다.')
    @admin_command
    async def wake_post(interaction: discord.Interaction):
        now = now_kst()
        if not at(now.date(), 6) <= now < at(now.date(), 10, 30):
            raise ValueError('기상 게시글은 당일 06:00~10:30 사이에 생성할 수 있습니다.')
        await interaction.response.defer(ephemeral=True)
        thread_id = await bot.automation.ensure_wake(now.date())
        await interaction.followup.send(f'☀️ <#{thread_id}>', ephemeral=True)

    @bot.tree.command(name='휴무신청', description='당일 08:30까지 휴무를 신청합니다.')
    async def request_leave(interaction: discord.Interaction, 날짜: str,
        유형: Literal['종일','반휴(늦게 참여)','반휴(일찍 퇴장)','기타'], 증빙: discord.Attachment | None = None):
        success, result = store.create_leave(date.fromisoformat(날짜), interaction.user.id, 유형,
                                             증빙.url if 증빙 else None)
        await interaction.response.send_message(f"{'✅' if success else '❌'} {result}" +
            (' — 관리자 승인 후 확정됩니다.' if success and result == '대기' else ''), ephemeral=True)

    @bot.tree.command(name='휴무취소', description='당일 08:30까지 자신의 휴무를 취소합니다.')
    async def cancel_leave(interaction: discord.Interaction, 날짜: str):
        success, result = store.cancel_leave(date.fromisoformat(날짜), interaction.user.id)
        await interaction.response.send_message(f"{'✅' if success else '❌'} {result}", ephemeral=True)

    @bot.tree.command(name='내휴무', description='자신의 휴무 신청 내역을 확인합니다.')
    async def my_leave(interaction: discord.Interaction):
        await reply_lines(interaction, [f"{r['date']} | {r['type']} | {r['status']}" for r in store.get_leaves(interaction.user.id)])

    @bot.tree.command(name='휴무관리', description='대기 중인 기타 휴무와 증빙을 확인합니다.')
    @admin_command
    async def manage_leave(interaction: discord.Interaction):
        lines = [f"신청 {r['id']} | {r['date']} | {r['name']} | {r['type']}\n증빙: {r['evidence'] or '없음'}\n신청 시각: {r['requested_at'] or '기존 데이터 — 확인 필요'}" for r in store.get_leaves(pending=True)]
        await reply_lines(interaction, lines + ['/휴무처리 신청id 결과 — 당일 10:00까지 처리 가능'])

    @bot.tree.command(name='휴무처리', description='당일 10:00까지 기타 휴무를 승인·반려합니다.')
    @admin_command
    async def process_leave(interaction: discord.Interaction, 신청id: int, 결과: Literal['승인','반려']):
        success, result = store.change_leave_status(신청id, 결과, interaction.user.id)
        await interaction.response.send_message(f"{'✅' if success else '❌'} {result}", ephemeral=True)

    @bot.tree.command(name='출결확인', description='선택한 날짜의 출결과 해당 월 누적 벌점을 확인합니다.')
    async def check_attendance(interaction: discord.Interaction, 날짜: str):
        await reply_lines(interaction, attendance_lines(date.fromisoformat(날짜)))

    @bot.tree.command(name='출결판정', description='10:30 이후 저장된 정시 기록으로 출결을 재계산합니다.')
    @admin_command
    async def calculate_attendance(interaction: discord.Interaction, 날짜: str):
        target = date.fromisoformat(날짜)
        if now_kst() < at(target, 10, 30):
            raise ValueError('당일 10:30 이후에 판정할 수 있습니다.')
        await interaction.response.defer(ephemeral=True)
        async with bot.automation.lock:
            await bot.automation.finalize(target)
        await interaction.followup.send('✅ 재계산 완료. /출결확인으로 확인해주세요. 정정 기록은 유지됩니다.', ephemeral=True)

    @bot.tree.command(name='출결정정', description='장애·오판정 출결을 사유와 함께 정정합니다.')
    @admin_command
    async def correct_attendance(interaction: discord.Interaction, 날짜: str, 멤버: discord.Member,
                                 결과: Literal['출석','지각','결석','휴무'], 사유: str):
        from services.attendance import correct_attendance as correct
        correct(date.fromisoformat(날짜), 멤버.id, 결과, 사유, interaction.user.id)
        await interaction.response.send_message('✅ 출결·벌점 정정 완료. 사유와 관리자 기록이 보존됩니다.', ephemeral=True)

    @bot.tree.command(name='벌점확인', description='현재 월 벌점과 퇴출 대상을 확인합니다.')
    async def penalties(interaction: discord.Interaction):
        await reply_lines(interaction, [f"{r['name']}: {r['total']}점" +
            (' — 퇴출 대상' if r['total'] >= 6 and r['status'] == '활성' else '') for r in store.get_penalties(now_kst().date())])

    @bot.tree.command(name='휴일설정', description='임시공휴일 추가 또는 평일 공휴일 판정을 수정합니다.')
    @admin_command
    async def holiday(interaction: discord.Interaction, 날짜: str, 설정: Literal['휴일','운영일','자동'], 사유: str):
        target = date.fromisoformat(날짜)
        if now_kst() >= at(target, 6):
            raise ValueError('휴일 변경은 해당 날짜 06:00 전에 해주세요. 지난 출결은 /출결정정을 사용해주세요.')
        set_holiday(target, {'휴일': True, '운영일': False, '자동': None}[설정], 사유)
        await interaction.response.send_message(f'✅ {target}: {설정} (주말은 항상 제외)', ephemeral=True)
