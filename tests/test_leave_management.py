from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import unittest

import database
from commands.leave_management import LeaveManagementView
from commands.leave_self_service import LeaveRequestView, LeaveCancelView, LeaveDetailsModal
from services import attendance as store
from services.rules import OTHER, at

DAY = date(2026,10,14)


class LeaveManagementTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = TemporaryDirectory()
        self.old_db = database.DB_NAME
        database.DB_NAME = str(Path(self.tmp.name)/'test.db')
        database.create_tables()
        store.open_leave_window(DAY-timedelta(days=(DAY.weekday()-5)%7),at(DAY-timedelta(days=(DAY.weekday()-5)%7),10))
        with database.connect() as db:
            db.execute("INSERT INTO users(discord_id,name) VALUES (123,'신청자')")
        for offset in (0,1):
            store.create_leave(DAY+timedelta(days=offset),123,OTHER,'https://example.com/evidence.png',at(DAY,7))
        self.clock = patch('commands.leave_management.now_kst', return_value=at(DAY,9))
        self.service_clock = patch('services.attendance.now_kst', return_value=at(DAY,9))
        self.clock.start()
        self.service_clock.start()
        self.view = LeaveManagementView(1,999)
        self.view.render()

    async def asyncTearDown(self):
        self.view.stop()
        self.clock.stop()
        self.service_clock.stop()
        database.DB_NAME = self.old_db
        self.tmp.cleanup()

    def interaction(self, custom_id=None):
        return SimpleNamespace(guild_id=1,user=SimpleNamespace(id=999),permissions=SimpleNamespace(manage_guild=True),
            data={'custom_id':custom_id or self.view.approve.custom_id},
            response=SimpleNamespace(edit_message=AsyncMock(),send_message=AsyncMock()))

    async def test_self_service_date_options_and_ownership(self):
        with patch('services.attendance.now_kst',return_value=at(DAY,7)):
            view = LeaveRequestView(1,123)
            self.assertEqual([o.value for o in view.choose_date.options],['2026-10-14','2026-10-15','2026-10-16'])
            self.assertTrue(view.submit.disabled)
            interaction = self.interaction()
            self.assertFalse(await view.interaction_check(interaction))
            interaction.user.id=123
            self.assertTrue(await view.interaction_check(interaction))
            view.stop()

    async def test_request_selection_stays_visible_and_can_be_changed(self):
        view = LeaveRequestView(1,123)
        interaction = self.interaction()
        for value in ['2026-10-15','2026-10-16']:
            view.choose_date._values = [value]
            await view.choose_date.callback(interaction)
            self.assertEqual([o.value for o in view.choose_date.options if o.default],[value])
        interaction.response.send_modal = AsyncMock()
        await view.submit.callback(interaction)
        modal = interaction.response.send_modal.call_args.args[0]
        self.assertEqual(modal.day,date(2026,10,16))
        self.assertEqual(len(modal.children),2)
        self.assertIsNone(store.get_leave(date(2026,10,16),123))
        interaction.response.edit_message.assert_called_with(view=view)
        modal.stop()
        view.stop()

    async def test_modal_other_requires_evidence_before_writing(self):
        view = LeaveRequestView(1,123)
        modal = LeaveDetailsModal(view,date(2026,10,16))
        modal.leave_type._values = [OTHER]
        interaction = self.interaction()
        await modal.on_submit(interaction)
        self.assertIsNone(store.get_leave(date(2026,10,16),123))
        self.assertIn('증빙',interaction.response.send_message.call_args.args[0])
        modal.evidence._values = [SimpleNamespace(url='https://example.com/proof.png')]
        await modal.on_submit(interaction)
        self.assertEqual(store.get_leave(date(2026,10,16),123)['status'],'대기')
        modal.stop()
        view.stop()

    async def test_single_form_collects_date_type_and_file(self):
        view = LeaveRequestView(1,123)
        modal = LeaveDetailsModal(view)
        self.assertEqual(len(modal.children),3)
        modal.choose_date._values = ['2026-10-16']
        modal.leave_type._values = [OTHER]
        modal.evidence._values = [SimpleNamespace(url='https://example.com/proof.png')]
        interaction = self.interaction()
        await modal.on_submit(interaction)
        self.assertEqual(store.get_leave(date(2026,10,16),123)['status'],'대기')
        interaction.response.send_message.assert_awaited_once()
        modal.stop()
        view.stop()

    async def test_success_updates_original_message_without_duplicate(self):
        view = LeaveRequestView(1,123)
        view.message = SimpleNamespace(edit=AsyncMock())
        modal = LeaveDetailsModal(view,date(2026,10,16))
        modal.leave_type._values = ['종일']
        interaction = self.interaction()
        await modal.on_submit(interaction)
        interaction.response.edit_message.assert_awaited_once()
        interaction.response.send_message.assert_not_awaited()
        view.message.edit.assert_not_awaited()
        modal.stop()
        view.stop()

    async def test_cancel_selection_stays_visible_and_uses_latest_choice(self):
        with patch('services.attendance.now_kst',return_value=at(DAY,7)):
            view = LeaveCancelView(1,123)
            interaction = self.interaction()
            for key in view.rows:
                view.choose_leave._values = [key]
                await view.choose_leave.callback(interaction)
                self.assertEqual([o.value for o in view.choose_leave.options if o.default],[key])
            selected_day = date.fromisoformat(view.selected['date'])
            await view.cancel.callback(interaction)
            self.assertIsNone(store.get_leave(selected_day,123))
            other_day = DAY if selected_day != DAY else DAY+timedelta(days=1)
            self.assertIsNotNone(store.get_leave(other_day,123))
            view.stop()

    async def test_cancel_only_shows_own_current_open_requests(self):
        with patch('services.attendance.now_kst',return_value=at(DAY,9)):
            view = LeaveCancelView(1,123)
            self.assertEqual(len(view.rows),1)
            self.assertEqual(next(iter(view.rows.values()))['date'],'2026-10-15')
            other = LeaveCancelView(1,321)
            self.assertFalse(other.rows)
            self.assertTrue(other.choose_leave.disabled)
            view.stop()
            other.stop()

    async def test_approve_removes_current_request_and_shows_next(self):
        first = self.view.rows[0]['id']
        interaction = self.interaction()
        await self.view.process(interaction,'승인')
        self.assertEqual(len(self.view.rows),1)
        self.assertNotEqual(self.view.rows[0]['id'],first)
        self.assertEqual(len(store.get_leaves(pending=True)),1)
        self.assertIn('첨부파일 열기',self.view.render().fields[3].value)

    async def test_stale_double_click_does_not_approve_next_request(self):
        old_id = self.view.approve.custom_id
        await self.view.process(self.interaction(old_id),'승인')
        await self.view.process(self.interaction(old_id),'승인')
        self.assertEqual(len(store.get_leaves(pending=True)),1)

    async def test_reject_last_request_shows_empty_state(self):
        await self.view.process(self.interaction(),'반려')
        await self.view.process(self.interaction(),'반려')
        self.assertEqual(len(store.get_leaves(pending=True)),0)
        self.assertTrue(self.view.approve.disabled)
        self.assertIn('없습니다',self.view.render().description)

    async def test_permission_revoked_or_other_admin_cannot_click(self):
        interaction = self.interaction()
        self.assertTrue(await self.view.interaction_check(interaction))
        interaction.permissions.manage_guild=False
        self.assertFalse(await self.view.interaction_check(interaction))
        interaction.permissions.manage_guild=True
        interaction.user.id=888
        self.assertFalse(await self.view.interaction_check(interaction))

    async def test_expired_click_keeps_request_pending(self):
        # 날짜가 늦은 신청부터 표시되므로 다음날 마감 시각을 사용한다.
        target = date.fromisoformat(self.view.rows[0]['date'])
        with patch('services.attendance.now_kst',return_value=at(target,10,1)):
            await self.view.process(self.interaction(),'승인')
        self.assertEqual(len(store.get_leaves(pending=True)),2)

    async def test_timeout_disables_all_buttons(self):
        self.view.message=SimpleNamespace(edit=AsyncMock())
        await self.view.on_timeout()
        self.assertTrue(all(item.disabled for item in self.view.children))
        self.view.message.edit.assert_awaited_once()
