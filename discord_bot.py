#!/usr/bin/env python3
"""
GAPI Discord Bot
Discord integration for multi-user game picking with voting and co-op support.
"""

import discord
from discord import app_commands
import json
import os
import asyncio
from typing import Dict, List, Set, Optional
from datetime import datetime, timedelta
import multiuser


class GAPIBot(discord.Client):
    """Discord bot for GAPI game picking"""
    
    def __init__(self, config: Dict, config_file: str = 'discord_config.json'):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        
        super().__init__(intents=intents)
        
        self.tree = app_commands.CommandTree(self)
        
        self.config = config
        self.steam_api_key = config.get('steam_api_key')
        self.config_file = config_file
        self.multi_picker = multiuser.MultiUserPicker(config)
        
        # Active voting sessions
        self.active_votes: Dict[int, Dict] = {}  # channel_id -> vote_data
        
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
    
    def setup_commands(self):
        """Register slash commands"""
        
        @self.tree.command(name='link', description='Link your Discord account to your Steam ID')
        @app_commands.describe(
            steam_id='Your Steam ID (64-bit format)',
            username='Optional: Custom username (defaults to your Discord name)'
        )
        async def link_steam(interaction: discord.Interaction, steam_id: str, username: str = None):
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
            
            user_list = "\n".join([f"• {user['name']} (Steam ID: {user['steam_id']})" 
                                  for user in self.multi_picker.users])
            
            embed = discord.Embed(
                title="🎮 Linked Steam Accounts",
                description=user_list,
                color=discord.Color.blue()
            )
            await interaction.response.send_message(embed=embed)
        
        @self.tree.command(name='vote', description='Start a voting session to play a game')
        @app_commands.describe(
            duration='Duration in seconds for voting session (default: 60)',
            candidates='Number of game candidates to vote on (default: 5, max: 10)'
        )
        async def start_vote(interaction: discord.Interaction, duration: int = 60,
                             candidates: int = 5):
            """Start a game-choice voting session for all linked users"""
            channel_id = interaction.channel_id

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

            # Pick candidate games from the common library
            common_games = self.multi_picker.find_common_games(participants)
            if not common_games:
                await interaction.followup.send(
                    "❌ No common games found among linked users."
                )
                return

            import random as _random
            candidate_games = _random.sample(
                common_games, min(num_candidates, len(common_games))
            )

            # Create a voting session
            session = self.multi_picker.create_voting_session(
                candidate_games, voters=participants, duration=duration
            )

            # Build the voting embed
            NUMBER_EMOJIS = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣', '🔟']
            description_lines = [
                f"React with the number of the game you want to play!\n"
                f"Voting ends in **{duration} seconds**.\n"
            ]
            for i, game in enumerate(candidate_games):
                description_lines.append(f"{NUMBER_EMOJIS[i]}  **{game.get('name', 'Unknown')}**")

            embed = discord.Embed(
                title="🗳️ Vote for a Game!",
                description="\n".join(description_lines),
                color=discord.Color.green()
            )
            embed.set_footer(text=f"Session ID: {session.session_id[:8]}")

            await interaction.followup.send(embed=embed)
            vote_msg = await interaction.original_response()

            # Add number reactions
            for i in range(len(candidate_games)):
                await vote_msg.add_reaction(NUMBER_EMOJIS[i])

            # Store session info
            self.active_votes[channel_id] = {
                'session': session,
                'message': vote_msg,
                'candidate_games': candidate_games,
                'emojis': NUMBER_EMOJIS[:len(candidate_games)],
                'participants': participants,
            }

            # Wait for voting to end
            await asyncio.sleep(duration)

            # Process results
            await self.process_vote(interaction.channel)
        
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
            user1: discord.User = None,
            user2: discord.User = None,
            user3: discord.User = None,
            user4: discord.User = None,
            user5: discord.User = None
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

        await channel.send("\n".join(results_lines))

        if not winner:
            await channel.send("❌ Could not determine a winner.")
            return

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
    
    # Load configuration
    config_path = 'config.json'
    if not os.path.exists(config_path):
        print("❌ config.json not found!")
        sys.exit(1)
    
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    steam_api_key = config.get('steam_api_key')
    discord_token = config.get('discord_bot_token')
    
    if not steam_api_key:
        print("❌ steam_api_key not found in config.json")
        sys.exit(1)
    
    if not discord_token:
        print("❌ discord_bot_token not found in config.json")
        print("Please add your Discord bot token to config.json")
        sys.exit(1)
    
    run_bot(discord_token, config)
