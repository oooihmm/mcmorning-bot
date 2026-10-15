"""현재 발행된 주간 기간 안에서 날짜를 선택하는 휴무 신청·취소 화면."""

import logging
from datetime import date

import discord

from services import attendance as store
from services.rules import EARLY, FULL, LATE, OTHER

log = logging.getLogger(__name__)
WEEKDAYS = "월화수목금토일"


def day_label(day):
    return f"{day:%Y-%m-%d} ({WEEKDAYS[day.weekday()]})"


class PersonalLeaveView(discord.ui.View):
    def __init__(self, guild_id, owner_id):
        super().__init__(timeout=600)
        self.guild_id, self.owner_id = guild_id, owner_id
        self.message = None

    async def interaction_check(self, interaction):
        if (
            interaction.guild_id != self.guild_id
            or interaction.user.id != self.owner_id
        ):
            await interaction.response.send_message(
                "이 화면을 연 본인만 사용할 수 있습니다.", ephemeral=True
            )
            return False
        return True

    async def finish(self, interaction, success, result):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=("✅ " if success else "❌ ") + result, view=self
        )
        self.stop()

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(
                    content="화면이 만료되었습니다. 명령을 다시 실행해주세요.",
                    view=self,
                )
            except discord.HTTPException:
                log.exception("휴무 화면 만료 표시 실패")

    async def on_error(self, interaction, error, item):
        log.error(
            "휴무 화면 처리 실패", exc_info=(type(error), error, error.__traceback__)
        )
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "처리에 실패했습니다. 명령을 다시 실행해주세요.", ephemeral=True
            )


class LeaveDetailsModal(discord.ui.Modal):
    def __init__(self, source, day=None):
        super().__init__(title="휴무 신청", timeout=600)
        self.source, self.day = source, day
        self.choose_date = None
        if day is None:
            self.choose_date = discord.ui.Select(
                placeholder="휴무 날짜를 선택하세요",
                options=[
                    discord.SelectOption(
                        label=day_label(value), value=value.isoformat()
                    )
                    for value in store.available_leave_dates()
                ],
            )
            self.add_item(
                discord.ui.Label(text="휴무 날짜", component=self.choose_date)
            )
        self.leave_type = discord.ui.Select(
            placeholder="휴무 유형을 선택하세요",
            options=[
                discord.SelectOption(label="전일 휴무", value=FULL),
                discord.SelectOption(label="반휴 — 늦게 출근", value=LATE),
                discord.SelectOption(label="반휴 — 일찍 퇴근", value=EARLY),
                discord.SelectOption(label="기타 휴무 (증빙 필수)", value=OTHER),
            ],
        )
        self.evidence = discord.ui.FileUpload(required=False, max_values=1)
        self.add_item(discord.ui.Label(text="휴무 유형", component=self.leave_type))
        self.add_item(
            discord.ui.Label(
                text="증빙 자료",
                description="기타 휴무를 선택한 경우 반드시 첨부해주세요.",
                component=self.evidence,
            )
        )

    async def interaction_check(self, interaction):
        return await self.source.interaction_check(interaction)

    async def on_submit(self, interaction):
        if self.choose_date is not None:
            self.day = date.fromisoformat(self.choose_date.values[0])
        evidence = self.evidence.values[0].url if self.evidence.values else None
        success, result = store.create_leave(
            self.day, self.source.owner_id, self.leave_type.values[0], evidence
        )
        if success and self.source.message:
            for item in self.source.children:
                item.disabled = True
            self.source.stop()
            await interaction.response.edit_message(
                content=f"✅ {day_label(self.day)} 휴무 신청 완료 · {result}",
                view=self.source,
            )
        else:
            await interaction.response.send_message(
                ("✅ " if success else "❌ ") + f"{day_label(self.day)} · {result}",
                ephemeral=True,
            )

    async def on_error(self, interaction, error):
        await self.source.on_error(interaction, error, None)


class LeaveRequestView(PersonalLeaveView):
    def __init__(self, guild_id, owner_id):
        super().__init__(guild_id, owner_id)
        self.day = None
        dates = store.available_leave_dates()
        self.choose_date.options = [
            discord.SelectOption(label=day_label(day), value=day.isoformat())
            for day in dates
        ] or [discord.SelectOption(label="신청 가능한 날짜 없음", value="none")]
        self.choose_date.disabled = not dates
        self.submit.disabled = True

    @discord.ui.select(placeholder="휴무 날짜를 선택하세요", row=0)
    async def choose_date(self, interaction, select):
        self.day = date.fromisoformat(select.values[0])
        for option in select.options:
            option.default = option.value == select.values[0]
        self.submit.disabled = False
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="휴무 신청", style=discord.ButtonStyle.primary, row=1)
    async def submit(self, interaction, button):
        if self.day is None:
            await interaction.response.send_message(
                "날짜를 먼저 선택해주세요.", ephemeral=True
            )
            return
        if self.day not in store.available_leave_dates():
            await interaction.response.send_message(
                "신청 기간이 변경되었거나 마감되었습니다. /휴무신청을 다시 실행해주세요.",
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(LeaveDetailsModal(self, self.day))


class LeaveCancelView(PersonalLeaveView):
    def __init__(self, guild_id, owner_id):
        super().__init__(guild_id, owner_id)
        self.rows = {str(r["id"]): r for r in store.cancellable_leaves(owner_id)}
        self.selected = None
        self.choose_leave.options = [
            discord.SelectOption(
                label=f"{r['date']} · {r['type']}", description=r["status"], value=key
            )
            for key, r in self.rows.items()
        ] or [discord.SelectOption(label="취소 가능한 휴무 없음", value="none")]
        self.choose_leave.disabled = not self.rows
        self.cancel.disabled = True

    @discord.ui.select(placeholder="취소할 항목을 선택하세요", row=0)
    async def choose_leave(self, interaction, select):
        self.selected = self.rows[select.values[0]]
        for option in select.options:
            option.default = option.value == select.values[0]
        self.cancel.disabled = False
        await interaction.response.edit_message(view=self)

    @discord.ui.button(
        label="선택한 휴무 취소", style=discord.ButtonStyle.danger, row=1
    )
    async def cancel(self, interaction, button):
        if self.selected is None:
            await interaction.response.send_message(
                "취소할 휴무를 먼저 선택해주세요.", ephemeral=True
            )
            return
        row = self.selected
        success, result = store.cancel_leave(
            date.fromisoformat(row["date"]),
            self.owner_id,
            expected_requested_at=row["requested_at"],
        )
        await self.finish(interaction, success, f"{row['date']} · {result}")
