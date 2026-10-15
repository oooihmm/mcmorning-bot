"""관리자 전용 휴무 검토 화면. 신청 ID 입력 없이 증빙 확인과 처리를 제공한다."""

import asyncio
import logging
from datetime import date

import discord

from services import attendance as store
from services.rules import at, now_kst

log = logging.getLogger(__name__)


class LeaveManagementView(discord.ui.View):
    def __init__(self, guild_id, owner_id):
        super().__init__(timeout=600)
        self.guild_id = guild_id
        self.owner_id = owner_id
        self.rows = []
        self.index = 0
        self.lock = asyncio.Lock()
        self.message = None
        self.refresh()

    def refresh(self):
        self.rows = store.get_leaves(pending=True)
        self.index = min(self.index, max(0, len(self.rows) - 1))

    def render(self):
        self.previous.disabled = self.index == 0
        self.next.disabled = self.index >= len(self.rows) - 1
        if not self.rows:
            self.approve.disabled = self.reject.disabled = True
            return discord.Embed(
                title="🏖️ 휴무 관리",
                description="대기 중인 휴무 신청이 없습니다.",
                color=discord.Color.green(),
            )
        row = self.rows[self.index]
        expired = now_kst() >= at(date.fromisoformat(row["date"]), 10, 1)
        unknown = not row["requested_at"]
        self.approve.disabled = self.reject.disabled = expired or unknown
        self.approve.custom_id = f"leave:approve:{row['id']}"
        self.reject.custom_id = f"leave:reject:{row['id']}"
        embed = discord.Embed(title="🏖️ 휴무 승인 대기", color=discord.Color.orange())
        embed.add_field(name="신청자", value=row["name"], inline=True)
        embed.add_field(name="휴무 날짜", value=row["date"], inline=True)
        embed.add_field(name="유형", value=row["type"], inline=True)
        embed.add_field(
            name="증빙 자료",
            value=f"[첨부파일 열기]({row['evidence']})"
            if row["evidence"]
            else "증빙 없음",
            inline=False,
        )
        embed.add_field(
            name="신청 시각 (한국 시간)",
            value=row["requested_at"] or "기존 기록 — 시각 확인 필요",
            inline=False,
        )
        embed.add_field(
            name="처리 안내",
            value="승인 마감이 지났습니다."
            if expired
            else "신청 시각을 확인할 수 없어 처리가 제한됩니다."
            if unknown
            else "휴무일 10:00까지 처리할 수 있습니다.",
            inline=False,
        )
        embed.set_footer(
            text=f"{self.index + 1} / {len(self.rows)}건 · 화면은 10분 동안 사용 가능 · 만료 시 /휴무관리 재실행"
        )
        return embed

    async def interaction_check(self, interaction):
        if (
            interaction.guild_id != self.guild_id
            or interaction.user.id != self.owner_id
            or not interaction.permissions.manage_guild
        ):
            await interaction.response.send_message(
                "이 화면을 연 관리자만 사용할 수 있습니다. /휴무관리를 다시 실행해주세요.",
                ephemeral=True,
            )
            return False
        return True

    async def move(self, interaction, offset):
        async with self.lock:
            self.refresh()
            self.index = max(0, min(self.index + offset, len(self.rows) - 1))
            await interaction.response.edit_message(
                content=None, embed=self.render(), view=self
            )

    async def process(self, interaction, result):
        # 버튼에 신청 ID를 묶어 두어 오래된 클릭으로 다음 신청을 처리하지 않는다.
        leave_id = int(interaction.data["custom_id"].rsplit(":", 1)[1])
        async with self.lock:
            success, message = store.change_leave_status(
                leave_id, result, interaction.user.id
            )
            self.refresh()
            await interaction.response.edit_message(
                content=f"✅ {result} 처리했습니다." if success else "❌ " + message,
                embed=self.render(),
                view=self,
                allowed_mentions=discord.AllowedMentions.none(),
            )

    @discord.ui.button(label="승인", style=discord.ButtonStyle.success, row=0)
    async def approve(self, interaction, button):
        await self.process(interaction, "승인")

    @discord.ui.button(label="반려", style=discord.ButtonStyle.danger, row=0)
    async def reject(self, interaction, button):
        await self.process(interaction, "반려")

    @discord.ui.button(label="이전", style=discord.ButtonStyle.secondary, row=1)
    async def previous(self, interaction, button):
        await self.move(interaction, -1)

    @discord.ui.button(label="다음", style=discord.ButtonStyle.secondary, row=1)
    async def next(self, interaction, button):
        await self.move(interaction, 1)

    @discord.ui.button(label="새로고침", style=discord.ButtonStyle.secondary, row=1)
    async def reload(self, interaction, button):
        await self.move(interaction, 0)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(
                    content="화면이 만료되었습니다. /휴무관리를 다시 실행해주세요.",
                    view=self,
                )
            except discord.HTTPException:
                log.exception("휴무 관리 화면 만료 표시 실패")

    async def on_error(self, interaction, error, item):
        log.error(
            "휴무 관리 버튼 처리 실패",
            exc_info=(type(error), error, error.__traceback__),
        )
        text = "처리에 실패했습니다. /휴무관리를 다시 실행해주세요."
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=True)
        else:
            await interaction.response.send_message(text, ephemeral=True)
