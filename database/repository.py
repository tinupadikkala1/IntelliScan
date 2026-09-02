"""Repository layer.

Thin CRUD helpers over the SQLAlchemy models. Each method opens its own
session so callers never manage transactions directly. This is the single
place the rest of the application talks to the database.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

from sqlalchemy import select

from database.engine import Database
from database.models import (
    Favorite,
    File,
    Folder,
    Log,
    Plugin,
    Recent,
    SchemaVersion,
    Setting,
    Task,
)


def _now() -> datetime:
    return datetime.now()


class Repository:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ------------------------------------------------------------------ #
    # Favorites
    # ------------------------------------------------------------------ #
    def add_favorite(self, path: str, name: Optional[str] = None) -> Favorite:
        with self.db.session() as s:
            existing = s.execute(
                select(Favorite).where(Favorite.path == path)
            ).scalar_one_or_none()
            if existing:
                return existing
            fav = Favorite(path=path, name=name or path)
            s.add(fav)
            s.commit()
            return fav

    def remove_favorite(self, path: str) -> None:
        with self.db.session() as s:
            fav = s.execute(
                select(Favorite).where(Favorite.path == path)
            ).scalar_one_or_none()
            if fav:
                s.delete(fav)
                s.commit()

    def list_favorites(self) -> list[Favorite]:
        with self.db.session() as s:
            return list(s.execute(select(Favorite)).scalars().all())

    # ------------------------------------------------------------------ #
    # Recent
    # ------------------------------------------------------------------ #
    def add_recent(self, path: str, name: Optional[str] = None, limit: int = 50) -> None:
        with self.db.session() as s:
            rec = Recent(path=path, name=name or path)
            s.add(rec)
            s.commit()
        self._trim_recent(limit)

    def _trim_recent(self, limit: int) -> None:
        with self.db.session() as s:
            rows = s.execute(select(Recent).order_by(Recent.opened.desc())).scalars().all()
            for old in rows[limit:]:
                s.delete(old)
            s.commit()

    def list_recent(self, limit: int = 20) -> list[Recent]:
        with self.db.session() as s:
            return list(
                s.execute(select(Recent).order_by(Recent.opened.desc()).limit(limit))
                .scalars()
                .all()
            )

    # ------------------------------------------------------------------ #
    # Settings (mirrored copy in DB; config JSON remains source of truth)
    # ------------------------------------------------------------------ #
    def set_setting(self, key: str, value: str) -> None:
        with self.db.session() as s:
            row = s.get(Setting, key)
            if row is None:
                row = Setting(key=key, value=value)
                s.add(row)
            else:
                row.value = value
            s.commit()

    def get_setting(self, key: str) -> Optional[str]:
        with self.db.session() as s:
            row = s.get(Setting, key)
            return row.value if row else None

    # ------------------------------------------------------------------ #
    # Files / Folders
    # ------------------------------------------------------------------ #
    def upsert_file(self, **fields) -> File:
        path = fields["path"]
        if "parent" not in fields:
            fields["parent"] = os.path.dirname(path)
        with self.db.session() as s:
            f = s.execute(select(File).where(File.path == path)).scalar_one_or_none()
            if f is None:
                f = File(**fields)
                s.add(f)
            else:
                for k, v in fields.items():
                    setattr(f, k, v)
            s.commit()
            return f

    def upsert_folder(self, **fields) -> Folder:
        path = fields["path"]
        if "parent" not in fields:
            fields["parent"] = os.path.dirname(path)
        with self.db.session() as s:
            f = s.execute(select(Folder).where(Folder.path == path)).scalar_one_or_none()
            if f is None:
                f = Folder(**fields)
                s.add(f)
            else:
                for k, v in fields.items():
                    setattr(f, k, v)
            s.commit()
            return f

    def list_files(self, parent: Optional[str] = None) -> list[File]:
        with self.db.session() as s:
            stmt = select(File)
            if parent is not None:
                stmt = stmt.where(File.parent == parent)
            return list(s.execute(stmt).scalars().all())

    # ------------------------------------------------------------------ #
    # Tasks
    # ------------------------------------------------------------------ #
    def add_task(self, task_id: str, type_: str, total: int = 0) -> Task:
        with self.db.session() as s:
            t = Task(task_id=task_id, type=type_, total=total)
            s.add(t)
            s.commit()
            return t

    def update_task(self, task_id: str, **fields) -> None:
        with self.db.session() as s:
            t = s.execute(select(Task).where(Task.task_id == task_id)).scalar_one_or_none()
            if t is None:
                return
            for k, v in fields.items():
                setattr(t, k, v)
            s.commit()

    def list_tasks(self) -> list[Task]:
        with self.db.session() as s:
            return list(s.execute(select(Task)).scalars().all())

    def prune_tasks(self, keep: int = 1000, max_age_days: int = 30) -> int:
        """Prune old completed/failed tasks (Batch 7 task-table hygiene).

        Keeps at most ``keep`` recent tasks and drops rows older than
        ``max_age_days``, while always preserving active/in-progress tasks.
        Returns the number of rows removed.
        """
        from datetime import datetime, timedelta

        cutoff = datetime.now() - timedelta(days=max_age_days)
        removed = 0
        with self.db.session() as s:
            # 1) Age-based: remove finished tasks older than the cutoff.
            stale = s.execute(
                select(Task).where(
                    Task.finished.isnot(None),
                    Task.finished < cutoff,
                )
            ).scalars().all()
            for row in stale:
                s.delete(row)
                removed += 1
            # 2) Count-based: keep only the ``keep`` most recent finished tasks.
            finished = s.execute(
                select(Task).where(Task.finished.isnot(None))
                .order_by(Task.created.desc())
            ).scalars().all()
            for row in finished[keep:]:
                s.delete(row)
                removed += 1
            s.commit()
        return removed

    # ------------------------------------------------------------------ #
    # Plugins
    # ------------------------------------------------------------------ #
    def register_plugin(self, name: str, version: str, enabled: bool = True) -> Plugin:
        with self.db.session() as s:
            p = s.execute(select(Plugin).where(Plugin.name == name)).scalar_one_or_none()
            if p is None:
                p = Plugin(name=name, version=version, enabled=enabled)
                s.add(p)
            else:
                p.version = version
                p.enabled = enabled
            s.commit()
            return p

    def set_plugin_enabled(self, name: str, enabled: bool) -> None:
        with self.db.session() as s:
            p = s.execute(select(Plugin).where(Plugin.name == name)).scalar_one_or_none()
            if p:
                p.enabled = enabled
                s.commit()

    def list_plugins(self) -> list[Plugin]:
        with self.db.session() as s:
            return list(s.execute(select(Plugin)).scalars().all())

    # ------------------------------------------------------------------ #
    # Logs
    # ------------------------------------------------------------------ #
    def add_log(self, level: str, logger: str, message: str) -> None:
        with self.db.session() as s:
            s.add(Log(level=level, logger=logger, message=message))
            s.commit()

    def list_logs(self, limit: int = 200) -> list[Log]:
        with self.db.session() as s:
            return list(
                s.execute(select(Log).order_by(Log.timestamp.desc()).limit(limit))
                .scalars()
                .all()
            )

    # ------------------------------------------------------------------ #
    # Schema version
    # ------------------------------------------------------------------ #
    def set_schema_version(self, version: int) -> None:
        with self.db.session() as s:
            row = s.execute(select(SchemaVersion)).scalar_one_or_none()
            if row is None:
                s.add(SchemaVersion(version=version))
            else:
                row.version = version
            s.commit()
