#!/usr/bin/env python3
"""
GAPI Discord Bot
Discord integration for multi-user game picking with voting and co-op support.
"""

import discord
from discord import app_commands
import json
import os
import sys
import asyncio
from typing import Dict, List, Set, Optional
from datetime import datetime, timedelta
import multiuser
from dotenv import load_dotenv
import database

# Fix Windows console encoding for emoji support
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except (AttributeError, Exception):
        # Fallback for older Python versions or if reconfigure fails
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


class GAPIBot(discord.Client):
    """Discord bot for GAPI game picking"""
    
    def __init__(self, config: Dict):
        intents = discord.Intents.default()
        # Note: message_content and members are privileged intents that require
        # enabling in Discord Developer Portal. Since this bot uses slash commands,
        # we don't need message_content. Members intent is optional.
        # intents.message_content = True  # Not needed for slash commands
        # intents.members = True  # Only needed if you want to list server members
        
        super().__init__(intents=intents)
        
        self.tree = app_commands.CommandTree(self)
        
        self.config = config
        self.steam_api_key = config.get('steam_api_key')
        self.multi_picker = multiuser.MultiUserPicker(config)
        
        # Active voting sessions
        self.active_votes: Dict[int, Dict] = {}  # channel_id -> vote_data
        self.private_vote_lobbies: Dict[int, Dict] = {}  # channel_id -> lobby data
        
        # Track polls and votes by message ID for reaction-based joining
        self.active_polls: Dict[int, Dict] = {}  # message_id -> poll_data
        self.poll_participants: Dict[int, Set[int]] = {}  # message_id -> set of user_ids who joined
        
        # Discord user to Steam ID mapping (loaded from database)
        self.user_mappings: Dict[int, str] = {}  # discord_user_id -> steam_id
        self.load_user_mappings()
        
        # Add commands
        self.setup_commands()
    
    def load_user_mappings(self):
        """Load Discord user to Steam ID mappings from PostgreSQL database"""
        if not database.SessionLocal:
            print("❌ Database not available - cannot load Discord user mappings")
            print("   Ensure PostgreSQL is configured and accessible via .env DATABASE_URL")
            self.user_mappings = {}
            return
        
        try:
            # Load from PostgreSQL database
            db = database.SessionLocal()
            try:
                users = db.query(database.User).filter(database.User.discord_id.isnot(None)).all()
                self.user_mappings = {}
                for user in users:
                    if user.discord_id and user.steam_id:
                        try:
                            self.user_mappings[int(user.discord_id)] = user.steam_id
                        except ValueError:
                            print(f"⚠️  Invalid discord_id for user {user.username}: {user.discord_id}")
                print(f"✅ Loaded {len(self.user_mappings)} Discord user mappings from database")
            finally:
                db.close()
        except Exception as e:
            print(f"❌ Error loading user mappings from database: {e}")
            self.user_mappings = {}
    
    def save_user_mappings(self):
        """Save Discord user to Steam ID mappings to PostgreSQL database"""
        if not database.SessionLocal:
            print("❌ Database not available - cannot save Discord user mappings")
            return
        
        try:
            # Save to PostgreSQL database only
            db = database.SessionLocal()
            try:
                for discord_id, steam_id in self.user_mappings.items():
                    # Check if user exists with this steam_id
                    user = db.query(database.User).filter(
                        database.User.steam_id == steam_id
                    ).first()
                    
                    if user:
                        # Update existing user with Discord ID
                        user.discord_id = str(discord_id)
                    else:
                        # Check if user exists with this discord_id
                        user = db.query(database.User).filter(
                            database.User.discord_id == str(discord_id)
                        ).first()
                        if user:
                            # Update steam_id
                            user.steam_id = steam_id
                
                db.commit()
                print(f"✅ Saved {len(self.user_mappings)} Discord user mappings to database")
            except Exception as e:
                db.rollback()
                print(f"❌ Error saving to database: {e}")
            finally:
                db.close()
        except Exception as e:
            print(f"❌ Error saving user mappings: {e}")

    def _resolve_linked_user_name(self, discord_user_id: int) -> Optional[str]:
        """Resolve a Discord user ID to a MultiUserPicker user name."""
        steam_id = self.user_mappings.get(discord_user_id)
        if not steam_id:
            return None
        for user in self.multi_picker.users:
            if str(user.get('discord_id', '')) == str(discord_user_id):
                return str(user.get('name') or '')
            if user.get('steam_id') and str(user.get('steam_id')) == str(steam_id):
                return str(user.get('name') or '')
            platforms = user.get('platforms') if isinstance(user.get('platforms'), dict) else {}
            if str(platforms.get('steam', '')) == str(steam_id):
                return str(user.get('name') or '')
        return None

    def _filter_vote_candidates(self, games: List[Dict], genre: Optional[str] = None,
                                min_metacritic: Optional[int] = None,
                                min_release_year: Optional[int] = None) -> List[Dict]:
        """Filter to multiplayer/co-op games with optional additional constraints."""
        coop_games = self.multi_picker.filter_coop_games(games)
        if not coop_games:
            return []
        if genre or min_metacritic is not None or min_release_year is not None:
            genres = [genre] if genre else None
            coop_games = self.multi_picker.filter_games(
                coop_games,
                genres=genres,
                min_metacritic=min_metacritic,
                min_release_year=min_release_year,
            )
        return coop_games

    async def _countdown_timer(self, duration: int, message_callback):
        """Send countdown updates every 10 seconds."""
        elapsed = 0
        while elapsed < duration:
            await asyncio.sleep(10)
            elapsed += 10
            if elapsed < duration:
                remaining = duration - elapsed
                await message_callback(f"⏱️ Vote continues... **{remaining}s** remaining")

    async def _get_game_embed(self, game: Dict, app_id: str, total_votes: int = 0) -> discord.Embed:
        """Create a rich embed for a game with description, image, and links."""
        game_name = game.get('name', 'Unknown Game')
        
        embed = discord.Embed(
            title=f"🎮 Let's play: {game_name}!",
            color=discord.Color.gold()
        )
        
        # Add game image if available
        if app_id and app_id != '__NOTA__':
            embed.set_thumbnail(url=f"https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/header.jpg")
        
        # Add description
        description = game.get('short_description') or game.get('description', '')
        if description:
            # Truncate to 300 chars if too long
            if len(description) > 300:
                description = description[:297] + "..."
            embed.add_field(name="About", value=description, inline=False)
        
        # Add metadata
        if app_id and app_id != '__NOTA__':
            embed.add_field(name="App ID", value=str(app_id), inline=True)
            
            # Release date
            release_date = game.get('release_date')
            if release_date:
                if isinstance(release_date, dict):
                    release_date = release_date.get('date', '')
                if release_date:
                    embed.add_field(name="Release Date", value=str(release_date), inline=True)
            
            # Metacritic score
            metacritic = game.get('metacritic')
            if metacritic:
                if isinstance(metacritic, dict):
                    score = metacritic.get('score')
                    if score:
                        embed.add_field(name="Metacritic", value=f"{score}/100", inline=True)
        
        if total_votes > 0:
            embed.add_field(name="Total Votes", value=str(total_votes), inline=True)
        
        # Add links
        if app_id and app_id != '__NOTA__':
            embed.add_field(
                name="🔗 Links",
                value=f"[Steam Store](https://store.steampowered.com/app/{app_id}/) | "
                      f"[SteamDB](https://steamdb.info/app/{app_id}/) | "
                      f"[AllKeyShop](https://www.allkeyshop.com/blog/catalogue/{app_id}/)",
                inline=False
            )
        
        return embed

    async def _collect_private_vote(self, user: discord.User, candidate_games: List[Dict],
                                    timeout_seconds: int) -> Optional[str]:
        """DM a ballot to one user and return selected app_id or None."""
        app_ids = [str(g.get('appid') or g.get('app_id') or g.get('game_id') or '') for g in candidate_games]
        numbered = []
        for idx, game in enumerate(candidate_games, start=1):
            numbered.append(f"{idx}. {game.get('name', 'Unknown')} (ID: {app_ids[idx - 1]})")
        none_option_num = len(candidate_games) + 1
        numbered.append(f"{none_option_num}. None of these")

        dm_text = (
            "🗳️ Private GAPI vote is open!\n"
            f"Reply with the **number** or **app ID** of your choice within {timeout_seconds} seconds.\n"
            "You can also vote for **None of these**.\n\n"
            + "\n".join(numbered)
        )
        try:
            dm_channel = await user.create_dm()
            await dm_channel.send(dm_text)
        except Exception:
            return None

        def _check(msg: discord.Message) -> bool:
            return msg.author.id == user.id and isinstance(msg.channel, discord.DMChannel)

        try:
            msg = await self.wait_for('message', timeout=timeout_seconds, check=_check)
        except asyncio.TimeoutError:
            return None

        content = (msg.content or '').strip()
        if content.isdigit():
            choice_num = int(content)
            if 1 <= choice_num <= len(app_ids):
                return app_ids[choice_num - 1]
            if choice_num == none_option_num:
                return '__NOTA__'
        if content.lower() in {'none', 'none of these', 'nota', 'nope'}:
            return '__NOTA__'
        if content in app_ids:
            return content
        return None

    async def _run_private_vote(self, channel: discord.abc.Messageable, lobby: Dict) -> None:
        """Run private vote: wait join window, DM joined users, tally, then announce."""
        await asyncio.sleep(lobby['join_duration'])
        channel_id = lobby['channel_id']

        latest = self.private_vote_lobbies.get(channel_id)
        if not latest or latest.get('lobby_id') != lobby.get('lobby_id'):
            return
        self.private_vote_lobbies.pop(channel_id, None)

        joined_ids: Set[int] = set(latest.get('joined_ids', set()))
        if len(joined_ids) < 2:
            await channel.send("❌ Private vote canceled: at least 2 joined users are required.")
            return

        participant_names: List[str] = []
        participant_users: List[discord.User] = []
        for uid in joined_ids:
            name = self._resolve_linked_user_name(uid)
            if not name:
                continue
            try:
                user_obj = await self.fetch_user(uid)
            except Exception:
                continue
            participant_names.append(name)
            participant_users.append(user_obj)

        if len(participant_names) < 2:
            await channel.send("❌ Private vote canceled: joined users must be linked to Steam first.")
            return

        common_games = self.multi_picker.find_common_games(participant_names)
        if not common_games:
            await channel.send("❌ No common games found among joined users.")
            return

        # Run blocking filter operation in thread to avoid blocking event loop
        try:
            filtered_games = await asyncio.to_thread(
                self._filter_vote_candidates,
                common_games,
                genre=latest.get('genre'),
                min_metacritic=latest.get('min_metacritic'),
            )
        except Exception as e:
            await channel.send(f"❌ Error filtering games: {str(e)}")
            return
            
        if not filtered_games:
            await channel.send("❌ No co-op/multiplayer games matched the selected filters.")
            return

        import random as _random
        max_restarts = 2
        excluded_app_ids: Set[str] = set()
        candidate_count = max(2, min(int(latest.get('candidates', 8)), 20))

        for attempt in range(max_restarts + 1):
            candidate_pool = [
                g for g in filtered_games
                if str(g.get('appid') or g.get('app_id') or g.get('game_id') or '') not in excluded_app_ids
            ]
            if len(candidate_pool) < 2:
                candidate_pool = filtered_games

            candidate_games = _random.sample(candidate_pool, min(candidate_count, len(candidate_pool)))
            session_candidates = list(candidate_games) + [{'appid': '__NOTA__', 'name': 'None of these'}]

            session = self.multi_picker.create_voting_session(
                session_candidates,
                voters=participant_names,
                duration=latest.get('vote_duration', 60),
            )

            await channel.send(
                f"📨 Private vote started for {len(participant_users)} users. "
                f"Ballots were sent via DM and close in {latest.get('vote_duration', 60)}s."
                + (f" (Restart round {attempt})" if attempt > 0 else "")
            )

            vote_tasks = [
                self._collect_private_vote(u, candidate_games, latest.get('vote_duration', 60))
                for u in participant_users
            ]
            vote_results = await asyncio.gather(*vote_tasks, return_exceptions=True)

            for name, vote in zip(participant_names, vote_results):
                if isinstance(vote, Exception) or not vote:
                    continue
                session.cast_vote(name, vote)

            session.close()
            results = session.get_results()

            total_votes = sum(r.get('count', 0) for r in results.values())
            nota_count = results.get('__NOTA__', {}).get('count', 0)

            lines = ["🗳️ **Private Vote Results**"]
            for game in candidate_games:
                app_id = str(game.get('appid') or game.get('app_id') or '')
                result = results.get(app_id, {'count': 0, 'voters': []})
                voters = result.get('voters', [])
                voter_text = f" ({', '.join(voters)})" if voters else ""
                lines.append(f"• {game.get('name', 'Unknown')} — {result.get('count', 0)} vote(s){voter_text}")
            nota_voters = results.get('__NOTA__', {}).get('voters', [])
            nota_voter_text = f" ({', '.join(nota_voters)})" if nota_voters else ""
            lines.append(f"• None of these — {nota_count} vote(s){nota_voter_text}")

            await channel.send("\n".join(lines))

            if total_votes > 0 and nota_count > (total_votes / 2):
                if attempt < max_restarts:
                    for g in candidate_games:
                        excluded_app_ids.add(str(g.get('appid') or g.get('app_id') or g.get('game_id') or ''))
                    await channel.send("🔁 Majority voted **None of these**. Restarting vote with a new game list…")
                    continue
                await channel.send("❌ Vote ended with majority 'None of these' after retries.")
                return

            # Select winner from non-NOTA candidates.
            winner = None
            winner_count = -1
            for game in candidate_games:
                app_id = str(game.get('appid') or game.get('app_id') or '')
                count = results.get(app_id, {}).get('count', 0)
                if count > winner_count:
                    winner = game
                    winner_count = count

            if not winner or winner_count <= 0:
                await channel.send("❌ Vote ended with no winner.")
                return

            winner_app_id = winner.get('appid') or winner.get('app_id')
            embed = await self._get_game_embed(winner, str(winner_app_id), total_votes)
            await channel.send(embed=embed)
            return

    async def _start_public_vote_round(self, channel: discord.abc.Messageable, participants: List[str],
                                       duration: int, num_candidates: int,
                                       restart_count: int = 0, everyone_mention: bool = False,
                                       genre: Optional[str] = None, min_metacritic: Optional[int] = None,
                                       min_release_year: Optional[int] = None) -> bool:
        """Start one public reaction-vote round with a NOTA option."""
        common_games = self.multi_picker.find_common_games(participants)
        if not common_games:
            await channel.send("❌ No common games found among linked users.")
            return False

        # Run blocking filter operation in thread to avoid blocking event loop
        try:
            common_games = await asyncio.to_thread(
                self._filter_vote_candidates,
                common_games,
                genre=genre,
                min_metacritic=min_metacritic,
                min_release_year=min_release_year
            )
        except Exception as e:
            await channel.send(f"❌ Error filtering co-op games: {str(e)}")
            return False
            
        if not common_games:
            await channel.send("❌ No common co-op/multiplayer games found among linked users.")
            return False

        import random as _random
        candidate_games = _random.sample(common_games, min(num_candidates, len(common_games)))
        session_candidates = list(candidate_games) + [{'appid': '__NOTA__', 'name': 'None of these'}]
        session = self.multi_picker.create_voting_session(
            session_candidates,
            voters=participants,
            duration=duration,
        )

        NUMBER_EMOJIS = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣', '🔟']
        nota_emoji = '🚫'
        
        filter_bits = ["Co-op / multiplayer games only"]
        if genre:
            filter_bits.append(f"genre={genre}")
        if min_metacritic is not None:
            filter_bits.append(f"metacritic>={min_metacritic}")
        if min_release_year is not None:
            filter_bits.append(f"released>={min_release_year}")
        
        description_lines = [
            f"React with the number emoji to vote! Voting ends in **{duration} seconds**.",
            f"Filters: {', '.join(filter_bits)}",
            ""
        ]
        for i, game in enumerate(candidate_games):
            description_lines.append(f"{NUMBER_EMOJIS[i]}  **{game.get('name', 'Unknown')}**")
        description_lines.append(f"{nota_emoji}  **None of these**")

        embed = discord.Embed(
            title="🗳️ Vote for a Game!" + (f" (Restart {restart_count})" if restart_count else ""),
            description="\n".join(description_lines),
            color=discord.Color.green(),
        )
        embed.set_footer(text=f"Session ID: {session.session_id[:8]} | Vote with number emojis!")
        
        mention_prefix = "@everyone " if everyone_mention else ""
        vote_msg = await channel.send(mention_prefix, embed=embed)

        for i in range(len(candidate_games)):
            await vote_msg.add_reaction(NUMBER_EMOJIS[i])
        await vote_msg.add_reaction(nota_emoji)

        self.active_votes[channel.id] = {
            'session': session,
            'message': vote_msg,
            'candidate_games': candidate_games,
            'emojis': NUMBER_EMOJIS[:len(candidate_games)],
            'nota_emoji': nota_emoji,
            'participants': participants,
            'duration': duration,
            'num_candidates': num_candidates,
            'restart_count': restart_count,
            'max_restarts': 2,
            'everyone_mention': everyone_mention,
            'genre': genre,
            'min_metacritic': min_metacritic,
            'min_release_year': min_release_year,
        }

        # Countdown timer
        async def send_countdown(msg):
            try:
                await channel.send(msg)
            except Exception:
                pass
        
        countdown_task = asyncio.create_task(self._countdown_timer(duration, send_countdown))
        await asyncio.sleep(duration)
        countdown_task.cancel()
        try:
            await countdown_task
        except asyncio.CancelledError:
            pass
        
        await self.process_vote(channel)
        return True
    
    async def create_game_night_event(self, guild: discord.Guild, title: str, game_name: str,
                                      start_time: 'datetime', end_time: 'datetime',
                                      description: str = '', image_url: Optional[str] = None) -> Optional[discord.ScheduledEvent]:
        """Create a Discord scheduled event for a game night.
        
        Args:
            guild: Discord guild to create event in.
            title: Event title.
            game_name: Name of the game being played.
            start_time: Event start time (datetime with timezone).
            end_time: Event end time (datetime with timezone).
            description: Event description text.
            image_url: Optional image URL (fallback to bot banner if not provided).
            
        Returns:
            The created ScheduledEvent object, or None if creation failed.
        """
        try:
            from datetime import datetime, timezone
            import requests
            from io import BytesIO
            
            # Ensure times have timezone
            if start_time.tzinfo is None:
                start_time = start_time.replace(tzinfo=timezone.utc)
            if end_time.tzinfo is None:
                end_time = end_time.replace(tzinfo=timezone.utc)
            
            # Build full description
            full_desc = f"🎮 **{game_name}**\n"
            if description:
                full_desc += f"{description}\n"
            full_desc += f"\n📅 Created by GAPI Game Night Scheduler"
            
            # Prepare image cover if available
            cover_bytes = None
            if image_url:
                try:
                    # Try to fetch game image
                    response = requests.get(image_url, timeout=5)
                    if response.status_code == 200:
                        cover_bytes = response.content
                except Exception as e:
                    print(f"Warning: Could not fetch game image: {e}")
            
            # If no game image, try to fetch bot banner
            if not cover_bytes and self.user and self.user.banner:
                try:
                    response = requests.get(self.user.banner.url, timeout=5)
                    if response.status_code == 200:
                        cover_bytes = response.content
                except Exception:
                    pass
            
            # Create the scheduled event
            event = await guild.create_scheduled_event(
                name=title,
                start_time=start_time,
                end_time=end_time,
                description=full_desc,
                entity_type=discord.ScheduledEventEntityType.external,
                image=cover_bytes if cover_bytes else discord.utils.MISSING,
            )
            
            return event
            
        except Exception as e:
            print(f"Error creating Discord game night event: {e}")
            return None
    
    def setup_commands(self):
        """Register slash commands"""
        
        @self.tree.command(name='link', description='Link your Discord account to your Steam ID')
        @app_commands.describe(
            steam_id='Your Steam ID (64-bit format)',
            username='Optional: Custom username (defaults to your Discord name)'
        )
        async def link_steam(interaction: discord.Interaction, steam_id: str, username: Optional[str] = None):
            """Link Discord user to Steam account"""
            user_name = username or interaction.user.name
            
            # Add to multi-user picker
            self.multi_picker.add_user(user_name, steam_id)
            
            # Add to Discord mapping
            self.user_mappings[interaction.user.id] = steam_id
            self.save_user_mappings()
            
            await interaction.response.send_message(f"✅ Linked {interaction.user.mention} to Steam ID: {steam_id}")
        
        @self.tree.command(name='unlink', description='Unlink your Steam account')
        async def unlink_steam(interaction: discord.Interaction):
            """Unlink Discord user from Steam account"""
            if interaction.user.id in self.user_mappings:
                steam_id = self.user_mappings[interaction.user.id]
                del self.user_mappings[interaction.user.id]
                self.save_user_mappings()
                
                # Remove from multi-user picker
                self.multi_picker.remove_user(interaction.user.name)
                
                await interaction.response.send_message(f"✅ Unlinked {interaction.user.mention} from Steam")
            else:
                await interaction.response.send_message(f"❌ {interaction.user.mention} is not linked to any Steam account")
        
        @self.tree.command(name='users', description='List all linked users')
        async def list_users(interaction: discord.Interaction):
            """List all users with linked Steam accounts"""
            if not self.multi_picker.users:
                await interaction.response.send_message("No users have linked their Steam accounts yet.")
                return

            def _user_name(user: Dict) -> str:
                return str(user.get('name') or user.get('username') or 'Unknown User')

            def _steam_id(user: Dict) -> str:
                if user.get('steam_id'):
                    return str(user.get('steam_id'))
                platforms = user.get('platforms') if isinstance(user.get('platforms'), dict) else {}
                steam = platforms.get('steam') if isinstance(platforms, dict) else None
                return str(steam) if steam else 'Not linked'

            user_list = "\n".join(
                [f"• {_user_name(user)} (Steam ID: {_steam_id(user)})" for user in self.multi_picker.users]
            )
            
            embed = discord.Embed(
                title="🎮 Linked Steam Accounts",
                description=user_list,
                color=discord.Color.blue()
            )
            await interaction.response.send_message(embed=embed)

        @self.tree.command(name='url', description='Get the GAPI app URL')
        async def app_url(interaction: discord.Interaction):
            """Show the configured GAPI web app URL."""
            base_url = (
                os.getenv('GAPI_APP_URL')
                or self.config.get('app_url')
                or 'http://localhost:5000'
            )
            await interaction.response.send_message(
                f"🔗 GAPI URL: {base_url}\n"
                f"Sessions: Open the 🎯 Sessions tab from {base_url}/"
            )

        @self.tree.command(name='linked', description='Show your current linked Steam account')
        async def linked_account(interaction: discord.Interaction):
            """Show the Steam ID linked to the calling Discord user."""
            steam_id = self.user_mappings.get(interaction.user.id)
            if steam_id:
                await interaction.response.send_message(
                    f"✅ {interaction.user.mention} is linked to Steam ID: `{steam_id}`"
                )
            else:
                await interaction.response.send_message(
                    f"❌ {interaction.user.mention} is not linked yet. Use `/link steam_id:<id>`"
                )

        @self.tree.command(name='help', description='Show available GAPI bot commands')
        async def show_help(interaction: discord.Interaction):
            """Display a compact command guide."""
            embed = discord.Embed(
                title="🤖 GAPI Bot Commands",
                color=discord.Color.blurple(),
                description="Quick reference for common commands. Join polls/votes by reacting with ✅!"
            )
            embed.add_field(name="Account", value="`/link` • `/unlink` • `/linked` • `/users`", inline=False)
            embed.add_field(name="Game Picks", value="`/pick` • `/common` • `/vote` • `/voteprivate` • `/joinvote` • `/leavevote` • `/stats`", inline=False)
            embed.add_field(name="Events & Polls", value="`/createevent` • `/createpoll` • `/pollstatus`", inline=False)
            embed.add_field(name="Utilities", value="`/url` • `/invite` • `/ping` • `/botstatus` • `/ignore` • `/hunt`", inline=False)
            embed.add_field(name="ℹ️ Joining", value="React with ✅ to join any active poll, vote, or private vote lobby!", inline=False)
            await interaction.response.send_message(embed=embed)

        @self.tree.command(name='ping', description='Check bot latency and API reachability')
        async def ping(interaction: discord.Interaction):
            """Return gateway latency and current app URL."""
            latency_ms = round(self.latency * 1000)
            base_url = (
                os.getenv('GAPI_APP_URL')
                or self.config.get('app_url')
                or 'http://localhost:5000'
            )
            await interaction.response.send_message(
                f"🏓 Pong! Latency: **{latency_ms}ms**\n"
                f"GAPI URL: {base_url}"
            )

        @self.tree.command(name='invite', description='Get Discord bot invite URL')
        async def invite(interaction: discord.Interaction):
            """Generate bot invite URL using configured Discord client ID."""
            client_id = (
                os.getenv('DISCORD_CLIENT_ID')
                or self.config.get('discord_bot_client_id')
                or self.config.get('discord_client_id')
            )
            if not client_id:
                await interaction.response.send_message(
                    "❌ Discord client ID is not configured. Set `DISCORD_CLIENT_ID` in `.env` or `discord_bot_client_id` in config.",
                    ephemeral=True,
                )
                return

            permissions = 2147487744
            invite_url = (
                f"https://discord.com/api/oauth2/authorize?client_id={client_id}"
                f"&permissions={permissions}&scope=bot%20applications.commands"
            )
            await interaction.response.send_message(f"🔗 Invite URL:\n{invite_url}")

        @self.tree.command(name='botstatus', description='Show bot runtime status')
        async def bot_status(interaction: discord.Interaction):
            """Show linked users, active votes, and guild count."""
            guild_count = len(self.guilds)
            linked_count = len(self.user_mappings)
            active_votes = len(self.active_votes)
            users_loaded = len(self.multi_picker.users)

            embed = discord.Embed(
                title="🤖 Bot Status",
                color=discord.Color.green(),
            )
            embed.add_field(name="Guilds", value=str(guild_count), inline=True)
            embed.add_field(name="Linked Accounts", value=str(linked_count), inline=True)
            embed.add_field(name="Users Loaded", value=str(users_loaded), inline=True)
            embed.add_field(name="Active Votes", value=str(active_votes), inline=True)
            embed.add_field(name="Latency", value=f"{round(self.latency * 1000)}ms", inline=True)
            embed.add_field(name="Uptime", value=f"Since process start", inline=True)
            await interaction.response.send_message(embed=embed)

        @self.tree.command(name='voteprivate', description='Create a private DM vote lobby (co-op/multiplayer only)')
        @app_commands.describe(
            join_duration='Seconds users can join the vote lobby (default: 30)',
            vote_duration='Seconds users have to vote in DM once started (default: 60)',
            candidates='Number of candidate games to include (default: 8, max: 20)',
            genre='Optional genre filter (e.g. Action, RPG, Strategy)',
            min_metacritic='Optional minimum Metacritic score (0-100)'
        )
        async def vote_private(
            interaction: discord.Interaction,
            join_duration: int = 30,
            vote_duration: int = 60,
            candidates: int = 8,
            genre: Optional[str] = None,
            min_metacritic: Optional[int] = None,
        ):
            """Create a private vote lobby; joined users receive DM ballots."""
            channel_id = interaction.channel_id
            channel = interaction.channel
            if channel_id is None or channel is None:
                await interaction.response.send_message("❌ This command must be used in a channel.")
                return
            if channel_id in self.private_vote_lobbies:
                await interaction.response.send_message("❌ A private vote lobby is already active in this channel.")
                return

            creator_name = self._resolve_linked_user_name(interaction.user.id)
            if not creator_name:
                await interaction.response.send_message(
                    "❌ You must link your Steam account first with `/link` before creating a private vote.",
                    ephemeral=True,
                )
                return

            join_duration = max(10, min(join_duration, 300))
            vote_duration = max(20, min(vote_duration, 600))
            candidates = max(2, min(candidates, 20))
            
            # Default min_metacritic to 60 if not specified
            if min_metacritic is None:
                min_metacritic = 60
            else:
                min_metacritic = max(0, min(min_metacritic, 100))

            lobby = {
                'lobby_id': str(datetime.now().timestamp()),
                'channel_id': channel_id,
                'creator_id': interaction.user.id,
                'joined_ids': {interaction.user.id},
                'join_duration': join_duration,
                'vote_duration': vote_duration,
                'candidates': candidates,
                'genre': genre.strip() if genre else None,
                'min_metacritic': min_metacritic,
            }
            self.private_vote_lobbies[channel_id] = lobby

            filter_bits = ["co-op/multiplayer only"]
            if lobby['genre']:
                filter_bits.append(f"genre={lobby['genre']}")
            if lobby['min_metacritic'] is not None:
                filter_bits.append(f"metacritic>={lobby['min_metacritic']}")

            await interaction.response.send_message(
                f"🗳️ Private vote lobby created by {interaction.user.mention}!\n"
                f"Use `/joinvote` in this channel to join, or react with ✅ below. Join window: **{join_duration}s**\n"
                f"Vote duration: **{vote_duration}s**, candidates: **{candidates}**\n"
                f"Filters: {', '.join(filter_bits)}"
            )
            
            # Use followup to get actual message object for reactions
            vote_msg = await interaction.followup.send(
                "✅ React with ✅ below to join this private vote!"
            )
            
            # Add join reaction
            await vote_msg.add_reaction('✅')
            
            # Track this message for ✅ join reactions
            self.active_polls[vote_msg.id] = {
                'type': 'private_vote',
                'channel_id': channel_id,
                'lobby_id': lobby['lobby_id'],
            }
            self.poll_participants[vote_msg.id] = {interaction.user.id}

            asyncio.create_task(self._run_private_vote(interaction.channel, lobby))

        @self.tree.command(name='joinvote', description='Join an active private vote lobby in this channel')
        async def join_vote(interaction: discord.Interaction):
            """Join active private vote lobby for current channel."""
            channel_id = interaction.channel_id
            if channel_id is None:
                await interaction.response.send_message("❌ This command must be used in a channel.")
                return
            lobby = self.private_vote_lobbies.get(channel_id)
            if not lobby:
                await interaction.response.send_message("❌ No private vote lobby is active in this channel.")
                return

            linked_name = self._resolve_linked_user_name(interaction.user.id)
            if not linked_name:
                await interaction.response.send_message(
                    "❌ You must link your Steam account first with `/link` before joining private vote.",
                    ephemeral=True,
                )
                return

            lobby['joined_ids'].add(interaction.user.id)
            await interaction.response.send_message(
                f"✅ {interaction.user.mention} joined private vote. "
                f"Current participants: **{len(lobby['joined_ids'])}**"
            )

        @self.tree.command(name='leavevote', description='Leave an active private vote lobby in this channel')
        async def leave_vote(interaction: discord.Interaction):
            """Leave active private vote lobby for current channel."""
            channel_id = interaction.channel_id
            if channel_id is None:
                await interaction.response.send_message("❌ This command must be used in a channel.")
                return
            lobby = self.private_vote_lobbies.get(channel_id)
            if not lobby:
                await interaction.response.send_message("❌ No private vote lobby is active in this channel.")
                return

            if interaction.user.id == lobby.get('creator_id'):
                await interaction.response.send_message(
                    "❌ Vote creator cannot leave the lobby. You can wait for it to start or create a new one later.",
                    ephemeral=True,
                )
                return

            if interaction.user.id not in lobby.get('joined_ids', set()):
                await interaction.response.send_message("ℹ️ You are not currently joined in this private vote.", ephemeral=True)
                return

            lobby['joined_ids'].remove(interaction.user.id)
            await interaction.response.send_message(
                f"✅ {interaction.user.mention} left private vote. "
                f"Current participants: **{len(lobby['joined_ids'])}**"
            )
        
        @self.tree.command(name='vote', description='Start a voting session to play a game')
        @app_commands.describe(
            join_duration='Duration in seconds for joining phase (default: 30)',
            vote_duration='Duration in seconds for voting session (default: 60)',
            candidates='Number of game candidates to vote on (default: 5, max: 10 for public reaction vote)',
            everyone='Include @everyone in the vote notification (default: False)',
            genre='Optional genre filter (e.g. Action, RPG, Strategy)',
            min_metacritic='Optional minimum Metacritic score (0-100)',
            new_games_only='Filter to only recent/new games (default: True)'
        )
        async def start_vote(interaction: discord.Interaction, join_duration: int = 30,
                             vote_duration: int = 60, candidates: int = 5, everyone: bool = False,
                             genre: Optional[str] = None, min_metacritic: Optional[int] = None,
                             new_games_only: bool = True):
            """Start a public reaction vote with a join phase, then voting among participants."""
            channel_id = interaction.channel_id
            channel = interaction.channel
            
            if channel_id is None or channel is None:
                await interaction.response.send_message("❌ This command must be used in a channel!")
                return

            if channel_id in self.active_votes:
                await interaction.response.send_message("❌ A voting session is already active in this channel!")
                return

            num_candidates = max(2, min(candidates, 10))

            # Check if there are any linked users
            if not self.multi_picker.users:
                await interaction.response.send_message(
                    "❌ No users have linked their Steam accounts. Use `/link` first."
                )
                return

            mention_text = "@everyone " if everyone else ""

            # Phase 1: Join phase
            await interaction.response.send_message(f"🎮 {mention_text}**Game Vote Starting!**\n\nReact with ✅ to join the vote!\n⏱️ Join phase ends in **{join_duration} seconds**")
            
            # Get the message for adding reaction
            join_msg = await interaction.original_response()
            await join_msg.add_reaction('✅')
            
            # Track this as a join message
            self.active_polls[join_msg.id] = {
                'type': 'vote_join',
                'channel_id': channel.id,
            }
            self.poll_participants[join_msg.id] = set()
            
            # Wait for join duration
            await asyncio.sleep(join_duration)
            
            # Collect participants who joined
            joined_user_ids = self.poll_participants.get(join_msg.id, set())
            
            # Clean up join tracking
            if join_msg.id in self.active_polls:
                del self.active_polls[join_msg.id]
            if join_msg.id in self.poll_participants:
                del self.poll_participants[join_msg.id]
            
            if not joined_user_ids:
                await channel.send("❌ No one joined the vote! Vote cancelled.")
                return
            
            # Map Discord IDs to MultiUserPicker user names
            participants = []
            for discord_user_id in joined_user_ids:
                user_name = self._resolve_linked_user_name(discord_user_id)
                if user_name:
                    participants.append(user_name)
            
            if not participants:
                await channel.send("❌ None of the participants have linked their Steam accounts! Use `/link` first.")
                return
            
            # Validate and constrain filters
            if min_metacritic is not None:
                min_metacritic = max(0, min(min_metacritic, 100))
            
            # Set min_release_year for new games filter
            min_release_year = None
            if new_games_only:
                from datetime import datetime as dt
                current_year = dt.now().year
                min_release_year = current_year - 5  # Last 5 years
            
            filter_bits = []
            if genre:
                filter_bits.append(f"genre={genre.strip()}")
            if min_metacritic is not None:
                filter_bits.append(f"metacritic>={min_metacritic}")
            if new_games_only:
                filter_bits.append(f"released>={min_release_year}")
            
            filter_msg = f" with filters: {', '.join(filter_bits)}" if filter_bits else ""
            
            # Phase 2: Start the actual vote
            await channel.send(f"🔍 Found **{len(participants)}** participant(s)! Finding common games for the vote{filter_msg}…")
            await self._start_public_vote_round(
                channel=channel,
                participants=participants,
                duration=vote_duration,
                num_candidates=num_candidates,
                restart_count=0,
                everyone_mention=False,  # Don't mention everyone again
                genre=genre.strip() if genre else None,
                min_metacritic=min_metacritic,
                min_release_year=min_release_year,
            )
        
        @self.tree.command(name='pick', description='Pick a random game for mentioned users or all linked users')
        @app_commands.describe(
            user1='First user to pick a game for',
            user2='Second user to pick a game for',
            user3='Third user to pick a game for',
            user4='Fourth user to pick a game for',
            user5='Fifth user to pick a game for'
        )
        async def pick_game(
            interaction: discord.Interaction, 
            user1: Optional[discord.User] = None,
            user2: Optional[discord.User] = None,
            user3: Optional[discord.User] = None,
            user4: Optional[discord.User] = None,
            user5: Optional[discord.User] = None
        ):
            """Pick a random common game for specified users"""
            # Get participants
            participants = []
            mentioned_users = [u for u in [user1, user2, user3, user4, user5] if u is not None]
            
            if mentioned_users:
                # Use mentioned users
                for user in mentioned_users:
                    if user.id in self.user_mappings:
                        participants.append(user.name)
            else:
                # Use all linked users
                participants = [user['name'] for user in self.multi_picker.users]
            
            if not participants:
                await interaction.response.send_message("❌ No linked users found! Use `/link` to link your account.")
                return
            
            await interaction.response.send_message(f"🎲 Finding a common game for {len(participants)} player(s)...")
            
            # Pick a common game - run in thread to avoid blocking event loop
            try:
                game = await asyncio.to_thread(
                    self.multi_picker.pick_common_game,
                    participants,
                    coop_only=True
                )
            except Exception as e:
                await interaction.followup.send(f"❌ Error finding games: {str(e)}")
                return
            
            if not game:
                await interaction.followup.send(f"❌ No common co-op games found for the selected users.")
                return
            
            # Display result
            embed = discord.Embed(
                title=f"🎮 {game.get('name', 'Unknown Game')}",
                color=discord.Color.gold()
            )
            
            app_id = game.get('appid')
            embed.add_field(name="App ID", value=str(app_id), inline=True)
            
            if 'is_coop' in game:
                embed.add_field(name="Co-op", value="✅" if game['is_coop'] else "❌", inline=True)
            
            if 'owners' in game:
                embed.add_field(name="Players", value=", ".join(game['owners']), inline=False)
            
            embed.add_field(
                name="Steam Store", 
                value=f"[Open](https://store.steampowered.com/app/{app_id}/)",
                inline=True
            )
            embed.add_field(
                name="SteamDB", 
                value=f"[Open](https://steamdb.info/app/{app_id}/)",
                inline=True
            )
            
            await interaction.followup.send(embed=embed)
        
        @self.tree.command(name='common', description='Show common games between users')
        @app_commands.describe(limit='Maximum number of games to show (default: 10)')
        async def show_common(interaction: discord.Interaction, limit: int = 10):
            """Show common games owned by all linked users"""
            common_games = self.multi_picker.find_common_games()
            
            if not common_games:
                await interaction.response.send_message("❌ No common games found among linked users.")
                return
            
            # Sort by name
            common_games.sort(key=lambda g: g.get('name', ''))
            
            # Limit results
            games_to_show = common_games[:limit]
            
            game_list = "\n".join([f"• {game.get('name', 'Unknown')}" 
                                  for game in games_to_show])
            
            embed = discord.Embed(
                title=f"🎮 Common Games ({len(common_games)} total)",
                description=f"Showing {len(games_to_show)} of {len(common_games)} games:\n\n{game_list}",
                color=discord.Color.blue()
            )
            
            await interaction.response.send_message(embed=embed)
        
        @self.tree.command(name='stats', description='Show library statistics')
        async def show_stats(interaction: discord.Interaction):
            """Show statistics about user libraries"""
            stats = self.multi_picker.get_library_stats()
            
            if not stats:
                await interaction.response.send_message("❌ No user libraries loaded.")
                return
            
            embed = discord.Embed(
                title="📊 Library Statistics",
                color=discord.Color.purple()
            )
            
            for user, count in stats['total_games_per_user'].items():
                embed.add_field(name=user, value=f"{count} games", inline=True)
            
            embed.add_field(name="Common Games", value=str(stats['common_games_count']), inline=True)
            embed.add_field(name="Total Unique Games", value=str(stats['total_unique_games']), inline=True)
            
            await interaction.response.send_message(embed=embed)
        
        @self.tree.command(name='ignore', description='Manage your ignore list')
        @app_commands.describe(
            action='add, list, or remove',
            app_id='Steam app ID (for add/remove)',
            game_name='Game name (for add)'
        )
        async def manage_ignore(
            interaction: discord.Interaction,
            action: str = 'list',
            app_id: Optional[str] = None,
            game_name: Optional[str] = None
        ):
            """Manage ignored games"""
            import requests
            
            user_name = interaction.user.name
            api_url = 'http://localhost:5000'
            
            try:
                if action.lower() == 'add':
                    if not app_id or not game_name:
                        await interaction.response.send_message("❌ app_id and game_name required for add")
                        return
                    
                    response = requests.post(
                        f'{api_url}/api/ignored-games',
                        json={
                            'app_id': int(app_id),
                            'game_name': game_name,
                            'reason': f'Added via Discord by {interaction.user.name}'
                        },
                        headers={'Authorization': f'Bearer {user_name}'}
                    )
                    
                    if response.status_code == 200:
                        await interaction.response.send_message(f"✅ Added {game_name} to your ignore list")
                    else:
                        await interaction.response.send_message(f"❌ Failed to add game: {response.text}")
                
                elif action.lower() == 'list':
                    response = requests.get(
                        f'{api_url}/api/ignored-games',
                        headers={'Authorization': f'Bearer {user_name}'}
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        games = data.get('ignored_games', [])
                        
                        if not games:
                            await interaction.response.send_message("No games in your ignore list")
                            return
                        
                        embed = discord.Embed(
                            title="🚫 Your Ignore List",
                            color=discord.Color.red()
                        )
                        
                        for game in games[:25]:  # Discord has 25 field limit
                            reason = game.get('reason', 'No reason')
                            embed.add_field(
                                name=f"{game['game_name']} (ID: {game['app_id']})",
                                value=f"*{reason}*",
                                inline=False
                            )
                        
                        await interaction.response.send_message(embed=embed)
                    else:
                        await interaction.response.send_message("❌ Failed to load ignore list")
                
                elif action.lower() == 'remove':
                    if not app_id:
                        await interaction.response.send_message("❌ app_id required for remove")
                        return
                    
                    response = requests.post(
                        f'{api_url}/api/ignored-games',
                        json={'app_id': int(app_id), 'game_name': '', 'reason': ''},
                        headers={'Authorization': f'Bearer {user_name}'}
                    )
                    
                    if response.status_code == 200:
                        await interaction.response.send_message(f"✅ Removed game {app_id} from your ignore list")
                    else:
                        await interaction.response.send_message(f"❌ Failed to remove game")
                else:
                    await interaction.response.send_message("❌ Unknown action. Use: add, list, or remove")
                    
            except Exception as e:
                await interaction.response.send_message(f"❌ Error: {str(e)}")
        
        @self.tree.command(name='hunt', description='Start or manage achievement hunts')
        @app_commands.describe(
            action='start or progress',
            app_id='Steam app ID',
            game_name='Game name (for start)',
            difficulty='Difficulty: easy, medium, hard, extreme (for start)'
        )
        async def manage_hunt(
            interaction: discord.Interaction,
            action: str = 'progress',
            app_id: Optional[str] = None,
            game_name: Optional[str] = None,
            difficulty: Optional[str] = 'medium'
        ):
            """Start or check achievement hunts"""
            import requests
            
            user_name = interaction.user.name
            api_url = 'http://localhost:5000'
            
            try:
                if action.lower() == 'start':
                    if not app_id or not game_name:
                        await interaction.response.send_message("❌ app_id and game_name required for start")
                        return
                    
                    response = requests.post(
                        f'{api_url}/api/achievement-hunt',
                        json={
                            'app_id': int(app_id),
                            'game_name': game_name,
                            'difficulty': difficulty or 'medium'
                        },
                        headers={'Authorization': f'Bearer {user_name}'}
                    )
                    
                    if response.status_code == 201:
                        data = response.json()
                        embed = discord.Embed(
                            title=f"🏆 Started Achievement Hunt",
                            description=f"Game: {game_name}",
                            color=discord.Color.gold()
                        )
                        embed.add_field(name="Difficulty", value=difficulty or "medium", inline=True)
                        embed.add_field(name="Hunt ID", value=str(data.get('hunt_id', 'N/A')), inline=True)
                        await interaction.response.send_message(embed=embed)
                    else:
                        await interaction.response.send_message(f"❌ Failed to start hunt: {response.text}")
                
                elif action.lower() == 'progress':
                    response = requests.get(
                        f'{api_url}/api/achievements',
                        headers={'Authorization': f'Bearer {user_name}'}
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        achievements = data.get('achievements', [])
                        
                        if not achievements:
                            await interaction.response.send_message("No active achievement hunts")
                            return
                        
                        embed = discord.Embed(
                            title="🏆 Your Achievement Hunts",
                            color=discord.Color.gold()
                        )
                        
                        for game in achievements[:10]:  # Show top 10
                            unlocked = sum(1 for a in game.get('achievements', []) if a.get('unlocked'))
                            total = len(game.get('achievements', []))
                            progress = f"{unlocked}/{total}" if total > 0 else "0/0"
                            
                            embed.add_field(
                                name=game['game_name'],
                                value=f"Progress: {progress}",
                                inline=False
                            )
                        
                        await interaction.response.send_message(embed=embed)
                    else:
                        await interaction.response.send_message("❌ Failed to load achievements")
                else:
                    await interaction.response.send_message("❌ Unknown action. Use: start or progress")
                    
            except Exception as e:
                await interaction.response.send_message(f"❌ Error: {str(e)}")
        
        @self.tree.command(name='createpoll', description='Create a poll with custom options (everyone can vote)')
        @app_commands.describe(
            question='The question to ask',
            option1='First option',
            option2='Second option',
            option3='Third option (optional)',
            option4='Fourth option (optional)',
            option5='Fifth option (optional)'
        )
        async def create_poll(
            interaction: discord.Interaction,
            question: str,
            option1: str,
            option2: str,
            option3: Optional[str] = None,
            option4: Optional[str] = None,
            option5: Optional[str] = None,
        ):
            """Create an interactive poll that anyone can vote on using reactions."""
            options = [option1, option2, option3, option4, option5]
            options = [opt for opt in options if opt is not None]
            
            if len(options) < 2:
                await interaction.response.send_message("❌ You need at least 2 options for a poll")
                return
            
            if len(options) > 5:
                await interaction.response.send_message("❌ Maximum 5 options per poll")
                return
            
            # Emoji reactions for poll options
            OPTION_EMOJIS = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣']
            NONE_EMOJI = '❌'
            
            poll_description = "\n".join(
                [f"{OPTION_EMOJIS[i]} {options[i]}" for i in range(len(options))]
            )
            poll_description += f"\n{NONE_EMOJI} None of these"
            poll_description += f"\n\n✅ React with ✅ to join this poll!"
            
            embed = discord.Embed(
                title=f"📊 Poll: {question}",
                description=poll_description,
                color=discord.Color.blurple()
            )
            embed.set_footer(text=f"Created by {interaction.user.name}")
            
            await interaction.response.send_message(embed=embed)
            
            # Use followup to get actual message object for reactions
            poll_msg = await interaction.followup.send(
                "React with your choice or ✅ to join!"
            )
            
            # Store poll data for tracking
            self.active_polls[poll_msg.id] = {
                'question': question,
                'options': options,
                'creator_id': interaction.user.id,
                'channel_id': interaction.channel_id,
            }
            self.poll_participants[poll_msg.id] = {interaction.user.id}  # Creator joins automatically
            
            # Add reactions for each option
            for i in range(len(options)):
                await poll_msg.add_reaction(OPTION_EMOJIS[i])
            
            # Add None of these reaction
            await poll_msg.add_reaction(NONE_EMOJI)
            
            # Add join reaction
            await poll_msg.add_reaction('✅')
            
            await interaction.followup.send(f"✅ Poll created! Vote with {', '.join(OPTION_EMOJIS[:len(options)])} or {NONE_EMOJI}. React with ✅ to join!")
        
        @self.tree.command(name='createevent', description='Create a scheduled game event')
        @app_commands.describe(
            name='Name of the event',
            game_name='Game to be played',
            start_time='Start time in format HH:MM (24-hour format)',
            duration_minutes='Duration in minutes (default: 120)',
            description='Event description (optional)'
        )
        async def create_event(
            interaction: discord.Interaction,
            name: str,
            game_name: str,
            start_time: str,
            duration_minutes: int = 120,
            description: Optional[str] = None,
        ):
            """Create a scheduled Discord event for a game session."""
            try:
                # Parse start time
                if ':' not in start_time:
                    await interaction.response.send_message("❌ Invalid time format. Use HH:MM (24-hour format)")
                    return
                
                hour, minute = map(int, start_time.split(':'))
                if not (0 <= hour <= 23 and 0 <= minute <= 59):
                    await interaction.response.send_message("❌ Invalid time. Hours must be 0-23, minutes 0-59")
                    return
                
                # Calculate start time for today or tomorrow
                from datetime import datetime, timedelta, timezone
                now = datetime.now(timezone.utc)
                event_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                
                # If the time is in the past today, schedule for tomorrow
                if event_time <= now:
                    event_time += timedelta(days=1)
                
                # Create event description
                event_desc = f"🎮 Game: {game_name}\n"
                if description:
                    event_desc += f"\n{description}\n"
                event_desc += f"\nStarted by: {interaction.user.mention}"
                
                # Create the Discord event
                guild = interaction.guild
                if guild is None:
                    await interaction.response.send_message("❌ This command must be used in a server")
                    return
                
                # Discord.py event creation
                event = await guild.create_scheduled_event(
                    name=name,
                    start_time=event_time,
                    end_time=event_time + timedelta(minutes=duration_minutes),
                    description=event_desc,
                    entity_type=discord.ScheduledEventEntityType.external,
                )
                
                await interaction.response.send_message(
                    f"✅ Event created: **{name}**\n"
                    f"🎮 Game: {game_name}\n"
                    f"⏰ Start: {event_time.strftime('%H:%M UTC')}\n"
                    f"⏱️ Duration: {duration_minutes} minutes\n"
                    f"📅 Event ID: {event.id}"
                )
                
            except ValueError:
                await interaction.response.send_message("❌ Invalid input. Please check your time format (HH:MM)")
            except Exception as e:
                await interaction.response.send_message(f"❌ Failed to create event: {str(e)}")
        
        @self.tree.command(name='scheduledevent', description='Create Discord event from scheduled game night')
        @app_commands.describe(
            event_id='Schedule event ID (from /api/schedule)',
            game_name='Game name (will show on event)',
            image_url='Image URL for game (optional, uses bot banner)',
        )
        async def create_scheduled_event(
            interaction: discord.Interaction,
            event_id: str,
            game_name: str,
            image_url: Optional[str] = None,
        ):
            """Create a Discord scheduled event from a game night schedule.
            
            This command creates a Discord event with:
            - Game image (or bot banner as fallback)
            - Event time from the schedule
            - Attendee list in description
            """
            try:
                from datetime import datetime, timedelta, timezone
                
                guild = interaction.guild
                if not guild:
                    await interaction.response.send_message("❌ This command must be used in a server")
                    return
                
                # The event_id refers to a scheduled game night event
                # For now, we'll create a simple event since we don't have direct access
                # to the schedule service from here. In production, you'd fetch from the API.
                
                # Parse event_id and prepare event
                now = datetime.now(timezone.utc)
                start_time = now + timedelta(hours=1)
                end_time = start_time + timedelta(hours=2)
                
                # Create the event
                event = await self.create_game_night_event(
                    guild=guild,
                    title=f"Game Night: {game_name}",
                    game_name=game_name,
                    start_time=start_time,
                    end_time=end_time,
                    description=f"Event ID: {event_id}",
                    image_url=image_url,
                )
                
                if event:
                    await interaction.response.send_message(
                        f"✅ Discord event created: **{event.name}**\n"
                        f"🎮 Game: {game_name}\n"
                        f"⏰ Start: {start_time.strftime('%Y-%m-%d %H:%M UTC')}\n"
                        f"📅 Event ID: {event.id}"
                    )
                else:
                    await interaction.response.send_message("❌ Failed to create Discord event")
                    
            except Exception as e:
                await interaction.response.send_message(f"❌ Error: {str(e)}")
        
        @self.tree.command(name='pollstatus', description='Show active polls and votes in this channel')
        async def poll_status(interaction: discord.Interaction):
            """Show all active polls and current participants."""
            channel_id = interaction.channel_id
            active_in_channel = []
            
            for msg_id, poll_data in self.active_polls.items():
                if poll_data.get('channel_id') == channel_id:
                    participants = self.poll_participants.get(msg_id, set())
                    active_in_channel.append({
                        'msg_id': msg_id,
                        'data': poll_data,
                        'participants': participants,
                    })
            
            if not active_in_channel:
                await interaction.response.send_message("No active polls or votes in this channel.")
                return
            
            embed = discord.Embed(
                title=f"📊 Active Polls & Votes ({len(active_in_channel)})",
                color=discord.Color.blurple()
            )
            
            for item in active_in_channel:
                msg_id = item['msg_id']
                poll_data = item['data']
                participants = item['participants']
                
                poll_type = poll_data.get('type', 'poll')
                participant_list = f"{len(participants)} participant(s)"
                
                if poll_type == 'vote':
                    poll_type_str = "🗳️ Vote"
                elif poll_type == 'private_vote':
                    poll_type_str = "🗳️ Private Vote"
                else:
                    poll_type_str = "📊 Poll"
                
                question = poll_data.get('question', 'Game Vote')
                embed.add_field(
                    name=f"{poll_type_str}: {question}",
                    value=f"Message ID: {msg_id}\n{participant_list}",
                    inline=False
                )
            
            embed.set_footer(text="React with ✅ to join any active poll or vote!")
            await interaction.response.send_message(embed=embed)
    
    async def process_vote(self, channel):
        """Process voting results and announce the winning game."""
        channel_id = channel.id

        if channel_id not in self.active_votes:
            return

        vote_data = self.active_votes[channel_id]
        vote_msg = vote_data['message']
        session = vote_data.get('session')
        candidate_games = vote_data.get('candidate_games', [])
        emojis = vote_data.get('emojis', [])
        nota_emoji = vote_data.get('nota_emoji', '🚫')
        participants = vote_data.get('participants', [])
        duration = int(vote_data.get('duration', 60))
        num_candidates = int(vote_data.get('num_candidates', 5))
        restart_count = int(vote_data.get('restart_count', 0))
        max_restarts = int(vote_data.get('max_restarts', 2))
        everyone_mention = vote_data.get('everyone_mention', False)

        # Clean up active votes entry early to prevent double-processing
        del self.active_votes[channel_id]
        
        # Clean up poll tracking for this vote message
        message_id = vote_msg.id if vote_msg else None
        if message_id and message_id in self.active_polls:
            del self.active_polls[message_id]
        if message_id and message_id in self.poll_participants:
            del self.poll_participants[message_id]

        if not session or not candidate_games:
            await channel.send("❌ Voting session data missing.")
            return

        # Tally reactions from the vote message
        vote_count = 0
        if vote_msg:
            try:
                # Fetch fresh message to get current reactions
                vote_msg = await channel.fetch_message(vote_msg.id)
            except Exception as e:
                await channel.send(f"❌ Error fetching vote message: {str(e)}")
                return
            
            for reaction in vote_msg.reactions:
                emoji_str = str(reaction.emoji)
                if emoji_str in emojis:
                    game_index = emojis.index(emoji_str)
                    game = candidate_games[game_index]
                    app_id = str(game.get('appid') or game.get('app_id') or '')
                    async for user in reaction.users():
                        if not user.bot:
                            # Cast vote on behalf of linked or any reacting user
                            voter_name = user.name
                            session.cast_vote(voter_name, app_id)
                            vote_count += 1
                elif emoji_str == nota_emoji:
                    async for user in reaction.users():
                        if not user.bot:
                            voter_name = user.name
                            session.cast_vote(voter_name, '__NOTA__')
                            vote_count += 1
                # Skip ✅ emoji - that's for joining, not voting

        # Close session and determine winner
        session.close()
        winner = session.get_winner()
        results = session.get_results()
        
        # Check if anyone actually voted
        total_votes = sum(item.get('count', 0) for item in results.values())
        if total_votes == 0:
            await channel.send(f"❌ No votes were cast! Vote ended with no winner. (Processed {vote_count} reactions)")
            return

        # Build results summary
        results_lines = ["**Vote Results:**"]
        for i, game in enumerate(candidate_games):
            app_id = str(game.get('appid') or game.get('app_id') or '')
            count = results.get(app_id, {}).get('count', 0)
            voters = results.get(app_id, {}).get('voters', [])
            voter_str = f" ({', '.join(voters)})" if voters else ""
            results_lines.append(f"{emojis[i]} **{game.get('name', 'Unknown')}** — {count} vote(s){voter_str}")
        nota_count = results.get('__NOTA__', {}).get('count', 0)
        nota_voters = results.get('__NOTA__', {}).get('voters', [])
        nota_voter_str = f" ({', '.join(nota_voters)})" if nota_voters else ""
        results_lines.append(f"{nota_emoji} **None of these** — {nota_count} vote(s){nota_voter_str}")

        await channel.send("\n".join(results_lines))

        total_votes = sum(item.get('count', 0) for item in results.values())
        if total_votes > 0 and nota_count > (total_votes / 2):
            if restart_count < max_restarts:
                await channel.send("🔁 Majority voted **None of these**. Restarting vote with fresh options…")
                await self._start_public_vote_round(
                    channel=channel,
                    participants=participants,
                    duration=duration,
                    num_candidates=num_candidates,
                    restart_count=restart_count + 1,
                    everyone_mention=everyone_mention,
                    genre=vote_data.get('genre'),
                    min_metacritic=vote_data.get('min_metacritic'),
                    min_release_year=vote_data.get('min_release_year'),
                )
                return
            await channel.send("❌ Vote ended with majority 'None of these' after retries.")
            return

        if not winner:
            await channel.send("❌ Could not determine a winner.")
            return

        app_id = winner.get('appid') or winner.get('app_id')
        if str(app_id) == '__NOTA__':
            # Fallback to highest non-NOTA game when NOTA did not have majority.
            best_game = None
            best_count = -1
            for game in candidate_games:
                game_id = str(game.get('appid') or game.get('app_id') or '')
                game_count = results.get(game_id, {}).get('count', 0)
                if game_count > best_count:
                    best_count = game_count
                    best_game = game
            if not best_game or best_count <= 0:
                await channel.send("❌ Could not determine a winner.")
                return
            winner = best_game
            app_id = winner.get('appid') or winner.get('app_id')

        embed = await self._get_game_embed(winner, str(app_id), len(session.votes))
        await channel.send(embed=embed)

    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.User):
        """Handle user joining polls/votes with ✅ reaction."""
        if user.bot:
            return
        
        # Check if this is a poll or vote message
        message_id = reaction.message.id
        
        if message_id not in self.active_polls:
            return
        
        if str(reaction.emoji) != '✅':
            return
        
        poll_data = self.active_polls[message_id]
        
        # Handle regular polls and public votes
        if poll_data.get('type') != 'private_vote':
            if message_id not in self.poll_participants:
                self.poll_participants[message_id] = set()
            
            self.poll_participants[message_id].add(user.id)
            
            # Send DM or confirmation
            try:
                channel = reaction.message.channel
                await channel.send(f"✅ {user.mention} has joined! Participants: **{len(self.poll_participants[message_id])}**")
            except Exception:
                pass
        
        # Handle private vote joining
        else:
            channel_id = poll_data.get('channel_id')
            lobby_id = poll_data.get('lobby_id')
            
            if channel_id not in self.private_vote_lobbies:
                return
            
            lobby = self.private_vote_lobbies[channel_id]
            if lobby.get('lobby_id') != lobby_id:
                return
            
            linked_name = self._resolve_linked_user_name(user.id)
            if not linked_name:
                try:
                    await user.send("❌ You must link your Steam account first with `/link` before joining private vote.")
                except Exception:
                    pass
                return
            
            if user.id not in lobby.get('joined_ids', set()):
                lobby['joined_ids'].add(user.id)
                self.poll_participants[message_id].add(user.id)
                
                try:
                    channel = reaction.message.channel
                    await channel.send(
                        f"✅ {user.mention} has joined private vote. "
                        f"Current participants: **{len(lobby['joined_ids'])}**"
                    )
                except Exception:
                    pass
    
    async def on_reaction_remove(self, reaction: discord.Reaction, user: discord.User):
        """Handle user leaving polls/votes when removing ✅ reaction."""
        if user.bot:
            return
        
        message_id = reaction.message.id
        
        if message_id not in self.active_polls:
            return
        
        if str(reaction.emoji) != '✅':
            return
        
        poll_data = self.active_polls[message_id]
        
        if message_id in self.poll_participants:
            self.poll_participants[message_id].discard(user.id)
            
            # Handle private vote removal
            if poll_data.get('type') == 'private_vote':
                channel_id = poll_data.get('channel_id')
                lobby_id = poll_data.get('lobby_id')
                
                if channel_id in self.private_vote_lobbies:
                    lobby = self.private_vote_lobbies[channel_id]
                    if lobby.get('lobby_id') == lobby_id:
                        lobby['joined_ids'].discard(user.id)
                        
                        # Send notification
                        try:
                            channel = reaction.message.channel
                            participant_count = len(lobby.get('joined_ids', set()))
                            await channel.send(f"👋 {user.mention} has left. Participants: **{participant_count}**")
                        except Exception:
                            pass
            else:
                # Send notification for regular polls/votes
                try:
                    channel = reaction.message.channel
                    participant_count = len(self.poll_participants[message_id])
                    await channel.send(f"👋 {user.mention} has left. Participants: **{participant_count}**")
                except Exception:
                    pass


def run_bot(token: str, config: Dict):
    """Run the Discord bot"""
    bot = GAPIBot(config)
    
    @bot.event
    async def on_ready():
        print(f'✅ {bot.user} is now online!')
        print(f'Loaded {len(bot.multi_picker.users)} linked accounts')
        
        # Sync slash commands with Discord
        try:
            synced = await bot.tree.sync()
            print(f'✅ Synced {len(synced)} slash command(s)')
        except Exception as e:
            print(f'❌ Failed to sync commands: {e}')
    
    bot.run(token)


if __name__ == "__main__":
    import sys
    
    # Load .env file for environment variables
    load_dotenv()
    
    # Load configuration – honour GAPI_DISCORD_CONFIG env var set by admin panel
    config_path = os.environ.get('GAPI_DISCORD_CONFIG', 'config.json')
    if not os.path.exists(config_path):
        print("❌ config.json not found!")
        sys.exit(1)
    
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    # Read Steam API key from environment (.env) first, then fall back to config.json
    steam_api_key = os.getenv('STEAM_API_KEY') or config.get('steam_api_key')
    discord_token = config.get('discord_bot_token')
    
    if not steam_api_key:
        print("❌ steam_api_key not found in .env (STEAM_API_KEY) or config.json")
        print("  Please set STEAM_API_KEY in your .env file or add to config.json")
        sys.exit(1)
    
    if not discord_token:
        print("❌ discord_bot_token not found in config.json")
        print("Please add your Discord bot token to config.json")
        sys.exit(1)
    
    # Update config with steam_api_key from environment (priority: .env > config.json)
    config['steam_api_key'] = steam_api_key
    
    run_bot(discord_token, config)
