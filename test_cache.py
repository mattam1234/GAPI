import database
from datetime import datetime

db = database.SessionLocal()
admin = db.query(database.User).filter(database.User.username == 'admin').first()
games = db.query(database.GameLibraryCache).filter(
    database.GameLibraryCache.user_id == admin.id
).all()

print(f'Count: {len(games)}')
if games:
    print(f'First game cached_at: {games[0].cached_at}')
    print(f'Now: {datetime.utcnow()}')
    age_seconds = (datetime.utcnow() - games[0].cached_at).total_seconds()
    print(f'Age (seconds): {age_seconds}')
    print(f'Age (hours): {age_seconds / 3600}')

# Test get_cached_library
cached = database.get_cached_library(db, 'admin')
print(f'\nget_cached_library returned: {len(cached)} games')

db.close()
