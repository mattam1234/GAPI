import database

db = database.SessionLocal()

# Get both users
admin = db.query(database.User).filter(database.User.username == 'admin').first()
mattam = db.query(database.User).filter(database.User.username == 'mattam').first()

if not admin or not mattam:
    print("Users not found!")
    db.close()
    exit(1)

# Get mattam's games
mattam_games = db.query(database.GameLibraryCache).filter(
    database.GameLibraryCache.user_id == mattam.id
).all()

print(f"Copying {len(mattam_games)} games from mattam to admin...")

# Copy each game to admin
for game in mattam_games:
    new_game = database.GameLibraryCache(
        user_id=admin.id,
        app_id=game.app_id,
        game_name=game.game_name,
        platform=game.platform,
        playtime_hours=game.playtime_hours,
        last_played=game.last_played
    )
    db.add(new_game)

db.commit()
print("Done! Games copied successfully.")
db.close()
