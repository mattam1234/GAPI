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
    
    def __init__(self, config: Dict, config_file: str = 'discord_config.json'):
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
        self.config_file = config_file
        self.multi_picker = multiuser.MultiUserPicker(config)
        
        # Active voting sessions
        self.active_votes: Dict[int, Dict] = {}  # channel_id -> vote_data
        self.private_vote_lobbies: Dict[int, Dict] = {}  # channel_id -> lobby data
        
        # Discord user to Steam ID mapping
        self.user_mappings: Dict[int, str] = {}  # discord_user_id -> steam_id
        self.load_user_mappings()
        
        # Add commands
        self.setup_commands()
    
    def load_user_mappings(self):
        """Load Discord user to Steam ID mappings"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    data = json.load(f)
                    self.user_mappings = {int(k): v for k, v in data.get('user_mappings', {}).items()}
            except (json.JSONDecodeError, IOError):
                self.user_mappings = {}
    
    def save_user_mappings(self):
        """Save Discord user to Steam ID mappings"""
        try:
            data = {'user_mappings': {str(k): v for k, v in self.user_mappings.items()}}
            with open(self.config_file, 'w') as f:
                json.dump(data, f, indent=2)
        except IOError as e:
            print(f"Error saving user mappings: {e}")

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
                                min_metacritic: Optional[int] = None) -> List[Dict]:
        """Filter to multiplayer/co-op games with optional additional constraints."""
        coop_games = self.multi_picker.filter_coop_games(games)
        if not coop_games:
            return []
        if genre or min_metacritic is not None:
            genres = [genre] if genre else None
            coop_games = self.multi_picker.filter_games(
                coop_games,
                genres=genres,
                min_metacritic=min_metacritic,
            )
        return coop_games

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

        filtered_games = self._filter_vote_candidates(
            common_games,
            genre=latest.get('genre'),
            min_metacritic=latest.get('min_metacritic'),
        )
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
            final_lines = [f"🏆 Winner: **{winner.get('name', 'Unknown Game')}**"]
            if winner_app_id:
                final_lines.append(f"Steam Store: https://store.steampowered.com/app/{winner_app_id}/")
            await channel.send("\n".join(final_lines))
            return

    async def _start_public_vote_round(self, channel: discord.abc.Messageable, participants: List[str],
                                       duration: int, num_candidates: int,
                                       restart_count: int = 0) -> bool:
        """Start one public reaction-vote round with a NOTA option."""
        common_games = self.multi_picker.find_common_games(participants)
        if not common_games:
            await channel.send("❌ No common games found among linked users.")
            return False

        common_games = self.multi_picker.filter_coop_games(common_games)
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
        description_lines = [
            f"React with your choice! Voting ends in **{duration} seconds**.",
            "Co-op / multiplayer games only."
        ]
        for i, game in enumerate(candidate_games):
            description_lines.append(f"{NUMBER_EMOJIS[i]}  **{game.get('name', 'Unknown')}**")
        description_lines.append(f"{nota_emoji}  **None of these**")

        embed = discord.Embed(
            title="🗳️ Vote for a Game!" + (f" (Restart {restart_count})" if restart_count else ""),
            description="\n".join(description_lines),
            color=discord.Color.green(),
        )
        embed.set_footer(text=f"Session ID: {session.session_id[:8]}")
        vote_msg = await channel.send(embed=embed)

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
        }

        await asyncio.sleep(duration)
        await self.process_vote(channel)
        return True
    
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
                f"Admin: {base_url}/#admin\n"
                f"Sessions: Open the 🎯 Sessions tab from {base_url}"
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
                description="Quick reference for common commands (votes include a 'None of these' option)"
            )
            embed.add_field(name="Account", value="`/link` • `/unlink` • `/linked` • `/users`", inline=False)
            embed.add_field(name="Game Picks", value="`/pick` • `/common` • `/vote` • `/voteprivate` • `/joinvote` • `/leavevote` • `/stats`", inline=False)
            embed.add_field(name="Utilities", value="`/url` • `/invite` • `/ping` • `/botstatus` • `/ignore` • `/hunt`", inline=False)
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
            if min_metacritic is not None:
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
                f"Use `/joinvote` in this channel to join. Join window: **{join_duration}s**\n"
                f"Vote duration: **{vote_duration}s**, candidates: **{candidates}**\n"
                f"Filters: {', '.join(filter_bits)}"
            )

            asyncio.create_task(self._run_private_vote(channel, lobby))

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
            duration='Duration in seconds for voting session (default: 60)',
            candidates='Number of game candidates to vote on (default: 5, max: 10 for public reaction vote)'
        )
        async def start_vote(interaction: discord.Interaction, duration: int = 60,
                             candidates: int = 5):
            """Start a public reaction vote for co-op/multiplayer games among linked users."""
            channel_id = interaction.channel_id
            channel = interaction.channel
            
            if channel_id is None or channel is None:
                await interaction.response.send_message("❌ This command must be used in a channel!")
                return

            if channel_id in self.active_votes:
                await interaction.response.send_message("❌ A voting session is already active in this channel!")
                return

            num_candidates = max(2, min(candidates, 10))

            # Gather participants from linked users
            participants = [u['name'] for u in self.multi_picker.users]
            if not participants:
                await interaction.response.send_message(
                    "❌ No users have linked their Steam accounts. Use `/link` first."
                )
                return

            await interaction.response.send_message("🔍 Finding common games for a vote…")
            await self._start_public_vote_round(
                channel=channel,
                participants=participants,
                duration=duration,
                num_candidates=num_candidates,
                restart_count=0,
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
            
            # Pick a common game
            game = self.multi_picker.pick_common_game(participants, coop_only=True)
            
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

        # Clean up active votes entry early to prevent double-processing
        del self.active_votes[channel_id]

        if not session or not candidate_games:
            await channel.send("❌ Voting session data missing.")
            return

        # Tally reactions from the vote message
        if vote_msg:
            try:
                vote_msg = await channel.fetch_message(vote_msg.id)
            except Exception:
                pass

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
                elif emoji_str == nota_emoji:
                    async for user in reaction.users():
                        if not user.bot:
                            voter_name = user.name
                            session.cast_vote(voter_name, '__NOTA__')

        # Close session and determine winner
        session.close()
        winner = session.get_winner()
        results = session.get_results()

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

        embed = discord.Embed(
            title=f"🎮 Let's play: {winner.get('name', 'Unknown Game')}!",
            color=discord.Color.gold()
        )
        embed.add_field(name="App ID", value=str(app_id), inline=True)
        embed.add_field(name="Total Votes", value=str(len(session.votes)), inline=True)

        if app_id:
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

        await channel.send(embed=embed)


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
