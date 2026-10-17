"""Separate shared storage failure from an individual request/match failure."""
import sqlite3


def storage_failure(error):
    if isinstance(error,(FileNotFoundError,PermissionError)):return True
    if not isinstance(error,sqlite3.Error):return False
    if isinstance(error,sqlite3.IntegrityError):return False
    code=getattr(error,'sqlite_errorcode',0) or 0
    if code&255 in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED):return False
    if isinstance(error,sqlite3.OperationalError) and str(error).lower() in (
        'database is locked','database table is locked','database is busy'):return False
    return True
