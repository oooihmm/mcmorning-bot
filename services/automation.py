"""영속 작업 이력과 Discord 기록 복구를 사용하는 단일 프로세스 스케줄러."""
import asyncio
import logging
from datetime import date, datetime, timedelta

import discord
from discord.ext import tasks

from database import connect
from services import attendance as store
from services.calendar import is_study_day
from services.rules import at, now_kst

log = logging.getLogger(__name__)


def attendance_lines(day):
    lines = [f'📋 {day} 출결 결과 (확인 필요는 자동 벌점 없음)']
    for row in store.get_attendance(day):
        lines.append(f"{row['name']} | 기상: {row['wake_status'] or '-'} | 영상: {row['video_status'] or '-'} | {row['final_status'] or '미판정'} | 사유: {row['final_reason'] or '-'}")
    lines.append(f'📌 {day:%Y-%m} 누적 벌점')
    for row in store.get_penalties(day):
        flag = ' — 퇴출 대상' if row['total'] >= 6 and row['status'] == '활성' else ''
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
            raise RuntimeError('모닝 채널은 음성 채널이어야 합니다.')
        return {member.id for member in channel.members if not member.bot and member.voice
                and (member.voice.self_video or member.voice.self_stream)}

    async def voice_changed(self, member, before, after):
        relevant = any(channel and channel.id == self.settings.morning_channel_id for channel in (before.channel, after.channel))
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
            raise RuntimeError(f'채널 유형·서버·접근 권한을 확인해주세요: {channel_id}')
        return channel

    def validate_channels(self):
        self.channel(self.settings.wake_channel_id, discord.ForumChannel)
        self.channel(self.settings.morning_channel_id, discord.VoiceChannel)
        self.channel(self.settings.leave_channel_id, (discord.TextChannel, discord.ForumChannel))

    async def forum_post(self, channel, title, content):
        # Discord 게시 성공 후 DB 저장 전에 종료된 경우 제목으로 복구한다.
        for thread in channel.threads:
            if thread.name == title and thread.owner_id == self.bot.user.id:
                return thread
        async for thread in channel.archived_threads(limit=None):
            if thread.name == title and thread.owner_id == self.bot.user.id:
                return thread
        result = await channel.create_thread(name=title, content=content,
                                             allowed_mentions=discord.AllowedMentions.none())
        return result.thread

    async def ensure_wake(self, day):
        async with self.lock:
            return await self._ensure_wake(day)

    async def _ensure_wake(self, day):
        if not is_study_day(day):
            raise ValueError('주말·공휴일에는 기상 게시글을 생성하지 않습니다.')
        thread_id = store.get_thread(day)
        if thread_id:
            return thread_id
        channel = self.channel(self.settings.wake_channel_id, discord.ForumChannel)
        thread = await self.forum_post(channel, f'☀️ {day} 기상 인증',
            '이 Thread에 첫 메시지를 작성해주세요.\n일반: 08:00까지 기상 / 08:30까지 지각\n늦게 출근 반휴: 09:30 이전 인증 + 09:35 카메라 또는 화면 공유 참여')
        store.save_thread(day, thread.id)
        store.create_daily_attendance(day)
        store.mark_job(day, 'wake')
        return thread.id

    async def recover_wake(self, day):
        thread_id = store.get_thread(day)
        if thread_id is None:
            store.mark_job(day, 'wake_history', 'missed', '당일 기상 Thread 없음')
            return
        thread = self.bot.get_channel(thread_id) or await self.bot.fetch_channel(thread_id)
        async for message in thread.history(limit=None, after=at(day, 0), before=at(day, 10, 30), oldest_first=True):
            if not message.author.bot and (message.content.strip() or message.attachments):
                store.save_wake_record(day, message.author.id, message.created_at, message.id)
        # 정시 게시글이 없었던 날을 무인증 결석으로 확정하지 않는다.
        complete = thread.created_at <= at(day, 6, 1)
        store.mark_job(day, 'wake_history', 'done' if complete else 'missed',
                       None if complete else '06:00 게시글 생성 지연 — 관리자 확인 필요')

    async def record_message(self, message):
        if message.author.bot or not message.guild or message.guild.id != self.settings.guild_id:
            return
        day = message.created_at.astimezone(at(now_kst().date(), 0).tzinfo).date()
        if message.channel.id != store.get_thread(day) or not is_study_day(day):
            return
        if message.content.strip() or message.attachments:
            store.save_wake_record(day, message.author.id, message.created_at, message.id)

    async def send_once(self, channel, day, key, content):
        marker = f'[맥집사:{day}:{key}]'
        async for message in channel.history(limit=None, after=at(day, 0)):
            if message.author.id == self.bot.user.id and marker in message.content:
                return
        await channel.send(content + '\n' + marker, allowed_mentions=discord.AllowedMentions.none())

    async def weekly_leave(self, day):
        monday = day + timedelta(days=2)
        weekdays = [monday + timedelta(days=i) for i in range(5)]
        lines = [f'🏖️ {monday} ~ {weekdays[-1]} 휴무 신청',
                 '전일 1회 또는 반휴 2회 / 기타: 증빙 + 관리자 승인',
                 '/휴무신청, /휴무취소, /내휴무 명령을 사용해주세요.',
                 '신청·취소: 당일 08:30까지 / 기타 승인: 당일 10:00까지']
        lines += [f"{d} ({'신청 가능' if is_study_day(d) else '공휴일 — 스터디 없음'})" for d in weekdays]
        channel = self.channel(self.settings.leave_channel_id, (discord.TextChannel, discord.ForumChannel))
        if isinstance(channel, discord.ForumChannel):
            await self.forum_post(channel, f'🏖️ {monday} 주간 휴무 신청', '\n'.join(lines))
        else:
            await self.send_once(channel, day, 'weekly_leave', '\n'.join(lines))
        store.mark_job(day, 'weekly_leave')

    def capture_slot(self, day, slot, now):
        hour, minute = map(int, slot.split(':'))
        scheduled = at(day, hour, minute)
        if store.job_status(day, 'video_' + slot) in ('done', 'missed'):
            return
        if now < scheduled:
            return
        states = [state for when, state in self.timeline if when <= scheduled]
        if (now - scheduled).total_seconds() < 60 and self.connected_since and self.connected_since <= scheduled and states:
            store.save_video_snapshot(day, slot, states[-1], now)
        else:
            store.mark_job(day, 'video_' + slot, 'missed', '정시 참여 상태 확인 불가')

    async def finalize(self, day):
        await self.recover_wake(day)
        store.calculate_final_attendance(day)
        store.mark_job(day, 'final')

    async def report(self, day):
        thread_id = store.get_thread(day)
        if thread_id is None:
            raise RuntimeError(f'{day} 기상 인증 게시글이 없어 출결 댓글을 작성할 수 없습니다.')
        channel = self.bot.get_channel(thread_id) or await self.bot.fetch_channel(thread_id)
        if (not isinstance(channel, discord.Thread)
                or channel.guild.id != self.settings.guild_id
                or channel.parent_id != self.settings.wake_channel_id):
            raise RuntimeError('당일 기상 인증 게시글의 서버·포럼을 확인해주세요.')
        if channel.archived:
            await channel.edit(archived=False)
        pages, current = [], ''
        for line in attendance_lines(day):
            if len(current) + len(line) > 1700:
                pages.append(current)
                current = ''
            current += line[:1500] + '\n'
        pages.append(current)
        for index, content in enumerate(pages):
            await self.send_once(channel, day, f'result_{index}', content)
        store.mark_job(day, 'report')

    async def run_step(self, label, action):
        try:
            await action()
        except Exception:
            log.exception('자동화 작업 실패: %s (다음 주기에 재시도)', label)

    async def tick(self, now=None):
        now = now or now_kst()
        day = now.date()
        if not self.bot.is_ready():
            return
        async with self.lock:
            # 토요일 게시 누락은 다음 금요일까지 복구한다.
            saturday = day - timedelta(days=(day.weekday() - 5) % 7)
            if now >= at(saturday, 10) and store.job_status(saturday, 'weekly_leave') != 'done':
                await self.run_step('weekly_leave', lambda: self.weekly_leave(saturday))
            if is_study_day(day):
                if at(day, 6) <= now < at(day, 10, 30) and not store.get_thread(day):
                    await self.run_step('wake', lambda: self._ensure_wake(day))
                self.capture_slot(day, '08:35', now)
                self.capture_slot(day, '09:35', now)
                if now >= at(day, 10, 30) and store.job_status(day, 'final') != 'done':
                    await self.run_step('final', lambda: self.finalize(day))
            # 정시 게시글을 만들었던 과거 운영일도 재시작 후 판정/보고를 마친다.
            with connect() as db:
                days = [date.fromisoformat(row[0]) for row in db.execute(
                    "SELECT date FROM daily_threads UNION SELECT date FROM attendance WHERE final_status IS NULL")]
            for target in sorted(set(days + [day])):
                if not is_study_day(target) or now < at(target, 10, 30):
                    continue
                if store.job_status(target, 'final') != 'done':
                    await self.run_step(f'final:{target}', lambda d=target: self.finalize(d))
                if store.job_status(target, 'final') == 'done' and store.job_status(target, 'report') != 'done':
                    await self.run_step(f'report:{target}', lambda d=target: self.report(d))

    @tasks.loop(seconds=5, reconnect=True)
    async def loop(self):
        try:
            await self.tick()
        except Exception:
            log.exception('스케줄러 주기 실패 (다음 주기에 재시도)')

    @loop.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()
