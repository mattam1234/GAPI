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
    
    def __init__(self, steam_api_key: str, config_file: str = 'discord_config.json'):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        
        super().__init__(intents=intents)
        
        self.tree = app_commands.CommandTree(self)
        
        self.steam_api_key = steam_api_key
        self.config_file = config_file
        self.multi_picker = multiuser.MultiUserPicker(steam_api_key)
        
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
        @app_commands.describe(duration='Duration in seconds for voting session (default: 60)')
        async def start_vote(interaction: discord.Interaction, duration: int = 60):
            """Start a voting session for picking a co-op game"""
            channel_id = interaction.channel_id
            
            if channel_id in self.active_votes:
                await interaction.response.send_message("❌ A voting session is already active in this channel!")
                return
            
            # Initialize vote
            self.active_votes[channel_id] = {
                'participants': set(),
                'votes': {},
                'end_time': datetime.now() + timedelta(seconds=duration),
                'message': None
            }
            
            embed = discord.Embed(
                title="🗳️ Vote to Play!",
                description=f"React with ✅ to join the game picking session!\n"
                           f"Voting ends in {duration} seconds.",
                color=discord.Color.green()
            )
            
            await interaction.response.send_message(embed=embed)
            vote_msg = await interaction.original_response()
            await vote_msg.add_reaction('✅')
            
            self.active_votes[channel_id]['message'] = vote_msg
            
            # Wait for voting to end
            await asyncio.sleep(duration)
            
            # Process results
            await self.process_vote(interaction.channel)
        
        @self.tree.command(name='pick', description='Pick a random game for mentioned users or all linked users')
        @app_commands.describe(
            user1='First user to include (optional)',
            user2='Second user to include (optional)',
            user3='Third user to include (optional)',
            user4='Fourth user to include (optional)',
            user5='Fifth user to include (optional)'
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
                await interaction.response.send_message("❌ No linked users found! Use `/link <steam_id>` to link your account.")
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
        """Process voting results and pick a game"""
        channel_id = channel.id
        
        if channel_id not in self.active_votes:
            return
        
        vote_data = self.active_votes[channel_id]
        vote_msg = vote_data['message']
        
        # Get users who reacted with ✅
        if vote_msg:
            vote_msg = await channel.fetch_message(vote_msg.id)
            for reaction in vote_msg.reactions:
                if str(reaction.emoji) == '✅':
                    async for user in reaction.users():
                        if not user.bot and user.id in self.user_mappings:
                            vote_data['participants'].add(user.name)
        
        participants = list(vote_data['participants'])
        
        # Clean up
        del self.active_votes[channel_id]
        
        if not participants:
            await channel.send("❌ No participants found! Make sure you've linked your Steam account with `!gapi link`")
            return
        
        await channel.send(f"🎲 Picking a game for {len(participants)} player(s): {', '.join(participants)}")
        
        # Pick a game
        game = self.multi_picker.pick_common_game(participants, coop_only=True, max_players=len(participants))
        
        if not game:
            await channel.send(f"❌ No common co-op games found for the selected players.")
            return
        
        # Display result
        embed = discord.Embed(
            title=f"🎮 Let's play: {game.get('name', 'Unknown Game')}!",
            color=discord.Color.gold()
        )
        
        app_id = game.get('appid')
        embed.add_field(name="App ID", value=str(app_id), inline=True)
        embed.add_field(name="Players", value=str(len(participants)), inline=True)
        
        if 'is_coop' in game:
            mode = "Co-op" if game['is_coop'] else "Multiplayer"
            embed.add_field(name="Mode", value=mode, inline=True)
        
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


def run_bot(token: str, steam_api_key: str):
    """Run the Discord bot"""
    bot = GAPIBot(steam_api_key)
    
    @bot.event
    async def on_ready():
        print(f'✅ {bot.user} is now online!')
        print(f'Loaded {len(bot.multi_picker.users)} linked Steam accounts')
        
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
    
    run_bot(discord_token, steam_api_key)
