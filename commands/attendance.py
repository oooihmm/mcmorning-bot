from datetime import date
from typing import Literal
import discord
from discord import app_commands
from commands.leave_management import LeaveManagementView
from commands.leave_self_service import PersonalLeaveView, LeaveDetailsModal, LeaveCancelView

from database import connect
from services import attendance as store
from services.automation import attendance_lines
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

    @bot.tree.command(name='휴무신청', description='현재 주간 신청 기간에서 날짜를 선택해 휴무를 신청합니다.')
    async def request_leave(interaction: discord.Interaction):
        if not store.available_leave_dates():
            await interaction.response.send_message('현재 주간 안내 기간에 신청 가능한 날짜가 없습니다.', ephemeral=True)
            return
        source = PersonalLeaveView(interaction.guild_id, interaction.user.id)
        await interaction.response.send_modal(LeaveDetailsModal(source))

    @bot.tree.command(name='휴무취소', description='현재 주간 신청 기간의 내 휴무를 선택해 취소합니다.')
    async def cancel_leave(interaction: discord.Interaction):
        view = LeaveCancelView(interaction.guild_id, interaction.user.id)
        await interaction.response.send_message('취소할 휴무를 선택해주세요.' if view.rows else '현재 주간 신청 기간에 취소 가능한 휴무가 없습니다.', view=view, ephemeral=True)
        view.message = await interaction.original_response()

    @bot.tree.command(name='내휴무', description='최신 주간 안내 기간의 내 휴무를 확인합니다.')
    async def my_leave(interaction: discord.Interaction):
        now = now_kst()
        window = store.current_leave_window(now)
        if window is None:
            await interaction.response.send_message('아직 주간 휴무 안내가 올라오지 않았습니다.', ephemeral=True)
            return
        rows = store.current_leaves(interaction.user.id, now)
        await reply_lines(interaction, [f'🏖️ 내 휴무 · {window[0]} ~ {window[1]}'] +
            ([f"{r['date']} | {r['type']} | {r['status']}" for r in rows] or ['해당 기간에 신청한 휴무가 없습니다.']))

    @bot.tree.command(name='휴무관리', description='증빙을 확인하고 버튼으로 휴무를 승인·반려합니다.')
    @admin_command
    async def manage_leave(interaction: discord.Interaction):
        view = LeaveManagementView(interaction.guild_id, interaction.user.id)
        await interaction.response.send_message(embed=view.render(), view=view, ephemeral=True,
                                                allowed_mentions=discord.AllowedMentions.none())
        view.message = await interaction.original_response()

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
