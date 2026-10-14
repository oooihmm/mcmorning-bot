import asyncio
from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import sqlite3
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import discord

import database
from services import attendance as store
from services.calendar import is_study_day, set_holiday
from services.rules import KST, FULL, LATE, EARLY, OTHER, at, judge, wake_status
from services.automation import Automation

DAY = date(2026, 10, 14)


class RulesTests(unittest.TestCase):
    def test_wake_boundaries(self):
        for clock, expected in [('08:00:59.999999', '기상'), ('08:01:00','지각'),
                                ('08:30:59.999999','지각'), ('08:31:00','결석')]:
            with self.subTest(clock=clock):
                self.assertEqual(wake_status(datetime.fromisoformat(f'{DAY}T{clock}').replace(tzinfo=KST)), expected)

    def test_late_wake_boundary(self):
        self.assertEqual(wake_status(at(DAY,9,30)-timedelta(microseconds=1), True), '기상')
        self.assertEqual(wake_status(at(DAY,9,30), True), '결석')

    def test_matrix(self):
        for wake, video, leave, expected in [
            (at(DAY,8),'참여',None,('출석',0)),
            (at(DAY,8,15),'참여',None,('지각',1)),
            (None,'참여',None,('결석',2)),
            (at(DAY,7),'미참여',None,('결석',2)),
            (None,None,FULL,('휴무',0)),
            (None,None,OTHER,('휴무',0)),
            (at(DAY,9,29),'참여',LATE,('출석',0)),
            (at(DAY,9,30),'참여',LATE,('결석',2)),
            (at(DAY,7),None,None,('확인 필요',0)),
        ]:
            with self.subTest(wake=wake,video=video,leave=leave):
                self.assertEqual(judge(wake,video,leave), expected)
        self.assertEqual(judge(None,'참여',wake_complete=False), ('확인 필요',0))


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.old_path = database.DB_NAME
        database.DB_NAME = str(Path(self.tmp.name)/'test.db')
        database.create_tables()
        store.open_leave_window(DAY-timedelta(days=(DAY.weekday()-5)%7),at(DAY-timedelta(days=(DAY.weekday()-5)%7),10))
        with database.connect() as db:
            db.execute("INSERT INTO users(discord_id,name) VALUES (123,'멤버')")
        self.request_time = at(DAY-timedelta(days=1),12)

    def tearDown(self):
        database.DB_NAME = self.old_path
        self.tmp.cleanup()

    def leave(self, kind=FULL, day=DAY, now=None):
        return store.create_leave(day,123,kind,'evidence' if kind == OTHER else None, now or self.request_time)

    def finalize(self, day=DAY):
        store.calculate_final_attendance(day, at(day,10,30))
        return store.get_attendance(day)[0]['final_status']

    def captured(self, day=DAY, normal=True, late=False):
        store.save_video_snapshot(day,'08:35',{123} if normal else set(),at(day,8,35))
        store.save_video_snapshot(day,'09:35',{123} if late else set(),at(day,9,35))
        store.mark_job(day,'wake_history')

    def test_no_published_window_blocks_request(self):
        with database.connect() as db:
            db.execute('DELETE FROM leave_windows')
        self.assertFalse(self.leave()[0])

    def test_only_latest_published_window_can_be_used(self):
        future = date(2026,10,19)
        self.assertFalse(self.leave(FULL,future)[0])
        self.leave()
        published = at(date(2026,10,17),10)
        store.open_leave_window(date(2026,10,17),published)
        self.assertEqual(store.current_leave_window(published),(future,date(2026,10,23)))
        self.assertTrue(store.create_leave(future,123,FULL,now=published)[0])
        self.assertFalse(store.cancel_leave(DAY,123,published)[0])
        self.assertFalse(store.create_leave(date(2026,10,26),123,FULL,now=published)[0])

    def test_available_dates_exclude_holidays_and_cutoff(self):
        set_holiday(DAY+timedelta(days=1),True,'휴일')
        self.assertEqual(store.available_leave_dates(at(DAY,8,30)),[DAY,DAY+timedelta(days=2)])
        self.assertEqual(store.available_leave_dates(at(DAY,8,31)),[DAY+timedelta(days=2)])

    def test_stale_cancel_cannot_cancel_reapplied_request(self):
        self.leave()
        old = store.get_leave(DAY,123)['requested_at']
        store.cancel_leave(DAY,123,self.request_time)
        self.leave(LATE,now=self.request_time+timedelta(minutes=1))
        self.assertFalse(store.cancel_leave(DAY,123,self.request_time+timedelta(minutes=2),expected_requested_at=old)[0])
        self.assertEqual(store.get_leave(DAY,123)['type'],LATE)

    def test_current_leaves_scoped_to_owner_and_published_period(self):
        with database.connect() as db:
            db.execute("INSERT INTO users(discord_id,name) VALUES (456,'다른 멤버')")
            for day,status in [(date(2026,10,5),'승인'),(date(2026,10,12),'취소'),(date(2026,10,13),'반려'),(DAY,'대기'),(date(2026,10,15),'승인'),(date(2026,10,19),'승인')]:
                db.execute('INSERT INTO leaves(date,user_id,type,status) VALUES (?,1,?,?)',(day,OTHER,status))
            db.execute("INSERT INTO leaves(date,user_id,type,status) VALUES (?,2,'기타','승인')",(DAY,))
        rows=store.current_leaves(123,at(DAY,9))
        self.assertEqual([r['status'] for r in rows],['취소','반려','대기','승인'])
        store.open_leave_window(date(2026,10,17),at(date(2026,10,17),10))
        rows=store.current_leaves(123,at(date(2026,10,17),10))
        self.assertEqual([r['date'] for r in rows],['2026-10-19'])

    def test_current_leaves_hidden_until_weekly_post_exists(self):
        self.leave()
        with database.connect() as db:
            db.execute('DELETE FROM leave_windows')
        self.assertEqual(store.current_leaves(123,self.request_time),[])

    def test_full_leave_excluded(self):
        self.assertTrue(self.leave()[0])
        self.assertEqual(self.finalize(), '휴무')
        self.assertEqual(store.get_penalties(DAY)[0]['total'],0)

    def test_weekly_exclusive_limit(self):
        self.assertTrue(self.leave()[0])
        self.assertFalse(self.leave(EARLY,DAY+timedelta(days=1))[0])
        self.assertTrue(store.cancel_leave(DAY,123,self.request_time)[0])
        self.assertTrue(self.leave(EARLY)[0])
        self.assertTrue(self.leave(LATE,DAY+timedelta(days=1))[0])
        self.assertFalse(self.leave(EARLY,DAY+timedelta(days=2))[0])
        self.assertFalse(self.leave(FULL,DAY+timedelta(days=2))[0])
        self.assertTrue(self.leave(OTHER,DAY+timedelta(days=2))[0])

    def test_request_boundary(self):
        self.assertTrue(self.leave(now=at(DAY,8,31)-timedelta(microseconds=1))[0])
        self.assertFalse(store.cancel_leave(DAY,123,at(DAY,8,31))[0])
        self.assertFalse(self.leave(FULL,DAY+timedelta(days=1),at(DAY+timedelta(days=1),8,31))[0])

    def test_cancel_and_reapply(self):
        self.leave()
        self.assertTrue(store.cancel_leave(DAY,123,self.request_time)[0])
        self.assertIsNone(store.get_leave(DAY,123))
        self.assertTrue(self.leave(LATE)[0])
        with database.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM leave_events').fetchone()[0],3)

    def test_approval_boundary(self):
        self.leave(OTHER)
        row = store.get_leave(DAY,123)
        self.assertTrue(store.change_leave_status(row['id'],'승인',999,at(DAY,10,1)-timedelta(microseconds=1))[0])
        self.assertEqual(self.finalize(),'휴무')

    def test_late_approval_and_pending_are_not_leave(self):
        self.leave(OTHER)
        row = store.get_leave(DAY,123)
        self.assertFalse(store.change_leave_status(row['id'],'승인',999,at(DAY,10,1))[0])
        self.captured()
        self.assertEqual(self.finalize(),'결석')
        self.assertEqual(store.get_penalties(DAY)[0]['total'],2)

    def test_evidence_required_in_service(self):
        self.assertFalse(store.create_leave(DAY,123,OTHER,now=self.request_time)[0])

    def test_first_message_kept_even_history_recovery_out_of_order(self):
        store.save_wake_record(DAY,123,at(DAY,8,20),20)
        store.save_wake_record(DAY,123,at(DAY,7),10)
        store.save_wake_record(DAY,123,at(DAY,9),30)
        self.captured()
        self.assertEqual(self.finalize(),'출석')
        with database.connect() as db:
            self.assertEqual(db.execute('SELECT wake_message_id FROM attendance').fetchone()[0],10)

    def test_late_leave_uses_only_0935(self):
        self.leave(LATE)
        store.save_wake_record(DAY,123,at(DAY,9,29),1)
        self.captured(normal=False,late=True)
        self.assertEqual(self.finalize(),'출석')

    def test_normal_and_early_cannot_use_0935(self):
        for leave in [None, EARLY]:
            with self.subTest(leave=leave):
                if leave:
                    self.leave(leave)
                store.save_wake_record(DAY,123,at(DAY,7),1)
                self.captured(normal=False,late=True)
                self.assertEqual(self.finalize(),'결석')

    def test_missing_video_no_penalty(self):
        store.save_wake_record(DAY,123,at(DAY,7),1)
        store.mark_job(DAY,'wake_history')
        self.assertEqual(self.finalize(),'확인 필요')
        self.assertEqual(store.get_penalties(DAY)[0]['total'],0)

    def test_penalty_idempotency_and_correction(self):
        self.captured()
        self.assertEqual(self.finalize(),'결석')
        self.assertEqual(self.finalize(),'결석')
        self.assertEqual(store.get_penalties(DAY)[0]['total'],2)
        store.correct_attendance(DAY,123,'출석','장애 확인',999,at(DAY,11))
        self.assertEqual(self.finalize(),'출석')
        self.assertEqual(store.get_penalties(DAY)[0]['total'],0)

    def test_inactive_exclusion(self):
        self.captured()
        self.finalize()
        with database.connect() as db:
            db.execute("UPDATE users SET status='휴면'")
        self.assertEqual(self.finalize(),'관리 제외')
        self.assertEqual(store.get_penalties(DAY)[0]['total'],0)

    def test_monthly_reset_preserves_history(self):
        self.captured()
        self.finalize()
        self.assertEqual(store.get_penalties(date(2026,11,1))[0]['total'],0)
        self.assertEqual(store.get_penalties(DAY)[0]['total'],2)

    def test_six_point_candidate(self):
        for offset in range(3):
            target = DAY+timedelta(days=offset)
            self.captured(target)
            self.finalize(target)
        self.assertEqual(store.get_penalties(DAY)[0]['total'],6)

    def test_weekends_holidays_and_override(self):
        self.assertFalse(is_study_day(date(2026,10,17)))
        self.assertFalse(is_study_day(date(2026,10,9)))
        set_holiday(DAY,True,'임시휴일')
        self.assertFalse(is_study_day(DAY))
        self.assertFalse(self.leave()[0])
        set_holiday(DAY,None,'자동 복귀')
        self.assertTrue(is_study_day(DAY))
        with self.assertRaises(ValueError):
            self.finalize(date(2026,10,17))

    def test_no_final_before_1030(self):
        with self.assertRaises(ValueError):
            store.calculate_final_attendance(DAY,at(DAY,10,30)-timedelta(microseconds=1))

    def test_persistent_thread_and_snapshot(self):
        store.save_thread(DAY,456)
        self.captured()
        database.create_tables()
        self.assertEqual(store.get_thread(DAY),456)
        store.save_video_snapshot(DAY,'08:35',set(),at(DAY,9))
        store.save_wake_record(DAY,123,at(DAY,7),1)
        self.assertEqual(self.finalize(),'출석')

    def test_legacy_leave_requires_review(self):
        with database.connect() as db:
            db.execute("INSERT INTO leaves(date,user_id,type,status) VALUES (?,1,'종일','승인')",(DAY,))
        self.captured()
        self.assertEqual(self.finalize(),'확인 필요')

    def test_capture_uses_state_at_exact_slot(self):
        auto = Automation(SimpleNamespace(),None)
        auto.connected_since = at(DAY,8)
        auto.timeline = [(at(DAY,8),{123}),(at(DAY,8,35)+timedelta(seconds=1),set())]
        auto.capture_slot(DAY,'08:35',at(DAY,8,35)+timedelta(seconds=5))
        store.mark_job(DAY,'wake_history')
        store.save_wake_record(DAY,123,at(DAY,7),1)
        self.assertEqual(self.finalize(),'출석')

    def test_capture_after_disconnect_is_unknown(self):
        auto = Automation(SimpleNamespace(),None)
        auto.connected_since = at(DAY,8,35)+timedelta(seconds=1)
        auto.timeline = [(auto.connected_since,{123})]
        auto.capture_slot(DAY,'08:35',at(DAY,8,35)+timedelta(seconds=5))
        self.assertEqual(store.job_status(DAY,'video_08:35'),'missed')
        self.assertEqual(self.finalize(),'확인 필요')

    def test_ordinary_tick_does_not_create_goal_tasks(self):
        auto = Automation(SimpleNamespace(is_ready=lambda: True),None)
        saturday = DAY-timedelta(days=(DAY.weekday()-5)%7)
        store.mark_job(saturday,'weekly_leave')
        auto._ensure_wake = AsyncMock()
        auto.finalize = AsyncMock()
        asyncio.run(auto.tick(at(DAY,8,15)))
        auto._ensure_wake.assert_awaited_once_with(DAY)
        auto.finalize.assert_not_awaited()

    def test_final_and_report_retry_without_repeating_final(self):
        auto = Automation(SimpleNamespace(is_ready=lambda: True),None)
        saturday = DAY-timedelta(days=(DAY.weekday()-5)%7)
        store.mark_job(saturday,'weekly_leave')
        async def finalize(day):
            store.mark_job(day,'final')
        async def report(day):
            store.mark_job(day,'report')
        auto.finalize = AsyncMock(side_effect=finalize)
        auto.report = AsyncMock(side_effect=report)
        asyncio.run(auto.tick(at(DAY,10,30)))
        asyncio.run(auto.tick(at(DAY,10,31)))
        auto.finalize.assert_awaited_once_with(DAY)
        auto.report.assert_awaited_once_with(DAY)

    def test_holiday_tick_no_attendance(self):
        auto = Automation(SimpleNamespace(is_ready=lambda: True),None)
        store.mark_job(DAY-timedelta(days=(DAY.weekday()-5)%7),'weekly_leave')
        set_holiday(DAY,True,'임시휴일')
        auto._ensure_wake = AsyncMock()
        auto.finalize = AsyncMock()
        asyncio.run(auto.tick(at(DAY,10,30)))
        auto._ensure_wake.assert_not_awaited()
        auto.finalize.assert_not_awaited()
        self.assertEqual(store.get_attendance(DAY),[])

    def test_report_replies_to_daily_wake_thread_after_restart(self):
        store.save_thread(DAY,456)
        thread = MagicMock(spec=discord.Thread)
        thread.guild = SimpleNamespace(id=1)
        thread.parent_id = 2
        thread.archived = True
        thread.edit = AsyncMock()
        bot = SimpleNamespace(get_channel=lambda _: None, fetch_channel=AsyncMock(return_value=thread))
        auto = Automation(bot,SimpleNamespace(guild_id=1,wake_channel_id=2))
        auto.send_once = AsyncMock()
        asyncio.run(auto.report(DAY))
        bot.fetch_channel.assert_awaited_once_with(456)
        thread.edit.assert_awaited_once_with(archived=False)
        self.assertIs(auto.send_once.call_args.args[0],thread)
        self.assertEqual(store.job_status(DAY,'report'),'done')

    def test_report_without_thread_does_not_create_post(self):
        auto = Automation(SimpleNamespace(),SimpleNamespace(guild_id=1,wake_channel_id=2))
        auto.send_once = AsyncMock()
        with self.assertRaises(RuntimeError):
            asyncio.run(auto.report(DAY))
        auto.send_once.assert_not_awaited()
        self.assertIsNone(store.job_status(DAY,'report'))

    def test_report_rejects_thread_from_other_forum(self):
        store.save_thread(DAY,456)
        thread = MagicMock(spec=discord.Thread)
        thread.guild = SimpleNamespace(id=1)
        thread.parent_id = 999
        auto = Automation(SimpleNamespace(get_channel=lambda _: thread),SimpleNamespace(guild_id=1,wake_channel_id=2))
        auto.send_once = AsyncMock()
        with self.assertRaises(RuntimeError):
            asyncio.run(auto.report(DAY))
        auto.send_once.assert_not_awaited()

    def test_weekend_tick_only_weekly_post(self):
        auto = Automation(SimpleNamespace(is_ready=lambda: True),None)
        auto.weekly_leave = AsyncMock()
        auto._ensure_wake = AsyncMock()
        auto.finalize = AsyncMock()
        asyncio.run(auto.tick(at(date(2026,10,17),10)))
        auto.weekly_leave.assert_awaited_once_with(date(2026,10,17))
        auto._ensure_wake.assert_not_awaited()
        auto.finalize.assert_not_awaited()


class MigrationTests(unittest.TestCase):
    def test_existing_db_preserved(self):
        with TemporaryDirectory() as tmp:
            old_path = database.DB_NAME
            database.DB_NAME = str(Path(tmp)/'legacy.db')
            try:
                with sqlite3.connect(database.DB_NAME) as db:
                    db.executescript('''
                        CREATE TABLE users(id INTEGER PRIMARY KEY,discord_id INTEGER UNIQUE NOT NULL,name TEXT NOT NULL,status TEXT NOT NULL DEFAULT '활성');
                        CREATE TABLE attendance(id INTEGER PRIMARY KEY,date DATE,user_id INTEGER,wake_status TEXT,video_status TEXT,final_status TEXT, UNIQUE(date,user_id));
                        CREATE TABLE leaves(id INTEGER PRIMARY KEY,date DATE,user_id INTEGER,type TEXT,status TEXT DEFAULT '대기',evidence TEXT,UNIQUE(date,user_id));
                        CREATE TABLE penalties(id INTEGER PRIMARY KEY,date DATE,user_id INTEGER,score INTEGER,reason TEXT);
                        INSERT INTO users VALUES (1,123,'기존멤버','활성');
                        INSERT INTO penalties VALUES (1,'2026-10-01',1,1,'기존 벌점');
                    ''')
                database.create_tables()
                database.create_tables()
                with database.connect() as db:
                    self.assertEqual(db.execute('SELECT name FROM users').fetchone()[0],'기존멤버')
                    self.assertEqual(db.execute('SELECT SUM(score) FROM penalties').fetchone()[0],1)
                self.assertEqual(len(list(Path(tmp).glob('*.bak'))),1)
            finally:
                database.DB_NAME = old_path


if __name__ == '__main__':
    unittest.main()
