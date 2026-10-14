# 맥집사 개발·운영 환경 문서

참여자용 운영 규칙은 [README](../README.md), 검증 결과와 시험 순서는 [테스트 안내](TESTING.md)를 참고한다.

## 로컬 준비

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
# 프로젝트 폴더에 .env 파일을 만들고 아래 필수 항목을 작성한다.
```

기존 `.env`가 있으면 누락 항목만 추가한다. 토큰 값은 문서나 채팅에 공개하지 않는다.

`.env` 예시(실제 값으로 교체):

```dotenv
DISCORD_TOKEN=your-bot-token
GUILD_ID=your-server-id
WAKE_CHANNEL_ID=your-wake-forum-channel-id
MORNING_CHANNEL_ID=your-morning-voice-channel-id
LEAVE_CHANNEL_ID=your-leave-channel-id
# DATABASE_PATH=/opt/mcmorning-bot/data/mcmorning.db
```

출결 결과는 DB에 저장된 **해당 날짜의 기상 인증 Thread**에 댓글로 전송한다. 보관된 Thread는 보관 해제 후 댓글을 작성하며, Thread가 없거나 접근할 수 없으면 별도 게시글을 만들지 않고 오류를 기록해 재시도한다.

환경변수 항목:

| 항목               | 내용                                      |
| ------------------ | ----------------------------------------- |
| DISCORD_TOKEN      | 봇 토큰(외부 공유 금지)                   |
| GUILD_ID           | 스터디 Discord 서버 ID                    |
| WAKE_CHANNEL_ID    | 기상 인증 **포럼** 채널 ID                |
| MORNING_CHANNEL_ID | 모닝 **음성** 채널 ID                     |
| LEAVE_CHANNEL_ID   | 휴무 안내 **텍스트 또는 포럼** 채널 ID    |
| DATABASE_PATH      | 선택. 기본 프로젝트 폴더의 `mcmorning.db` |

Developer Portal의 Bot 설정에서 **Server Members Intent**, **Message Content Intent**를 켠다.
초대 시 `bot`, `applications.commands` 범위를 사용한다.
지정 채널에 View Channel, Read Message History, Send Messages, Send Messages in Threads,
Create Public Threads 권한을 허용한다. 포럼 태그 필수 설정은 해제하고,
보관된 Thread 읽기 및 음성 채널 접근도 테스트한다.
명령은 지정한 GUILD_ID 서버에만 등록된다. 기존 전역 명령은 시작 시 제거한다.
관리 명령은 **서버 관리(Manage Server)** 권한이 필요하다.

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python database.py  # 기존 데이터 보존 + 테이블 생성/확장
.venv/bin/python bot.py
```

`database.py`를 직접 실행하거나 봇을 시작하면 기존 DB를 자동 확장한다.
이 문서의 DB 초기화는 테이블 준비이며 데이터 삭제가 아니다. `.env`의 `DATABASE_PATH`도 적용한다. 마이그레이션 직전에 기존 DB 사본을
`mcmorning.db.pre-migration-시각.bak`으로 남긴다. 기존 데이터는 삭제하지 않는다.
과거 휴무는 신청·승인 시각을 추정하지 않고 `확인 필요`로 남긴다.
등록된 활성 멤버가 실제 스터디 명단과 맞는지 `/멤버등록`, `/멤버상태변경`으로 확인한다.

## 명령

일반: `/휴무신청`, `/휴무취소`, `/내휴무`, `/출결확인`, `/벌점확인`

관리자: `/멤버등록`, `/멤버상태변경`, `/휴무관리`,
`/기상게시글`, `/출결판정`, `/출결정정`

`/휴무관리`는 대기 신청과 증빙 링크를 관리자 전용 화면에 표시한다. 승인·반려 버튼으로 처리하고 이전·다음·새로고침으로 탐색한다. 별도 `/휴무처리` 명령은 제거했다. 버튼 클릭 시에도 관리자 권한·서버·화면 소유자·마감·최신 신청 상태를 검사한다. 화면은 10분 후 만료되며 명령을 재실행하면 된다.
휴무 신청·취소·승인 이벤트와 출결 정정 사유·관리자·시각은 DB에 남는다.
`/출결판정`은 10:30 이후 저장된 정시 기록으로만 재계산한다.
`/출결정정`은 장애/오판정에 대한 최종 결과와 자동 벌점을 정정하고, 이후 재계산에도 유지한다.
정정 후 게시된 최초 결과 메시지는 자동 갱신되지 않는다. `/출결확인`이 최신 결과다.

## 장애와 재시작

- Thread ID, 정시 영상 기록, 작업 완료 이력은 SQLite에 영구 저장한다.
- 기상 최초 메시지는 10:30에 Thread 이력을 다시 읽어 복구한다. 삭제된 미수집 메시지는 복구 불가.
- Discord 게시 성공 후 DB 저장 전 종료한 경우 봇 소유 Thread 제목/결과 메시지 표식으로 중복 게시를 억제한다.
- 게시·기록 복구 실패는 로그에 남기고 5초 주기마다 재시도한다.
- 예정 시각 이전부터 연결되어 있고 1분 내 작업이 실행된 경우, 메모리의 상태 변경 이력으로 **정시 상태**를 저장한다.
- 정시 전에 꺼졌거나 연결이 끊겼던 경우 현재 상태를 과거 상태로 사용하지 않는다.
  영상 기록 누락은 **확인 필요 / 자동 벌점 0**으로 남긴다. 관리자 `/출결정정`으로 확정한다.
- 06:01 이전에 기상 게시글을 생성하지 못한 날도 확인 필요로 남긴다(휴무 면제는 유지).
- 재시작 후 당일 및 DB에 남은 미완료 운영일의 판정·보고를 복구한다.
- 누락된 토요일 안내는 다음 금요일까지 복구한다.
- 동일 환경에서 두 프로세스가 뜨지 않도록 파일 잠금을 사용한다.
  로컬과 서버에서 같은 봇을 동시에 실행하지 않는다.

## 실제 Discord 검증 후 서버 선택

서버를 구매하기 전에 테스트용 Discord 서버에서 다음 흐름을 확인한다.

1. 서버·채널 ID와 권한, 관리자/일반 사용자 명령 접근 확인.
2. 기상 Thread에서 최초 인증을 남기고 재시작 후에도 연결되는지 확인.
3. 휴무 신청·취소·증빙 승인, 주간 한도 및 마감 확인.
4. 운영일 06:00 전부터 실행해 08:35·09:35 카메라/화면 공유 및 미참여 기록 확인.
5. 10:30 당일 기상 인증 Thread의 결과 댓글과 벌점 확인. 재계산 시 중복 벌점 없음 확인.
6. 정시 확인을 놓친 경우 확인 필요로 남는지, 관리자 정정이 유지되는지 확인.

자동화는 실제 출결과 벌점을 기록한다. 시험 서버에는 별도 봇 토큰/DB/명단을 사용한다.
기존 실제 서버를 사용할 경우 먼저 시험 운영 멤버만 활성으로 등록한다.

## Linux 상시 실행 준비

서버는 아직 선택하지 않았다. 아래는 systemd가 있는 Linux 서버용 준비 설정이며 배포는 수행하지 않았다.

1. 전용 사용자 `mcmorning`을 만들고 프로젝트를 `/opt/mcmorning-bot`에 배치한다.
2. 해당 경로에서 가상환경/requirements를 설치하고 `.env`를 작성한다.
3. 영구 데이터 폴더 `/opt/mcmorning-bot/data`를 만들고 사용자에게 쓰기 권한을 준다.
4. 기존 DB를 옮기는 경우 봇을 정지한 상태에서 이전하고 `DATABASE_PATH=/opt/mcmorning-bot/data/mcmorning.db`로 설정한다.
5. `.env`와 DB는 전용 사용자만 읽을 수 있도록 설정한다.
6. `deploy/mcmorning-bot.service`를 `/etc/systemd/system/`에 설치한다.

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now mcmorning-bot
sudo systemctl status mcmorning-bot
sudo journalctl -u mcmorning-bot -f
```

봇이 Discord에 연결하는 방식이므로 별도 웹 서버/인바운드 웹 포트는 필요하지 않다.
코드를 업데이트할 때는 백업 후 봇을 재시작한다.

```sh
.venv/bin/python backup.py --directory backups
```

백업은 SQLite 백업 API로 일관된 사본을 만들며, 실행 중에도 사용할 수 있다.
서버 선택 후 일일 백업 예약과 서버 외부 보관을 설정한다. 백업 파일에는 멤버 정보가 있으므로 공유하지 않는다.
복원은 봇을 정지한 뒤 백업 사본을 DATABASE_PATH에 배치하고 다시 시작한다.

## 주간 휴무 신청 UI

주간 안내 게시에 성공한 뒤 `leave_windows`에 월~금 기간을 저장한다. 최신 발행 기간만 신청·취소할 수 있다. 기존 발행 완료 작업은 DB 초기화 시 복원한다. 발행된 글이 없으면 신청·취소가 차단된다.

`/휴무신청`은 유형·증빙을 받아 날짜 선택 목록과 확정 버튼을 표시한다. 날짜는 직접 입력하지 않는다. `/휴무취소`는 본인의 현재 기간 내 승인·대기 신청 중 08:31 마감 전 건만 표시한다. 화면은 10분 후 만료되고, 확정 시 최신 기간·마감을 재검사한다. 취소 후 재신청된 건은 이전 화면에서 취소할 수 없다. `/내휴무`도 최신 발행 기간의 본인 신청만 조회한다(승인·대기·반려·취소 포함). 사용자의 휴무 조회·신청·취소는 모두 동일한 주간 범위를 따른다. 과거 기록은 DB에 보존하지만 일반 사용자 휴무 화면에는 노출하지 않는다.
