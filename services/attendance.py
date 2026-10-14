from datetime import date as Date, datetime, timedelta
from database import connect
from services.calendar import is_study_day
from services.rules import FULL, LATE, OTHER, LEAVE_TYPES, at, now_kst, timestamp, wake_status, judge


def active_members():
    with connect() as db:
        return db.execute("SELECT * FROM users WHERE status='활성'").fetchall()


def create_daily_attendance(day):
    if not is_study_day(day):
        return
    with connect() as db:
        db.execute("INSERT OR IGNORE INTO attendance(date,user_id) SELECT ?,id FROM users WHERE status='활성'", (day,))


def save_wake_record(day, discord_id, created_at, message_id):
    if created_at.astimezone(at(day, 0).tzinfo).date() != day:
        return
    create_daily_attendance(day)
    value = timestamp(created_at)
    with connect() as db:
        db.execute('''UPDATE attendance SET wake_at=?, wake_message_id=?, wake_status=?
            WHERE date=? AND user_id=(SELECT id FROM users WHERE discord_id=?)
            AND (wake_at IS NULL OR wake_at>?)''',
            (value, message_id, wake_status(created_at), day, discord_id, value))


def get_thread(day):
    with connect() as db:
        row = db.execute('SELECT thread_id FROM daily_threads WHERE date=?', (day,)).fetchone()
    return row[0] if row else None


def save_thread(day, thread_id):
    with connect() as db:
        db.execute('INSERT INTO daily_threads VALUES (?,?) ON CONFLICT(date) DO UPDATE SET thread_id=excluded.thread_id', (day, thread_id))


def job_status(day, name):
    with connect() as db:
        row = db.execute('SELECT status FROM jobs WHERE date=? AND name=?', (day, name)).fetchone()
    return row[0] if row else None


def mark_job(day, name, status='done', detail=None):
    with connect() as db:
        db.execute('''INSERT INTO jobs VALUES (?,?,?,?,?) ON CONFLICT(date,name)
            DO UPDATE SET status=excluded.status, updated_at=excluded.updated_at, detail=excluded.detail''',
            (day, name, status, timestamp(now_kst()), detail))


def save_video_snapshot(day, slot, participants, captured_at):
    """participants는 해당 시각에 영상 참여한 Discord 사용자 ID 집합."""
    create_daily_attendance(day)
    with connect() as db:
        for user in db.execute("SELECT id,discord_id FROM users WHERE status='활성'").fetchall():
            status = '참여' if user['discord_id'] in participants else '미참여'
            db.execute('INSERT OR IGNORE INTO video_snapshots VALUES (?,?,?,?,?)',
                (day, slot, user['id'], status, timestamp(captured_at)))
        db.execute('INSERT OR REPLACE INTO jobs VALUES (?,?,?,?,?)',
            (day, 'video_' + slot, 'done', timestamp(captured_at), None))


def get_leave(day, discord_id):
    with connect() as db:
        return db.execute('''SELECT l.* FROM leaves l JOIN users u ON u.id=l.user_id
            WHERE l.date=? AND u.discord_id=? AND l.status NOT IN ('취소','반려')''', (day, discord_id)).fetchone()


def _weekly_units(db, day, user_id):
    start = day - timedelta(days=day.weekday())
    rows = db.execute("SELECT type FROM leaves WHERE user_id=? AND date BETWEEN ? AND ? AND status NOT IN ('취소','반려')", (user_id, start, start + timedelta(days=6)))
    return sum(2 if row[0] == FULL else 0 if row[0] == OTHER else 1 for row in rows)


def create_leave(day, discord_id, leave_type, evidence=None, now=None):
    now = now or now_kst()
    if leave_type not in LEAVE_TYPES:
        return False, '잘못된 휴무 유형입니다.'
    if now >= at(day, 8, 31):
        return False, '당일 08:30까지 신청할 수 있습니다.'
    if not is_study_day(day):
        return False, '주말·공휴일에는 휴무를 사용할 필요가 없습니다.'
    if leave_type == OTHER and not evidence:
        return False, '기타 휴무는 증빙 자료가 필요합니다.'
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        user = db.execute("SELECT id FROM users WHERE discord_id=? AND status='활성'", (discord_id,)).fetchone()
        if user is None:
            return False, '등록된 활성 멤버가 아닙니다.'
        existing = db.execute('SELECT id,status FROM leaves WHERE date=? AND user_id=?', (day, user[0])).fetchone()
        if existing and existing['status'] not in ('취소', '반려'):
            return False, '해당 날짜에 이미 신청된 휴무가 있습니다.'
        units = 0 if leave_type == OTHER else 2 if leave_type == FULL else 1
        if units and _weekly_units(db, day, user[0]) + units > 2:
            return False, '주간 휴무 한도(전일 1회 또는 반휴 2회)를 초과했습니다.'
        status = '대기' if leave_type == OTHER else '승인'
        approved = None if leave_type == OTHER else timestamp(now)
        db.execute('''INSERT INTO leaves(date,user_id,type,status,evidence,requested_at,approved_at,processed_by)
            VALUES (?,?,?,?,?,?,?,NULL) ON CONFLICT(date,user_id) DO UPDATE SET
            type=excluded.type,status=excluded.status,evidence=excluded.evidence,
            requested_at=excluded.requested_at,approved_at=excluded.approved_at,processed_by=NULL''',
            (day, user[0], leave_type, status, evidence, timestamp(now), approved))
        leave_id = db.execute('SELECT id FROM leaves WHERE date=? AND user_id=?', (day, user[0])).fetchone()[0]
        db.execute('INSERT INTO leave_events(leave_id,action,actor_id,created_at) VALUES (?,?,?,?)', (leave_id, '신청:' + leave_type, discord_id, timestamp(now)))
    return True, status


def cancel_leave(day, discord_id, now=None):
    now = now or now_kst()
    if now >= at(day, 8, 31):
        return False, '당일 08:30까지 취소할 수 있습니다.'
    with connect() as db:
        row = db.execute("SELECT id FROM leaves WHERE date=? AND user_id=(SELECT id FROM users WHERE discord_id=?) AND status NOT IN ('취소','반려')", (day, discord_id)).fetchone()
        if not row:
            return False, '취소할 휴무 신청이 없습니다.'
        db.execute("UPDATE leaves SET status='취소' WHERE id=?", (row[0],))
        db.execute('INSERT INTO leave_events(leave_id,action,actor_id,created_at) VALUES (?,?,?,?)', (row[0], '취소', discord_id, timestamp(now)))
    return True, '취소'


def change_leave_status(leave_id, status, actor_id, now=None):
    now = now or now_kst()
    if status not in ('승인', '반려'):
        return False, '승인 또는 반려만 가능합니다.'
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute("SELECT * FROM leaves WHERE id=? AND status='대기'", (leave_id,)).fetchone()
        if not row:
            return False, '대기 중인 신청을 찾을 수 없습니다.'
        day = Date.fromisoformat(row['date'])
        if now >= at(day, 10, 1):
            return False, '당일 10:00까지 승인·반려할 수 있습니다.'
        if not row['requested_at'] or datetime.fromisoformat(row['requested_at']) >= at(day, 8, 31):
            return False, '신청 시각을 확인할 수 없거나 마감 이후 신청입니다.'
        db.execute('UPDATE leaves SET status=?,approved_at=?,processed_by=? WHERE id=?', (status, timestamp(now) if status == '승인' else None, actor_id, leave_id))
        db.execute('INSERT INTO leave_events(leave_id,action,actor_id,created_at) VALUES (?,?,?,?)', (leave_id, status, actor_id, timestamp(now)))
    return True, status


def get_leaves(discord_id=None, pending=False):
    query = 'SELECT l.*,u.name FROM leaves l JOIN users u ON u.id=l.user_id WHERE 1=1'
    params = []
    if discord_id is not None:
        query += ' AND u.discord_id=?'
        params.append(discord_id)
    if pending:
        query += " AND l.status='대기'"
    with connect() as db:
        return db.execute(query + ' ORDER BY l.date DESC,l.id DESC LIMIT 100', params).fetchall()


def _effective_leave(row, day):
    if row is None or row['status'] != '승인' or not row['requested_at']:
        return None
    if datetime.fromisoformat(row['requested_at']) >= at(day, 8, 31):
        return None
    if row['type'] == OTHER and (not row['approved_at'] or datetime.fromisoformat(row['approved_at']) >= at(day, 10, 1)):
        return None
    return row['type']


def calculate_final_attendance(day, now=None):
    now = now or now_kst()
    if now < at(day, 10, 30):
        raise ValueError('최종 출결은 당일 10:30 이후에 판정할 수 있습니다.')
    if not is_study_day(day):
        raise ValueError('주말·공휴일은 출결 판정 대상이 아닙니다.')
    create_daily_attendance(day)
    with connect() as db:
        complete = db.execute("SELECT 1 FROM jobs WHERE date=? AND name='wake_history' AND status='done'", (day,)).fetchone() is not None
        for user in db.execute("SELECT * FROM users WHERE status='활성'").fetchall():
            leave = db.execute('SELECT * FROM leaves WHERE date=? AND user_id=?', (day, user['id'])).fetchone()
            leave_type = _effective_leave(leave, day)
            record = db.execute('SELECT * FROM attendance WHERE date=? AND user_id=?', (day, user['id'])).fetchone()
            wake_at = datetime.fromisoformat(record['wake_at']) if record['wake_at'] else None
            slot = '09:35' if leave_type == LATE else '08:35'
            video_row = db.execute('SELECT status FROM video_snapshots WHERE date=? AND slot=? AND user_id=?', (day, slot, user['id'])).fetchone()
            video = video_row[0] if video_row else None
            # 시각 정보 없는 기존 휴무는 관리자 검토 대상으로 남긴다.
            legacy = leave is not None and leave['status'] in ('대기', '승인') and not leave['requested_at']
            final, score = ('확인 필요', 0) if legacy else judge(wake_at, video, leave_type, complete)
            reason = final
            if final == '결석':
                reason = ('기상 인증 없음' if wake_at is None else '기상 인증 마감 초과') if wake_status(wake_at, leave_type == LATE) == '결석' else f'{slot} 카메라·화면 공유 미참여'
            elif final == '지각':
                reason = '08:01~08:30 기상 인증'
            elif final == '확인 필요':
                reason = '기존 휴무 신청 시각 불명' if legacy else '기상 게시글/기록 복구 불완전' if not complete else f'{slot} 정시 영상 기록 없음'
            correction = db.execute('SELECT result,reason FROM attendance_corrections WHERE date=? AND user_id=? ORDER BY id DESC LIMIT 1', (day, user['id'])).fetchone()
            if correction:
                final = correction[0]
                score = {'지각': 1, '결석': 2}.get(final, 0)
                reason = '관리자 정정: ' + correction['reason']
            db.execute('UPDATE attendance SET wake_status=?,video_status=?,final_status=?,final_reason=? WHERE id=?',
                (None if leave_type in (FULL, OTHER) else wake_status(wake_at, leave_type == LATE), video, final, reason, record['id']))
            db.execute("DELETE FROM penalties WHERE date=? AND user_id=? AND source='attendance'", (day, user['id']))
            if score:
                db.execute('INSERT INTO penalties(date,user_id,score,reason,source) VALUES (?,?,?,?,?)', (day, user['id'], score, reason, 'attendance'))
        # 비활성 멤버는 이전에 생성된 당일 기록과 자동 벌점에서도 제외.
        db.execute("UPDATE attendance SET final_status='관리 제외' WHERE date=? AND user_id IN (SELECT id FROM users WHERE status!='활성')", (day,))
        db.execute("DELETE FROM penalties WHERE date=? AND source='attendance' AND user_id IN (SELECT id FROM users WHERE status!='활성')", (day,))


def get_attendance(day):
    with connect() as db:
        return db.execute('''SELECT u.name,a.wake_status,a.video_status,a.final_status,a.final_reason FROM attendance a
            JOIN users u ON a.user_id=u.id WHERE a.date=? ORDER BY u.name''', (day,)).fetchall()


def get_penalties(day):
    start = day.replace(day=1)
    next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    with connect() as db:
        return db.execute('''SELECT u.name,u.status,COALESCE(SUM(p.score),0) AS total FROM users u
            LEFT JOIN penalties p ON p.user_id=u.id AND p.date>=? AND p.date<?
            GROUP BY u.id ORDER BY total DESC,u.name''', (start, next_month)).fetchall()


def correct_attendance(day, discord_id, result, reason, actor_id, now=None):
    now = now or now_kst()
    if result not in ('출석', '지각', '결석', '휴무') or not reason.strip():
        raise ValueError('올바른 결과와 정정 사유가 필요합니다.')
    if now < at(day, 10, 30) or not is_study_day(day):
        raise ValueError('운영일 10:30 이후의 출결만 정정할 수 있습니다.')
    create_daily_attendance(day)
    with connect() as db:
        user = db.execute("SELECT id FROM users WHERE discord_id=? AND status='활성'", (discord_id,)).fetchone()
        if not user:
            raise ValueError('활성 멤버가 아닙니다.')
        db.execute('INSERT INTO attendance_corrections(date,user_id,result,reason,actor_id,created_at) VALUES (?,?,?,?,?,?)', (day, user[0], result, reason, actor_id, timestamp(now)))
        db.execute('UPDATE attendance SET final_status=?,final_reason=? WHERE date=? AND user_id=?', (result, '관리자 정정: ' + reason, day, user[0]))
        db.execute("DELETE FROM penalties WHERE date=? AND user_id=? AND source='attendance'", (day, user[0]))
        score = {'지각': 1, '결석': 2}.get(result, 0)
        if score:
            db.execute('INSERT INTO penalties(date,user_id,score,reason,source) VALUES (?,?,?,?,?)', (day, user[0], score, result + ': ' + reason, 'attendance'))
