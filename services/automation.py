"""영속 작업 이력과 Discord 기록 복구를 사용하는 단일 프로세스 스케줄러."""

import asyncio
import io
import logging
import re
from datetime import date, timedelta

import discord
from discord.ext import tasks

from database import connect
from services import attendance as store
from services.wake import wake_title, wake_body
from services.calendar import is_study_day
from services.rules import EARLY, FULL, LATE, OTHER, at, now_kst

log = logging.getLogger(__name__)


def attendance_lines(day):
    lines = [f"📋 {day} 출결 결과 (확인 필요는 자동 벌점 없음)"]
    for row in store.get_attendance(day):
        lines.append(
            f"{row['name']} | 기상: {row['wake_status'] or '-'} | 영상: {row['video_status'] or '-'} | {row['final_status'] or '미판정'} | 사유: {row['final_reason'] or '-'}"
        )
    lines.append(f"📌 {day:%Y-%m} 누적 벌점")
    for row in store.get_penalties(day):
        flag = " — 퇴출 대상" if row["total"] >= 6 and row["status"] == "활성" else ""
        lines.append(f"{row['name']}: {row['total']}점{flag}")
    return lines


class Automation:
    def __init__(self, bot, settings):
        self.bot, self.settings = bot, settings
        self.lock = asyncio.Lock()
        self.connected_since = None
        self.timeline = []

    def reset_voice_baseline(self):
        self.connected_since = now_kst()
        self.timeline = [(self.connected_since, self.current_participants())]

    def disconnected(self):
        self.connected_since = None
        self.timeline = []

    def current_participants(self):
        channel = self.bot.get_channel(self.settings.morning_channel_id)
        if not isinstance(channel, discord.VoiceChannel):
            raise RuntimeError("모닝 채널은 음성 채널이어야 합니다.")
        return {
            member.id
            for member in channel.members
            if not member.bot
            and member.voice
            and (member.voice.self_video or member.voice.self_stream)
        }

    async def voice_changed(self, member, before, after):
        relevant = any(
            channel and channel.id == self.settings.morning_channel_id
            for channel in (before.channel, after.channel)
        )
        if relevant and self.connected_since is not None:
            now = now_kst()
            self.timeline.append((now, self.current_participants()))
            # 이전 상태 하나를 보존하며 최근 3시간 상태만 유지한다.
            cutoff = now - timedelta(hours=3)
            while len(self.timeline) > 1 and self.timeline[1][0] < cutoff:
                self.timeline.pop(0)

    def channel(self, channel_id, kinds):
        channel = self.bot.get_channel(channel_id)
        if not isinstance(channel, kinds) or channel.guild.id != self.settings.guild_id:
            raise RuntimeError(f"채널 유형·서버·접근 권한을 확인해주세요: {channel_id}")
        return channel

    def validate_channels(self):
        self.channel(self.settings.wake_channel_id, discord.ForumChannel)
        self.channel(self.settings.morning_channel_id, discord.VoiceChannel)
        self.channel(self.settings.leave_channel_id, discord.TextChannel)

    async def forum_post(self, channel, title, content, legacy_title=None, post_day=None):
        # Discord 게시 성공 후 DB 저장 전에 종료된 경우 제목으로 복구한다.
        for thread in channel.threads:
            if (thread.name in (title, legacy_title) and thread.owner_id == self.bot.user.id
                    and (post_day is None or thread.created_at.astimezone(at(post_day,0).tzinfo).date()==post_day)):
                return thread
        async for thread in channel.archived_threads(limit=None):
            if (thread.name in (title, legacy_title) and thread.owner_id == self.bot.user.id
                    and (post_day is None or thread.created_at.astimezone(at(post_day,0).tzinfo).date()==post_day)):
                return thread
        result = await channel.create_thread(
            name=title, content=content, allowed_mentions=discord.AllowedMentions.none()
        )
        return result.thread

    async def ensure_wake(self, day):
        async with self.lock:
            return await self._ensure_wake(day)

    async def _ensure_wake(self, day):
        if not is_study_day(day):
            raise ValueError("주말·공휴일에는 기상 게시글을 생성하지 않습니다.")
        thread_id = store.get_thread(day)
        if thread_id:
            return thread_id
        channel = self.channel(self.settings.wake_channel_id, discord.ForumChannel)
        thread = await self.forum_post(
            channel,
            wake_title(day),
            wake_body(day),
            legacy_title=f"☀️ {day} 기상 인증",
            post_day=day,
        )
        store.save_thread(day, thread.id)
        store.create_daily_attendance(day)
        store.mark_job(day, "wake")
        return thread.id

    async def recover_wake(self, day):
        thread_id = store.get_thread(day)
        if thread_id is None:
            store.mark_job(day, "wake_history", "missed", "당일 기상 Thread 없음")
            return
        thread = self.bot.get_channel(thread_id) or await self.bot.fetch_channel(
            thread_id
        )
        async for message in thread.history(
            limit=None, after=at(day, 0), before=at(day, 10, 30), oldest_first=True
        ):
            if not message.author.bot and (
                message.content.strip() or message.attachments
            ):
                store.save_wake_record(
                    day, message.author.id, message.created_at, message.id
                )
        # 정시 게시글이 없었던 날을 무인증 결석으로 확정하지 않는다.
        complete = thread.created_at <= at(day, 6, 1)
        store.mark_job(
            day,
            "wake_history",
            "done" if complete else "missed",
            None if complete else "06:00 게시글 생성 지연 — 관리자 확인 필요",
        )

    async def record_message(self, message):
        if (
            message.author.bot
            or not message.guild
            or message.guild.id != self.settings.guild_id
        ):
            return
        day = message.created_at.astimezone(at(now_kst().date(), 0).tzinfo).date()
        if message.channel.id != store.get_thread(day) or not is_study_day(day):
            return
        if message.content.strip() or message.attachments:
            store.save_wake_record(
                day, message.author.id, message.created_at, message.id
            )

    async def send_once(self, channel, day, key, content):
        with connect() as db:
            saved = db.execute(
                "SELECT message_id FROM sent_messages WHERE date=? AND channel_id=? AND key=?",
                (day, channel.id, key),
            ).fetchone()
        if saved:
            return
        marker = f"[맥집사:{day}:{key}]"
        message = None
        async for candidate in channel.history(limit=None, after=at(day, 0)):
            if candidate.author.id == self.bot.user.id and (
                marker in candidate.content or candidate.content == content
            ):
                message = candidate
                if marker in candidate.content:
                    await candidate.edit(
                        content=content, allowed_mentions=discord.AllowedMentions.none()
                    )
                break
        if message is None:
            message = await channel.send(
                content, allowed_mentions=discord.AllowedMentions.none()
            )
        with connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO sent_messages VALUES (?,?,?,?)",
                (day, channel.id, key, message.id),
            )

    async def clean_legacy_markers(self):
        # 한 주기에 채널 하나씩 정리한다. 봇이 작성한 정확한 표식 줄만 제거한다.
        with connect() as db:
            targets = [
                (date.fromisoformat(r["date"]), r["thread_id"])
                for r in db.execute("SELECT date,thread_id FROM daily_threads")
            ]
        targets.append((date(1970, 1, 1), self.settings.leave_channel_id))
        for day, channel_id in targets:
            key = f"clean_markers_{channel_id}"
            if store.job_status(day, key) == "done":
                continue
            try:
                channel = self.bot.get_channel(
                    channel_id
                ) or await self.bot.fetch_channel(channel_id)
            except discord.NotFound:
                store.mark_job(day, key)
                return
            if channel.guild.id != self.settings.guild_id:
                raise RuntimeError("표식 정리 대상 서버를 확인해주세요.")
            async for message in channel.history(limit=None):
                if message.author.id != self.bot.user.id:
                    continue
                cleaned = re.sub(
                    r"(?m)^\[맥집사:\d{4}-\d{2}-\d{2}:(?:weekly_leave(?:_\d+)?|result_\d+)\]\s*$",
                    "",
                    message.content,
                ).rstrip()
                if cleaned and cleaned != message.content.rstrip():
                    await message.edit(
                        content=cleaned, allowed_mentions=discord.AllowedMentions.none()
                    )
            store.mark_job(day, key)
            return

    def leave_notice_pages(self, saturday):
        monday = saturday + timedelta(days=2)
        friday = monday + timedelta(days=4)
        lines = [
            "## 🌴 휴무 신청",
            "",
            "### 신청 기간",
            f"> **{monday:%m월 %d일} ~ {friday:%m월 %d일}**",
            "",
            "주에 휴무 1회 or 반휴 2회 신청 가능합니다!",
            "",
            "### 휴무 유형",
            "> 전일 / 반휴 (늦게 출근 or 일찍 퇴근) / 기타",
            "",
            "### 신청 방법",
            "- `/휴무신청` — 날짜·유형을 선택하고 휴무를 등록합니다.",
            "- `/휴무취소` — 등록한 휴무를 선택하여 취소합니다.",
            "- `/내휴무` — 휴무 신청 내역과 상태를 확인합니다.",
            "",
            "### 신청 현황",
        ]
        with connect() as db:
            rows = db.execute(
                """SELECT l.date,l.type,l.status,u.name FROM leaves l
                JOIN users u ON u.id=l.user_id WHERE l.date BETWEEN ? AND ?
                AND l.status IN ('승인','대기') ORDER BY l.date,u.name,l.id""",
                (monday, friday),
            ).fetchall()
        names = {
            FULL: "전일 휴무",
            LATE: "반휴 — 늦게 출근",
            EARLY: "반휴 — 일찍 퇴근",
            OTHER: "기타 휴무",
        }
        for offset in range(5):
            day = monday + timedelta(days=offset)
            lines += ["", f"📅 {day:%m/%d} ({'월화수목금'[offset]})"]
            if not is_study_day(day):
                lines.append("공휴일 · 스터디 없음")
                continue
            requests = [r for r in rows if r["date"] == day.isoformat()]
            if not requests:
                lines.append("신청 없음")
            for row in requests:
                name = discord.utils.escape_markdown(row["name"]).replace("\n", " ")[
                    :100
                ]
                lines.append(
                    f"{name} · {names.get(row['type'], row['type'])}"
                    + (" ⏳ 승인 대기" if row["status"] == "대기" else "")
                )
        pages, content = [], ""
        for line in lines:
            if len(content) + len(line) + 1 > 1800:
                pages.append(content.rstrip())
                content = "### 신청 현황 (계속)\n"
            content += line + "\n"
        pages.append(content.rstrip())
        return pages

    async def sync_leave_notice(self, saturday):
        channel = self.channel(self.settings.leave_channel_id, discord.TextChannel)
        pages = self.leave_notice_pages(saturday)
        for index, body in enumerate(pages):
            key = "weekly_leave" if index == 0 else f"weekly_leave_{index}"
            content = body
            with connect() as db:
                saved = db.execute(
                    "SELECT * FROM leave_notices WHERE date=? AND channel_id=? AND page=?",
                    (saturday, channel.id, index),
                ).fetchone()
            if saved and saved["content"] == content:
                continue
            message = None
            if saved:
                try:
                    message = await channel.fetch_message(saved["message_id"])
                except discord.NotFound:
                    pass
            else:
                marker = f"\n[맥집사:{saturday}:{key}]"
                async for candidate in channel.history(
                    limit=None, after=at(saturday, 0)
                ):
                    if (
                        candidate.author.id == self.bot.user.id
                        and marker in candidate.content
                    ):
                        message = candidate
                        break
            if message:
                await message.edit(
                    content=content, allowed_mentions=discord.AllowedMentions.none()
                )
            else:
                message = await channel.send(
                    content, allowed_mentions=discord.AllowedMentions.none()
                )
            with connect() as db:
                db.execute(
                    "INSERT OR REPLACE INTO leave_notices VALUES (?,?,?,?,?)",
                    (saturday, channel.id, index, message.id, content),
                )
        with connect() as db:
            obsolete = db.execute(
                "SELECT page,message_id FROM leave_notices WHERE date=? AND channel_id=? AND page>=?",
                (saturday, channel.id, len(pages)),
            ).fetchall()
        for row in obsolete:
            try:
                message = await channel.fetch_message(row["message_id"])
                await message.delete()
            except discord.NotFound:
                pass
            with connect() as db:
                db.execute(
                    "DELETE FROM leave_notices WHERE date=? AND channel_id=? AND page=?",
                    (saturday, channel.id, row["page"]),
                )

    async def weekly_leave(self, day):
        await self.sync_leave_notice(day)
        store.open_leave_window(day)
        store.mark_job(day, "weekly_leave")

    def capture_slot(self, day, slot, now):
        hour, minute = map(int, slot.split(":"))
        scheduled = at(day, hour, minute)
        if store.job_status(day, "video_" + slot) in ("done", "missed"):
            return
        if now < scheduled:
            return
        states = [state for when, state in self.timeline if when <= scheduled]
        if (
            (now - scheduled).total_seconds() < 60
            and self.connected_since
            and self.connected_since <= scheduled
            and states
        ):
            store.save_video_snapshot(day, slot, states[-1], now)
        else:
            store.mark_job(day, "video_" + slot, "missed", "정시 참여 상태 확인 불가")

    async def finalize(self, day):
        await self.recover_wake(day)
        store.calculate_final_attendance(day)
        store.mark_job(day, "final")

    async def report(self, day):
        thread_id = store.get_thread(day)
        if thread_id is None:
            raise RuntimeError(f'{day} 기상 인증 게시글이 없어 출결을 작성할 수 없습니다.')
        thread = self.bot.get_channel(thread_id) or await self.bot.fetch_channel(thread_id)
        if (not isinstance(thread,discord.Thread) or thread.guild.id != self.settings.guild_id
                or thread.parent_id != self.settings.wake_channel_id):
            raise RuntimeError('당일 기상 인증 게시글의 서버·포럼을 확인해주세요.')
        if thread.archived:
            await thread.edit(archived=False)
        if thread.name != wake_title(day):
            await thread.edit(name=wake_title(day))
        starter = await thread.fetch_message(thread.id)
        if starter.author.id != self.bot.user.id:
            raise RuntimeError('봇이 작성한 기상 인증 게시글만 수정할 수 있습니다.')
        lines = []
        for row in store.get_attendance(day):
            name = discord.utils.escape_markdown(row['name']).replace('\n',' ')
            lines.append(f"{name} | 기상: {row['wake_status'] or '-'} | 영상: {row['video_status'] or '-'} | {row['final_status'] or '미판정'} | 사유: {row['final_reason'] or '-'}")
        details = '\n'.join(lines) or '출결 관리 대상이 없습니다.'
        body = wake_body(day)
        content = body + details
        embeds, attachments = [], []
        # Discord 본문 길이를 넘으면 같은 게시글에 상세 내용을 담는다.
        if len(content)>2000:
            content = body
            if len(details)<=5800:
                chunk = ''
                for line in lines:
                    if len(chunk)+len(line)+1>3500:
                        embeds.append(discord.Embed(description=chunk))
                        chunk = ''
                    chunk += line + '\n'
                if chunk:
                    embeds.append(discord.Embed(description=chunk))
            else:
                content += '전체 출결은 첨부된 출결 결과 파일에서 확인해주세요.'
                attachments.append(discord.File(io.BytesIO(details.encode('utf-8')),filename=f'{day}-출결.txt'))
        await starter.edit(content=content,embeds=embeds,attachments=attachments,
                           allowed_mentions=discord.AllowedMentions.none())
        store.mark_job(day,'report')
        store.mark_job(day,'report_body')

    async def run_step(self, label, action):
        try:
            await action()
        except Exception:
            log.exception("자동화 작업 실패: %s (다음 주기에 재시도)", label)

    async def tick(self, now=None):
        now = now or now_kst()
        day = now.date()
        if not self.bot.is_ready():
            return
        async with self.lock:
            # 토요일 게시 누락은 다음 금요일까지 복구한다.
            saturday = day - timedelta(days=(day.weekday() - 5) % 7)
            if (
                now >= at(saturday, 10)
                and store.job_status(saturday, "weekly_leave") != "done"
            ):
                await self.run_step("weekly_leave", lambda: self.weekly_leave(saturday))
            if store.job_status(saturday, "weekly_leave") == "done":
                await self.run_step(
                    "leave_notice", lambda: self.sync_leave_notice(saturday)
                )
            if is_study_day(day):
                if at(day, 6) <= now < at(day, 10, 30) and not store.get_thread(day):
                    await self.run_step("wake", lambda: self._ensure_wake(day))
                self.capture_slot(day, "08:35", now)
                self.capture_slot(day, "09:35", now)
                if now >= at(day, 10, 30) and store.job_status(day, "final") != "done":
                    await self.run_step("final", lambda: self.finalize(day))
            # 정시 게시글을 만들었던 과거 운영일도 재시작 후 판정/보고를 마친다.
            with connect() as db:
                days = [
                    date.fromisoformat(row[0])
                    for row in db.execute(
                        "SELECT date FROM daily_threads UNION SELECT date FROM attendance WHERE final_status IS NULL"
                    )
                ]
            for target in sorted(set(days + [day])):
                if not is_study_day(target) or now < at(target, 10, 30):
                    continue
                if store.job_status(target, "final") != "done":
                    await self.run_step(
                        f"final:{target}", lambda d=target: self.finalize(d)
                    )
                if (
                    store.job_status(target, "final") == "done"
                    and store.job_status(target, "report_body") != "done"
                ):
                    await self.run_step(
                        f"report:{target}", lambda d=target: self.report(d)
                    )
            await self.run_step("legacy_markers", self.clean_legacy_markers)

    @tasks.loop(seconds=5, reconnect=True)
    async def loop(self):
        try:
            await self.tick()
        except Exception:
            log.exception("스케줄러 주기 실패 (다음 주기에 재시도)")

    @loop.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()
