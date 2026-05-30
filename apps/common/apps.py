"""Common app: cross-cutting concerns (exceptions, pagination, DB tuning).

The AppConfig.ready() hook wires SQLite PRAGMAs so dev installs survive the
"database is locked" contention from concurrent heartbeats + generation
writes. Importing this module also exposes the package as a Django app so
the ready() hook actually fires.
"""
from django.apps import AppConfig
from django.db import connection
from django.db.backends.signals import connection_created


def _apply_sqlite_pragmas(sender, connection, **_):
    """Enable WAL + a real busy_timeout on every new SQLite connection.

    Runs once per new connection (Django keeps one per worker thread).
    WAL is sticky on the database file, so this is idempotent.
    """
    if connection.vendor != "sqlite":
        return
    with connection.cursor() as cursor:
        # journal_mode=WAL — readers and writers no longer block each other
        cursor.execute("PRAGMA journal_mode=WAL;")
        # synchronous=NORMAL — faster commits, still safe with WAL
        cursor.execute("PRAGMA synchronous=NORMAL;")
        # busy_timeout in milliseconds — block up to 30s waiting for the
        # write lock instead of immediately raising "database is locked".
        cursor.execute("PRAGMA busy_timeout=30000;")
        # foreign_keys ON to match production Postgres semantics
        cursor.execute("PRAGMA foreign_keys=ON;")


class CommonConfig(AppConfig):
    name = "apps.common"
    verbose_name = "Common"

    def ready(self):
        connection_created.connect(_apply_sqlite_pragmas)
        # Apply to the already-open default connection so the very first
        # request after server start (which reuses this connection) also
        # has WAL + busy_timeout in effect.
        try:
            _apply_sqlite_pragmas(sender=None, connection=connection)
        except Exception:
            # Best-effort; the signal handler will catch subsequent ones.
            pass
