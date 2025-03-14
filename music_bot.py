import discord
from discord.ext import commands
from discord import ui, Interaction, Embed
import yt_dlp
import asyncio
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from collections import deque
import sys
import os
import traceback

# Spotify API Credentials
# Replace these with your own Spotify API credentials
SPOTIFY_CLIENT_ID = "your_spotify_client_id"
SPOTIFY_CLIENT_SECRET = "your_spotify_client_secret"

# Configure Spotify API
sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
    client_id=SPOTIFY_CLIENT_ID,
    client_secret=SPOTIFY_CLIENT_SECRET
))

# Discord bot token
# Replace this with your own Discord bot token
token = "your_discord_bot_token"

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", help_command=None, intents=intents)  # Creating our bot

# Queue management
queue = deque()
current_song = None
current_message = None

# Colors for embeds
NEGATIVE_COLOR = 0xf94b2c
POSITIVE_COLOR = 0x483182

class QueueView(ui.View):
    def __init__(self, queue_list, max_per_page=15):
        super().__init__(timeout=None)
        self.queue_list = queue_list
        self.max_per_page = max_per_page
        self.current_page = 0

    def get_total_pages(self):
        return (len(self.queue_list) // self.max_per_page) + (1 if len(self.queue_list) % self.max_per_page != 0 else 0)

    def get_page_content(self):
        start = self.current_page * self.max_per_page
        end = start + self.max_per_page
        page_queue = self.queue_list[start:end]
        queue_str = "\n".join([f"{i + 1}. {song}" for i, song in enumerate(page_queue, start=start + 1)])
        return queue_str or "No tracks on this page."

    @ui.button(label="⬅️ Previous", style=discord.ButtonStyle.secondary, row=0)
    async def previous_page(self, interaction: Interaction, button: ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            await self.update_message(interaction)

    @ui.button(label="➡️ Next", style=discord.ButtonStyle.secondary, row=0)
    async def next_page(self, interaction: Interaction, button: ui.Button):
        if self.current_page < self.get_total_pages() - 1:
            self.current_page += 1
            await self.update_message(interaction)

    async def update_message(self, interaction: Interaction):
        embed = Embed(
            title="Queue",
            description=self.get_page_content(),
            color=POSITIVE_COLOR  # Use positive color
        )
        embed.set_footer(text=f"Page {self.current_page + 1}/{self.get_total_pages()}")
        await interaction.response.edit_message(embed=embed, view=self)

# Music control buttons
class MusicControls(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.current_page = 0  # Initial page
        self.max_per_page = 15  # Maximum number of tracks per page

    @ui.button(label="⏸️ Pause", style=discord.ButtonStyle.primary, row=0)
    async def pause(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
            interaction.guild.voice_client.pause()
            await interaction.response.send_message("Playback paused.", ephemeral=True)
        else:
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)

    @ui.button(label="▶️ Resume", style=discord.ButtonStyle.success, row=0)
    async def resume(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.guild.voice_client and interaction.guild.voice_client.is_paused():
            interaction.guild.voice_client.resume()
            await interaction.response.send_message("Playback resumed.", ephemeral=True)
        else:
            await interaction.response.send_message("Nothing is paused.", ephemeral=True)

    @ui.button(label="⏭️ Skip", style=discord.ButtonStyle.secondary, row=0)
    async def skip(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
            interaction.guild.voice_client.stop()
            await interaction.response.send_message("Skipped the current track.", ephemeral=True)
        else:
            await interaction.response.send_message("Nothing to skip.", ephemeral=True)

    @ui.button(label="🧹 Reset Queue", style=discord.ButtonStyle.danger, row=1)
    async def reset_queue(self, interaction: discord.Interaction, button: ui.Button):
        """Clear the entire queue"""
        queue.clear()  # Empty the queue
        await interaction.response.send_message("Queue has been cleared!", ephemeral=True)

    @ui.button(label="📜 Show Queue", style=discord.ButtonStyle.secondary, row=1)
    async def show_queue(self, interaction: Interaction, button: ui.Button):
        """Show the queue with pagination"""
        if queue:
            max_per_page = 15
            queue_list = list(queue)  # Convert queue to list
            total_pages = (len(queue_list) // max_per_page) + (1 if len(queue_list) % max_per_page != 0 else 0)

            # Create a view with the queue
            queue_view = QueueView(queue_list, max_per_page=max_per_page)
            embed = Embed(
                title="Queue",
                description=queue_view.get_page_content(),
                color=POSITIVE_COLOR  # Use positive color
            )
            embed.set_footer(text=f"Page {queue_view.current_page + 1}/{queue_view.get_total_pages()}")
            await interaction.response.send_message(embed=embed, view=queue_view, ephemeral=True)
        else:
            embed = Embed(
                title="Queue is Empty",
                description="There are no songs in the queue.",
                color=NEGATIVE_COLOR  # Use negative color
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

# Function to fetch track information from a Spotify link
def get_spotify_tracks(query):
    try:
        if "spotify.com" in query:
            if "track" in query:  # Track
                track_info = sp.track(query)
                return [f"{track_info['artists'][0]['name']} - {track_info['name']}"]
            elif "album" in query:  # Album
                album_info = sp.album(query)
                return [f"{track['artists'][0]['name']} - {track['name']}" for track in album_info['tracks']['items']]
            elif "playlist" in query:  # Playlist
                playlist_info = sp.playlist(query)
                return [f"{item['track']['artists'][0]['name']} - {item['track']['name']}" for item in playlist_info['tracks']['items']]
        else:
            return [query]
    except Exception as e:
        print(f"Error with Spotify: {e}")
        return None

# Function to fetch YouTube link or playlist
def give_link(query):
    """Function to fetch YouTube link or playlist."""
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"ytsearch:{query}", download=False)
        # If it's a playlist
        if 'entries' in info:
            return [entry['url'] for entry in info['entries']]
        else:
            return [info['url']]  # Return single link if it's not a playlist

# Function to play the next song in the queue
async def play_next(ctx):
    """Play the next song in the queue."""
    global current_song
    if queue:
        current_song = queue.popleft()
        
        # If it's a list (playlist), play all songs in the list
        if isinstance(current_song, list):
            for song_url in current_song:
                await play_single(ctx, song_url, song_url)
        else:
            # Single song (not a playlist)
            url = give_link(current_song)[0]
            await play_single(ctx, url, current_song)
    else:
        current_song = None
        await ctx.send("Queue is empty, playback finished.")

# Function to play a single track
async def play_single(ctx, url, title):
    """Play a single track."""
    global current_message  # Reference to global variable

    voice_client = ctx.voice_client
    if not voice_client:
        voice_channel = ctx.author.voice.channel
        voice_client = await voice_channel.connect()

    ffmpeg_options = {
        'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
        'options': '-vn'
    }

    try:
        # Pass URL to FFmpegPCMAudio, ensure it's a single track
        voice_client.play(
            discord.FFmpegPCMAudio(url, **ffmpeg_options),
            after=lambda e: asyncio.run_coroutine_threadsafe(play_next(ctx), bot.loop)
        )
        
        # Delete previous message before sending a new one (if exists)
        if current_message:
            await current_message.delete()

        # Create embed with track information
        embed = discord.Embed(
            title="Now Playing",
            description=f"Now playing: {title}",
            color=POSITIVE_COLOR
        )

        # Send message with embed and new buttons
        current_message = await ctx.send(embed=embed, view=MusicControls())

    except Exception as e:
        # If an error occurred, delete previous message
        if current_message:
            await current_message.delete()

        embed = discord.Embed(
            title="Error",
            description=f"An error occurred while trying to play the track: {str(e)}",
            color=NEGATIVE_COLOR
        )
        current_message = await ctx.send(embed=embed)

@bot.command(name="play")
async def play(ctx, *, query):
    """Add a track or playlist to the queue and start playing."""
    global current_song

    # Handle Spotify
    if "spotify.com" in query:
        spotify_tracks = get_spotify_tracks(query)
        
        if spotify_tracks:
            queue.extend(spotify_tracks)
            embed = discord.Embed(
                title="Tracks Added to Queue",
                description=f"Added {len(spotify_tracks)} tracks to the queue.",
                color=POSITIVE_COLOR
            )
        else:
            embed = discord.Embed(
                title="Error Adding Tracks",
                description="No valid tracks found from the Spotify link.",
                color=NEGATIVE_COLOR
            )
        
        await ctx.send(embed=embed)
        
    # Handle YouTube (playlist)
    elif "youtube.com" in query:
        links = give_link(query)
        
        if links:
            queue.extend(links)
            embed = discord.Embed(
                title="Playlist Added to Queue",
                description=f"Added {len(links)} videos to the queue from the playlist.",
                color=POSITIVE_COLOR
            )
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(
                title="Error",
                description="Could not retrieve any tracks from the YouTube link.",
                color=NEGATIVE_COLOR
            )
            await ctx.send(embed=embed)
    
    # Handle single track
    else:
        queue.append(query)
        embed = discord.Embed(
            title="Track Added to Queue",
            description=f"Added `{query}` to the queue.",
            color=POSITIVE_COLOR
        )
        await ctx.send(embed=embed)

    # If nothing is playing, start playing
    if not current_song:
        await play_next(ctx)

@bot.command(name="skip")
async def skip(ctx):
    """Skip the current track."""
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        await ctx.send("Skipped the current track.", embed=discord.Embed(color=POSITIVE_COLOR))
    else:
        await ctx.send("Nothing to skip.", embed=discord.Embed(color=NEGATIVE_COLOR))

@bot.command(name="pause")
async def pause(ctx):
    """Pause the current track."""
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        await ctx.send("Playback paused.", embed=discord.Embed(color=POSITIVE_COLOR))
    else:
        await ctx.send("Nothing is playing.", embed=discord.Embed(color=NEGATIVE_COLOR))

@bot.command(name="resume")
async def resume(ctx):
    """Resume the current track."""
    if ctx.voice_client and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        await ctx.send("Playback resumed.", embed=discord.Embed(color=POSITIVE_COLOR))
    else:
        await ctx.send("Nothing is paused.", embed=discord.Embed(color=NEGATIVE_COLOR))

@bot.command(name="stop")
async def stop(ctx):
    """Stop playback."""
    if ctx.voice_client:
        ctx.voice_client.stop()
        await ctx.send("Playback stopped.", embed=discord.Embed(color=POSITIVE_COLOR))
    else:
        await ctx.send("Nothing is playing.", embed=discord.Embed(color=NEGATIVE_COLOR))

@bot.command(name="leave")
async def leave(ctx):
    """Leave the voice channel."""
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("Disconnected from the voice channel.", embed=discord.Embed(color=POSITIVE_COLOR))
    else:
        await ctx.send("I'm not connected to any voice channel.", embed=discord.Embed(color=NEGATIVE_COLOR))

# Function to restart the bot
def restart_bot():
    """Restart the bot process."""
    print("Restarting bot...")
    os.execv(sys.executable, ['python'] + sys.argv)

# Global error handler for events
@bot.event
async def on_error(event_method, *args, **kwargs):
    """Global error handler for events."""
    print(f"Error in {event_method}:")
    traceback.print_exc()
    restart_bot()

# Global error handler for commands
@bot.event
async def on_command_error(ctx, error):
    """Global error handler for commands."""
    print(f"Error in command '{ctx.command}': {error}")
    traceback.print_exc()
    await ctx.send("An error occurred. Restarting the bot...")
    restart_bot()

# Start the bot with exception handling
while True:
    try:
        bot.run(token)
    except Exception as e:
        print("Critical error occurred, restarting bot...")
        traceback.print_exc()
        asyncio.sleep(5)  # Optional delay before restart

