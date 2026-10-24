"""Keep QA and retired save owners out of public standings, including slots.

The random namespaces below are reserved by the hosted verification tools.
Other trusted fixtures can be explicitly marked in rating_exclusions(account).
Public queries never create or modify that table.
"""
import re

QA_LOGIN = re.compile(r'(?:q(?:[a-z]|er)[0-9a-f]{8}[a-h]|webqa_[0-9a-f]{10}|qa_mail_[0-9a-f]{12}|uon[0-9a-f]{12}[ab])\Z')


def excluded(db, owner, *, include_retired=True):
    from .character_lifecycle import retired
    if include_retired and retired(db, owner):
        return True
    login = owner.split(':')[1] if owner.startswith('@character:') else owner
    if QA_LOGIN.fullmatch(login):
        return True
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='rating_exclusions'").fetchone():
        return bool(db.execute('SELECT 1 FROM rating_exclusions WHERE account IN (?,?)', (owner, login)).fetchone())
    return False
