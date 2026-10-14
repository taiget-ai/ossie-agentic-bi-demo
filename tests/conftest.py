from datetime import date
from pathlib import Path

import pytest

from ossie_demo.database import Database
from ossie_demo.service import SemanticService


@pytest.fixture(params=["duckdb", "sqlite"])
def service(tmp_path, request):
    project_root = Path(__file__).resolve().parents[1]
    db = Database(tmp_path / ("test." + request.param), backend=request.param)
    db.seed(today=date(2026, 10, 9))
    # Preserve the small hand-calculated baseline; expanded fixtures have their own tests.
    conn = db.connect()
    try:
        conn.execute('DELETE FROM bets WHERE player_id > 4')
        conn.execute('DELETE FROM deposits WHERE player_id > 4')
        conn.execute('DELETE FROM players WHERE player_id > 4')
        conn.commit()
    finally:
        conn.close()
    return SemanticService(project_root / "models/gaming.yaml", database=db)
