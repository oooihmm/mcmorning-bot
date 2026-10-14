"""맥모닝 운영 규칙. 모든 경계 시각은 KST이며 상한은 미포함이다."""
from datetime import datetime, time
from zoneinfo import ZoneInfo

KST = ZoneInfo('Asia/Seoul')
FULL = '종일'
LATE = '반휴(늦게 참여)'
EARLY = '반휴(일찍 퇴장)'
OTHER = '기타'
LEAVE_TYPES = (FULL, LATE, EARLY, OTHER)


def now_kst():
    return datetime.now(KST)


def at(day, hour, minute=0):
    return datetime.combine(day, time(hour, minute), KST)


def timestamp(value):
    if value.tzinfo is None:
        raise ValueError('시간대가 있는 시각이 필요합니다.')
    return value.astimezone(KST).isoformat()


def wake_status(wake_at, late_leave=False):
    if wake_at is None:
        return '결석'
    clock = wake_at.astimezone(KST).time()
    if late_leave:
        return '기상' if clock < time(9, 30) else '결석'
    if clock < time(8, 1):
        return '기상'
    return '지각' if clock < time(8, 31) else '결석'


def judge(wake_at, video, leave_type=None, wake_complete=True):
    if leave_type in (FULL, OTHER):
        return '휴무', 0
    if not wake_complete or video is None:
        return '확인 필요', 0
    wake = wake_status(wake_at, leave_type == LATE)
    if wake == '결석' or video != '참여':
        return '결석', 2
    if wake == '지각':
        return '지각', 1
    return '출석', 0
