"""날짜별 기상 미션과 인증 게시글 양식."""
import random
from database import connect

MISSIONS = (
    '👍🏻 (엄지척)', '👎🏻 (붐따)', '👊🏻 (주먹)', '🤞🏻 (행운)',
    '✌🏻 (브이)', '🫰🏻 (손하트)', '🤟🏻 (사랑해)', '🤘🏻 (락앤롤)',
    '👌🏻 (오케이)', '👉🏻 (총모양)', '☝🏻 (콕찌르기)', '✋🏻 (하이파이브)', '🤙🏻 (손전화)',
)


def wake_title(day):
    return f'{day.month}월 {day.day}일 기상 인증'


def wake_body(day):
    with connect() as db:
        row = db.execute('SELECT mission FROM wake_missions WHERE date=?',(day,)).fetchone()
        if row is None:
            db.execute('INSERT OR IGNORE INTO wake_missions VALUES (?,?)',(day,random.choice(MISSIONS)))
            row = db.execute('SELECT mission FROM wake_missions WHERE date=?',(day,)).fetchone()
    return ('## ⏰ 기상 인증\n\n좋은 아침입니다!\n\n### 오늘의 기상 미션\n'
            f'> # {row[0]}\n'
            '타임스탬프 앱 또는 갤러리 화면을 이용하여\n'
            '**촬영 시간이 보이도록** 인증 사진을 업로드해 주세요.\n\n'
            '### 출결 확인\n')
