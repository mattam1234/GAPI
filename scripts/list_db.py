import sys
from sqlalchemy import inspect
import database

if not getattr(database, 'engine', None):
    print('NO_ENGINE')
    sys.exit(0)
ins = inspect(database.engine)
print('TABLES:', ins.get_table_names())
Session = database.SessionLocal
s = Session()
for t in ['users','ignored_games','achievements','game_library_cache','achievement_hunts','multiuser_sessions']:
    try:
        cnt = s.execute(f"SELECT count(*) FROM {t}").scalar()
        print(f"{t}: {cnt}")
    except Exception as e:
        print(f"{t}: ERROR {e}")
s.close()