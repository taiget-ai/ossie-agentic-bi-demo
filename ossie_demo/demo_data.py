"""Explicit initialization of the example warehouse; never used by query execution."""
import csv
from datetime import date, timedelta
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / 'data' / 'fixtures'
TABLES = ('players', 'games', 'bets', 'deposits')


def fixture(name):
    with (FIXTURES / f'{name}.csv').open(encoding='utf-8', newline='') as stream:
        return list(csv.DictReader(stream))


def seed_demo(database, today: date | None = None):
    """Re-create all demo tables from committed fixtures (explicit destructive reset)."""
    today = today or date.today()
    conn = database.connect()
    try:
        conn.execute("BEGIN TRANSACTION")
        for table in reversed(TABLES):
            conn.execute(f'DROP TABLE IF EXISTS "{table}"')
        conn.execute('CREATE TABLE players (player_id INTEGER PRIMARY KEY, country VARCHAR NOT NULL)')
        conn.execute('CREATE TABLE games (game_id INTEGER PRIMARY KEY, game_category VARCHAR NOT NULL)')
        conn.execute('''CREATE TABLE bets (
            bet_id INTEGER PRIMARY KEY, player_id INTEGER NOT NULL, game_id INTEGER NOT NULL,
            bet_date DATE NOT NULL, amount DECIMAL(12,2) NOT NULL,
            payout_amount DECIMAL(12,2) NOT NULL, bonus_cost DECIMAL(12,2) NOT NULL
        )''')
        conn.execute('''CREATE TABLE deposits (
            deposit_id INTEGER PRIMARY KEY, player_id INTEGER NOT NULL,
            deposit_date DATE NOT NULL, amount DECIMAL(12,2) NOT NULL
        )''')
        players = fixture('players')
        games = fixture('games')
        bets = fixture('bets')
        deposits = fixture('deposits')
        conn.executemany('INSERT INTO players VALUES (?, ?)',
                         [(int(x['player_id']), x['country']) for x in players])
        conn.executemany('INSERT INTO games VALUES (?, ?)',
                         [(int(x['game_id']), x['game_category']) for x in games])
        conn.executemany('INSERT INTO bets VALUES (?, ?, ?, ?, ?, ?, ?)', [
            (int(x['bet_id']), int(x['player_id']), int(x['game_id']),
             (today - timedelta(days=int(x['days_ago']))).isoformat(),
             x['amount'], x['payout_amount'], x['bonus_cost']) for x in bets
        ])
        conn.executemany('INSERT INTO deposits VALUES (?, ?, ?, ?)', [
            (int(x['deposit_id']), int(x['player_id']),
             (today - timedelta(days=int(x['days_ago']))).isoformat(), x['amount'])
            for x in deposits
        ])
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {'bets': len(bets), 'deposits': len(deposits),
            'players': len(players), 'games': len(games), 'today': today.isoformat(),
            'database_path': str(database.path)}

