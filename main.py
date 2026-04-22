import discord
from discord.ext import commands
import asyncio
import os
import time

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix="%", intents=intents)

SESSION_DURATION = 3600
REJOIN_DELAY = 2
CHECK_INTERVAL = 5

active_sessions = {}


class VoiceSession:
    def __init__(self, channel: discord.VoiceChannel, end_time: float):
        self.channel = channel
        self.end_time = end_time
        self.voice_client = None
        self.task = None
        self.should_run = True

    def time_remaining(self) -> float:
        return max(0, self.end_time - time.time())

    def is_expired(self) -> bool:
        return time.time() >= self.end_time


async def safe_disconnect(vc):
    try:
        await vc.disconnect(force=True)
    except Exception:
        pass
    try:
        vc.cleanup()
    except Exception:
        pass


async def voice_session_loop(session: VoiceSession, guild_id: int):
    while session.should_run and not session.is_expired():
        vc = session.voice_client
        connected = vc is not None and vc.is_connected()

        if not connected:
            if vc is not None:
                await safe_disconnect(vc)
                session.voice_client = None

            guild_vc = session.channel.guild.voice_client
            if guild_vc is not None:
                await safe_disconnect(guild_vc)

            await asyncio.sleep(REJOIN_DELAY)

            if session.is_expired() or not session.should_run:
                break

            try:
                session.voice_client = await session.channel.connect()
                print(f"[Bot] Connected to {session.channel.name} in guild {guild_id}")
            except Exception as e:
                print(f"[Bot] Failed to connect: {e}, retrying in {REJOIN_DELAY}s...")
                session.voice_client = None
                await asyncio.sleep(REJOIN_DELAY)
                continue

        remaining = session.time_remaining()
        if remaining <= 0:
            break

        await asyncio.sleep(min(CHECK_INTERVAL, remaining))

    vc = session.voice_client
    if vc is not None:
        await safe_disconnect(vc)
        session.voice_client = None
        print(f"[Bot] 1-hour session ended, disconnected from {session.channel.name}")

    active_sessions.pop(guild_id, None)


@bot.event
async def on_ready():
    print(f"[Bot] Logged in as {bot.user} (ID: {bot.user.id})")
    print("[Bot] Ready! Use %join in a server where you are in a voice channel.")


@bot.command(name="join")
async def join(ctx: commands.Context):
    if ctx.guild is None:
        await ctx.send("This command can only be used in a server.")
        return

    voice_state = ctx.author.voice
    if voice_state is None or voice_state.channel is None:
        await ctx.send("You need to be in a voice channel first!")
        return

    guild_id = ctx.guild.id
    channel = voice_state.channel

    if guild_id in active_sessions:
        existing = active_sessions[guild_id]
        mins_left = int(existing.time_remaining() / 60)
        await ctx.send(
            f"I'm already active in **{existing.channel.name}**! "
            f"I'll stay for **{mins_left}** more minute(s)."
        )
        return

    existing_vc = ctx.guild.voice_client
    if existing_vc is not None:
        await safe_disconnect(existing_vc)

    end_time = time.time() + SESSION_DURATION
    session = VoiceSession(channel=channel, end_time=end_time)
    active_sessions[guild_id] = session

    try:
        session.voice_client = await channel.connect()
    except Exception as e:
        active_sessions.pop(guild_id, None)
        await ctx.send(f"Failed to join the voice channel: {e}")
        return

    session.task = asyncio.create_task(voice_session_loop(session, guild_id))

    await ctx.send(
        f"Joined **{channel.name}**! I'll stay for **1 hour**. "
        f"If I get disconnected, I'll rejoin within {REJOIN_DELAY} seconds automatically."
    )


token = os.environ.get("DISCORD_BOT_TOKEN")
if not token:
    raise RuntimeError("DISCORD_BOT_TOKEN environment variable is not set!")

bot.run(token)
