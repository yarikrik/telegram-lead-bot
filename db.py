"""Работа с базой SQLite.

Используется стандартный sqlite3, а запросы выполняются в отдельном потоке
(asyncio.to_thread), чтобы не блокировать бота. Лишних зависимостей нет.
"""
import asyncio
import csv
import io
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id     INTEGER PRIMARY KEY,
    username    TEXT,
    full_name   TEXT,
    joined_at   TEXT NOT NULL,
    is_active   INTEGER NOT NULL DEFAULT 1   -- 0, если пользователь заблокировал бота
);
CREATE TABLE IF NOT EXISTS downloads (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(user_id),
    material_id TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_downloads_material ON downloads(material_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        self._lock = asyncio.Lock()

    async def _run(self, func, *args):
        async with self._lock:
            return await asyncio.to_thread(func, *args)

    # ---------- пользователи ----------
    def _add_user(self, user_id: int, username: str | None, full_name: str) -> bool:
        cur = self._conn.execute(
            "INSERT OR IGNORE INTO users (user_id, username, full_name, joined_at) VALUES (?, ?, ?, ?)",
            (user_id, username, full_name, _now()),
        )
        is_new = cur.rowcount == 1
        if not is_new:  # обновим имя и снова отметим активным (вдруг разблокировал бота)
            self._conn.execute(
                "UPDATE users SET username = ?, full_name = ?, is_active = 1 WHERE user_id = ?",
                (username, full_name, user_id),
            )
        self._conn.commit()
        return is_new

    async def add_user(self, user_id: int, username: str | None, full_name: str) -> bool:
        """Сохраняет пользователя. Возвращает True, если он новый."""
        return await self._run(self._add_user, user_id, username, full_name)

    def _set_inactive(self, user_id: int) -> None:
        self._conn.execute("UPDATE users SET is_active = 0 WHERE user_id = ?", (user_id,))
        self._conn.commit()

    async def set_inactive(self, user_id: int) -> None:
        await self._run(self._set_inactive, user_id)

    def _active_user_ids(self) -> list[int]:
        rows = self._conn.execute("SELECT user_id FROM users WHERE is_active = 1").fetchall()
        return [r["user_id"] for r in rows]

    async def active_user_ids(self) -> list[int]:
        return await self._run(self._active_user_ids)

    # ---------- выдачи материалов ----------
    def _log_download(self, user_id: int, material_id: str) -> None:
        self._conn.execute(
            "INSERT INTO downloads (user_id, material_id, created_at) VALUES (?, ?, ?)",
            (user_id, material_id, _now()),
        )
        self._conn.commit()

    async def log_download(self, user_id: int, material_id: str) -> None:
        await self._run(self._log_download, user_id, material_id)

    # ---------- статистика ----------
    def _stats(self) -> dict:
        day_ago = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(timespec="seconds")
        one = lambda q, *a: self._conn.execute(q, a).fetchone()[0]  # noqa: E731
        return {
            "total": one("SELECT COUNT(*) FROM users"),
            "active": one("SELECT COUNT(*) FROM users WHERE is_active = 1"),
            "new_day": one("SELECT COUNT(*) FROM users WHERE joined_at >= ?", day_ago),
            "new_week": one("SELECT COUNT(*) FROM users WHERE joined_at >= ?", week_ago),
            "downloads": {
                r["material_id"]: r["cnt"]
                for r in self._conn.execute(
                    "SELECT material_id, COUNT(*) AS cnt FROM downloads GROUP BY material_id ORDER BY cnt DESC"
                )
            },
        }

    async def stats(self) -> dict:
        return await self._run(self._stats)

    def _export_csv(self) -> bytes:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["user_id", "username", "full_name", "joined_at", "is_active", "downloads"])
        rows = self._conn.execute(
            """SELECT u.user_id, u.username, u.full_name, u.joined_at, u.is_active,
                      COUNT(d.id) AS downloads
               FROM users u LEFT JOIN downloads d ON d.user_id = u.user_id
               GROUP BY u.user_id ORDER BY u.joined_at"""
        )
        for r in rows:
            writer.writerow(list(r))
        # BOM, чтобы Excel правильно открыл кириллицу
        return ("﻿" + buf.getvalue()).encode("utf-8")

    async def export_csv(self) -> bytes:
        return await self._run(self._export_csv)

    def close(self) -> None:
        self._conn.close()
