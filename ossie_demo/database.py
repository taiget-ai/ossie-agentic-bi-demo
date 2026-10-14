"""DuckDB demo warehouse, seeded from version-controlled CSV fixtures.

SQLite is an optional CI/test backend; all documented users run DuckDB.
"""
import os
import sqlite3
import threading
from datetime import date
from decimal import Decimal
from pathlib import Path

from .demo_data import TABLES
from .planning.compiler import CompiledQuery

ROOT = Path(__file__).resolve().parent.parent
_DB_LOCK = threading.RLock()


class Database:
    def __init__(self, path: str | Path | None = None, backend: str | None = None):
        self.backend = backend or os.getenv('OSSIE_DB_BACKEND', 'duckdb')
        default = 'gaming.duckdb' if self.backend == 'duckdb' else 'gaming.sqlite'
        self.path = Path(path or os.getenv('OSSIE_DB_PATH', str(ROOT / 'data' / default)))
        self._lock = _DB_LOCK
        if self.backend not in ('duckdb', 'sqlite'):
            raise ValueError('OSSIE_DB_BACKEND must be duckdb or sqlite')

    def connect(self, *, read_only=False):
        if read_only and not self.path.exists():
            raise FileNotFoundError("Database is not initialized; run the seed command for demo data.")
        if not read_only:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.backend == 'sqlite':
            return (sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)
                    if read_only else sqlite3.connect(str(self.path)))
        try:
            import duckdb
        except ImportError as exc:
            raise RuntimeError("DuckDB missing: pip install -e '.[dev]'") from exc
        return duckdb.connect(str(self.path), read_only=read_only)

    def ensure_seeded(self):
        """First-run bootstrap only; never overwrite an existing valid database."""
        with self._lock:
            if not self.path.exists():
                self.seed()
                return
            try:
                conn = self.connect(read_only=True)
                try:
                    for table in TABLES:
                        conn.execute(f'SELECT 1 FROM "{table}" LIMIT 1')
                finally:
                    conn.close()
            except Exception:
                self.seed()

    def seed(self, today: date | None = None):
        """Compatibility entry point for explicit demo initialization."""
        from .demo_data import seed_demo
        with self._lock:
            try:
                return seed_demo(self, today)
            except Exception:
                for suffix in ('', '.wal'):
                    candidate = Path(str(self.path) + suffix)
                    if candidate.exists():
                        candidate.unlink(missing_ok=True)
                return seed_demo(self, today)

    def _fetch(self, sql, params=None):
        with self._lock:
            conn = self.connect(read_only=True)
            try:
                cursor = conn.execute(sql, params or [])
                columns = [col[0] for col in cursor.description]
                rows = cursor.fetchall()
                return [dict(zip(columns, (
                    float(v) if isinstance(v, Decimal) else v.isoformat() if isinstance(v, date) else v
                    for v in row))) for row in rows]
            finally:
                conn.close()

    def run(self, plan: CompiledQuery):
        return self._fetch(plan.sql, plan.parameters)

    def execute_many(self, plans, catalog=None):
        """All comparison queries and optional data export see one transaction snapshot."""
        from .catalog import identifier
        with self._lock:
            conn = self.connect(read_only=True)
            try:
                conn.execute('BEGIN TRANSACTION')
                results = []
                for plan in plans:
                    cursor = conn.execute(plan.sql, plan.parameters)
                    columns = [c[0] for c in cursor.description]
                    results.append([dict(zip(columns, [
                        float(v) if isinstance(v, Decimal) else v.isoformat() if isinstance(v, date) else v
                        for v in row])) for row in cursor.fetchall()])
                snapshot = []
                if catalog:
                    for dataset in catalog.datasets.values():
                        fields = dataset['fields']
                        columns = ', '.join(identifier(f['name']) for f in fields)
                        cursor = conn.execute(f'SELECT {columns} FROM {identifier(dataset["source"])}')
                        column_types = [str(c[1]) for f, c in zip(fields, cursor.description)]
                        rows = cursor.fetchall()
                        if self.backend == 'sqlite':
                            types = {r[1]: r[2] for r in conn.execute(f'PRAGMA table_info({identifier(dataset["source"])})').fetchall()}
                            column_types = [types[f['name']] for f in fields]
                        snapshot.append({'table': dataset['source'], 'fields': fields, 'column_types': column_types,
                                         'rows': [[str(v) if isinstance(v, (Decimal, date)) else v
                                                   for v in row] for row in rows]})
                conn.commit()
                return results, snapshot
            finally:
                conn.close()

    def overview(self):
        with self._lock:
            conn = self.connect(read_only=True)
            try:
                tables = [
                    {'name': table, 'row_count': int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])}
                    for table in TABLES
                ]
                return {'backend': self.backend, 'path': str(self.path), 'tables': tables}
            finally:
                conn.close()

    def preview(self, table: str, limit: int = 20):
        if table not in TABLES:
            raise ValueError('invalid table; only demo fixture tables are accessible')
        if not (1 <= limit <= 100):
            raise ValueError('limit must be between 1 and 100')
        return self._fetch(f'SELECT * FROM "{table}" ORDER BY 1 LIMIT ?', [limit])
