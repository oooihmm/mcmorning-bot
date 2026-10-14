"""실행 중인 SQLite DB도 일관된 사본으로 백업한다."""
import argparse
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv


def main():
    load_dotenv(Path(__file__).with_name('.env'))
    from database import DB_NAME
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', default='backups')
    args = parser.parse_args()
    directory = Path(args.directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f'mcmorning-{datetime.now():%Y%m%d-%H%M%S-%f}.db.bak'
    with sqlite3.connect(Path(DB_NAME).resolve().as_uri() + '?mode=ro', uri=True) as source:
        with sqlite3.connect(target) as backup:
            source.backup(backup)
    os.chmod(target, 0o600)
    print(f'백업 완료: {target}')


if __name__ == '__main__':
    main()
