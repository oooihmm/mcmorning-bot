"""현재 발행된 주간 기간 안에서 날짜를 선택하는 휴무 신청·취소 화면."""
import logging
from datetime import date
import discord
from services import attendance as store

log = logging.getLogger(__name__)
WEEKDAYS = '월화수목금토일'


def day_label(day):
    return f'{day:%Y-%m-%d} ({WEEKDAYS[day.weekday()]})'


class PersonalLeaveView(discord.ui.View):
    def __init__(self, guild_id, owner_id):
        super().__init__(timeout=600)
        self.guild_id, self.owner_id = guild_id, owner_id
        self.message = None

    async def interaction_check(self, interaction):
        if interaction.guild_id != self.guild_id or interaction.user.id != self.owner_id:
            await interaction.response.send_message('이 화면을 연 본인만 사용할 수 있습니다.', ephemeral=True)
            return False
        return True

    async def finish(self, interaction, success, result):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content=('✅ ' if success else '❌ ') + result, view=self)
        self.stop()

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(content='화면이 만료되었습니다. 명령을 다시 실행해주세요.', view=self)
            except discord.HTTPException:
                log.exception('휴무 화면 만료 표시 실패')

    async def on_error(self, interaction, error, item):
        log.error('휴무 화면 처리 실패',exc_info=(type(error),error,error.__traceback__))
        if not interaction.response.is_done():
            await interaction.response.send_message('처리에 실패했습니다. 명령을 다시 실행해주세요.',ephemeral=True)


class LeaveRequestView(PersonalLeaveView):
    def __init__(self, guild_id, owner_id, leave_type, evidence=None):
        super().__init__(guild_id,owner_id)
        self.leave_type, self.evidence = leave_type,evidence
        self.day = None
        dates = store.available_leave_dates()
        self.choose_date.options = [discord.SelectOption(label=day_label(day),value=day.isoformat()) for day in dates] or [discord.SelectOption(label='신청 가능한 날짜 없음',value='none')]
        self.choose_date.disabled = not dates
        self.submit.disabled = True

    @discord.ui.select(placeholder='휴무 날짜를 선택하세요 (YYYY-MM-DD · 요일)',row=0)
    async def choose_date(self, interaction, select):
        self.day = date.fromisoformat(select.values[0])
        self.submit.disabled = False
        await interaction.response.edit_message(content=f'{day_label(self.day)} · {self.leave_type}\n아래 신청 버튼을 눌러 확정해주세요.',view=self)

    @discord.ui.button(label='휴무 신청',style=discord.ButtonStyle.primary,row=1)
    async def submit(self, interaction, button):
        if self.day is None:
            await interaction.response.send_message('날짜를 먼저 선택해주세요.',ephemeral=True)
            return
        success,result = store.create_leave(self.day,self.owner_id,self.leave_type,self.evidence)
        await self.finish(interaction,success,f'{day_label(self.day)} · {result}')


class LeaveCancelView(PersonalLeaveView):
    def __init__(self,guild_id,owner_id):
        super().__init__(guild_id,owner_id)
        self.rows = {str(r['id']):r for r in store.cancellable_leaves(owner_id)}
        self.selected = None
        self.choose_leave.options = [discord.SelectOption(label=f"{r['date']} · {r['type']}",description=r['status'],value=key) for key,r in self.rows.items()] or [discord.SelectOption(label='취소 가능한 휴무 없음',value='none')]
        self.choose_leave.disabled = not self.rows
        self.cancel.disabled = True

    @discord.ui.select(placeholder='현재 신청 기간의 휴무 중 취소할 항목을 선택하세요',row=0)
    async def choose_leave(self,interaction,select):
        self.selected = self.rows[select.values[0]]
        self.cancel.disabled = False
        await interaction.response.edit_message(content=f"{self.selected['date']} · {self.selected['type']} · {self.selected['status']}\n아래 취소 버튼을 누르면 이 신청이 취소됩니다.",view=self)

    @discord.ui.button(label='선택한 휴무 취소',style=discord.ButtonStyle.danger,row=1)
    async def cancel(self,interaction,button):
        if self.selected is None:
            await interaction.response.send_message('취소할 휴무를 먼저 선택해주세요.',ephemeral=True)
            return
        row = self.selected
        success,result = store.cancel_leave(date.fromisoformat(row['date']),self.owner_id,expected_requested_at=row['requested_at'])
        await self.finish(interaction,success,f"{row['date']} · {result}")
