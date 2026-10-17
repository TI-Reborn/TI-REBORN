"""Generate a reviewable creation diff without changing CharacterStore."""
from pathlib import Path
import difflib
ROOT=Path(__file__).resolve().parents[1]


def main():
    path=ROOT/'tio/characters.py';before=path.read_text();after=before
    substitutions=(('from .db_transaction import connect','from .db_transaction import connect, transaction'),
        ("        with closing(connect(self.path)) as db, db:\n            db.execute('BEGIN IMMEDIATE')",'        with transaction(self.path) as db:'),
        ("            db.execute('INSERT INTO characters VALUES (?,?,?,?,?)',(owner,1,request.name_bytes,key,raw))",
         "            db.execute('INSERT INTO characters VALUES (?,?,?,?,?)',(owner,1,request.name_bytes,key,raw))\n            from .onboarding import initialize_created\n            initialize_created(self.path,owner)"))
    for source,target in substitutions:
        if after.count(source)!=1:raise ValueError('Review CharacterStore before generating creation patch')
        after=after.replace(source,target,1)
    patch=''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='a/tio/characters.py',tofile='b/tio/characters.py'))
    (ROOT/'deploy/tutorial_character_creation.patch').write_text(patch,encoding='utf-8')
    print('Creation diff prepared; CharacterStore is unchanged')


if __name__=='__main__':main()
