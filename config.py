import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    token: str
    guild_id: int
    wake_channel_id: int
    morning_channel_id: int
    leave_channel_id: int

    @classmethod
    def from_env(cls):
        names = ['DISCORD_TOKEN','GUILD_ID','WAKE_CHANNEL_ID','MORNING_CHANNEL_ID','LEAVE_CHANNEL_ID']
        missing = [name for name in names if not os.getenv(name)]
        if missing:
            raise ValueError('필수 환경변수를 설정해주세요: ' + ', '.join(missing))
        try:
            ids = [int(os.environ[name]) for name in names[1:]]
        except ValueError as error:
            raise ValueError('서버·채널 ID는 숫자여야 합니다.') from error
        if any(value <= 0 for value in ids):
            raise ValueError('서버·채널 ID는 양수여야 합니다.')
        return cls(os.environ[names[0]], *ids)
