import database

db = database.SessionLocal()
users = db.query(database.User).all()
for u in users:
    count = db.query(database.GameLibraryCache).filter(
        database.GameLibraryCache.user_id == u.id
    ).count()
    print(f'{u.username}: {count} games')

# Also check GameLibraryCache table
all_games = db.query(database.GameLibraryCache).all()
if all_games:
    print(f"\nFirst game: user_id={all_games[0].user_id}, user={db.query(database.User).filter(database.User.id == all_games[0].user_id).first().username if all_games[0].user_id else 'None'}")

db.close()
