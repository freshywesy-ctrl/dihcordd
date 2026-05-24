import os
import asyncio
import threading
import discord
from discord import app_commands

# ── Startup input ─────────────────────────────────────────────────────────────
TOKEN    = input("Enter your Discord bot token: ").strip()
GUILD_ID = int(input("Enter your Guild (Server) ID: ").strip())

if not TOKEN:
    raise RuntimeError("No token entered.")

# ── State ─────────────────────────────────────────────────────────────────────
locks: dict[int, dict[int, str]] = {}

# ── Client setup ──────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.voice_states = True
intents.members = True

class Bot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        print("✅  Slash commands synced to guild.")

    async def on_ready(self):
        print(f"✅  Logged in as {self.user} (ID: {self.user.id})")
        await self.change_presence(activity=discord.Activity(
            type=discord.ActivityType.watching, name="🔇 Keeping the peace"
        ))


bot = Bot()

# ── Permission check ──────────────────────────────────────────────────────────
LOCK_ROLE_NAME = "bot perm"

def has_mute_permission(interaction: discord.Interaction) -> bool:
    role = discord.utils.get(interaction.guild.roles, name=LOCK_ROLE_NAME)
    return role is not None and role in interaction.user.roles

# ── Apply lock immediately if target is in voice ──────────────────────────────
async def apply_lock(guild: discord.Guild, user_id: int, mode: str):
    try:
        member = await guild.fetch_member(user_id)
        if not member.voice or not member.voice.channel:
            print("  (User is not in a voice channel — lock saved, will apply on join)")
            return
        if mode == "deaf" and not member.voice.deaf:
            await member.edit(deafen=True, reason="Lock-deaf active")
            print("  (Deafen applied immediately)")
        elif mode == "mute" and not member.voice.mute:
            await member.edit(mute=True, reason="Lock-mute active")
            print("  (Mute applied immediately)")
    except Exception as e:
        print(f"  Error: {e}")

# ── Terminal command loop ─────────────────────────────────────────────────────
def terminal_commands():
    print("Terminal commands: lockdeaf <userID>, lockmute <userID>, unlock <userID>, locklist")
    while True:
        try:
            cmd = input("> ").strip().split()
            if not cmd:
                continue

            command = cmd[0].lower()
            user_id = int(cmd[1]) if len(cmd) > 1 else None

            if command in ("lockdeaf", "lockmute") and user_id:
                mode = "deaf" if command == "lockdeaf" else "mute"
                locks.setdefault(GUILD_ID, {})[user_id] = mode
                guild = bot.get_guild(GUILD_ID)
                if guild:
                    asyncio.run_coroutine_threadsafe(
                        apply_lock(guild, user_id, mode), bot.loop
                    )
                print(f"✅ {command} applied to {user_id}")

            elif command == "unlock" and user_id:
                guild_locks = locks.get(GUILD_ID, {})
                if user_id in guild_locks:
                    mode = guild_locks.pop(user_id)
                    guild = bot.get_guild(GUILD_ID)
                    if guild:
                        member = guild.get_member(user_id)
                        if member and member.voice and member.voice.channel:
                            async def do_unlock():
                                if mode == "deaf":
                                    await member.edit(deafen=False, reason="Lock removed")
                                else:
                                    await member.edit(mute=False, reason="Lock removed")
                            asyncio.run_coroutine_threadsafe(do_unlock(), bot.loop)
                    print(f"✅ Unlocked {user_id}")
                else:
                    print("No lock found for that user.")

            elif command == "locklist":
                guild_locks = locks.get(GUILD_ID, {})
                if not guild_locks:
                    print("No active locks.")
                else:
                    for uid, mode in guild_locks.items():
                        print(f"  User {uid} → {mode}")

            else:
                print("Commands: lockdeaf <userID> | lockmute <userID> | unlock <userID> | locklist")

        except (ValueError, IndexError):
            print("Invalid input. User ID must be a number.")
        except EOFError:
            break

# ── Voice state update — re-apply lock on every state change ─────────────────

@bot.event
async def on_voice_state_update(
    member: discord.Member,
    before: discord.VoiceState,
    after: discord.VoiceState,
):
    guild_locks = locks.get(member.guild.id, {})
    if member.id not in guild_locks:
        return

    if not after.channel:
        return

    mode = guild_locks[member.id]
    try:
        if mode == "deaf" and not after.deaf:
            await member.edit(deafen=True, reason="Lock-deaf re-applied")
            print(f"  (Re-applied deaf lock on {member})")
        elif mode == "mute" and not after.mute:
            await member.edit(mute=True, reason="Lock-mute re-applied")
            print(f"  (Re-applied mute lock on {member})")
    except Exception as e:
        print(f"Failed to re-apply lock for {member}: {e}")

# ── Slash commands ────────────────────────────────────────────────────────────
@bot.tree.command(name="lockdeaf", description="Keep a member server-deafened constantly.")
@app_commands.describe(target="Member to lock-deafen")
async def slash_lockdeaf(interaction: discord.Interaction, target: discord.Member):
    if not has_mute_permission(interaction):
        return await interaction.response.send_message("❌ You need the **Deafen Members** permission.", ephemeral=True)
    locks.setdefault(interaction.guild_id, {})[target.id] = "deaf"
    await apply_lock(interaction.guild, target.id, "deaf")
    await interaction.response.send_message(f"🔇 **{target.display_name}** is now lock-deafened.")

@bot.tree.command(name="lockmute", description="Keep a member server-muted constantly.")
@app_commands.describe(target="Member to lock-mute")
async def slash_lockmute(interaction: discord.Interaction, target: discord.Member):
    if not has_mute_permission(interaction):
        return await interaction.response.send_message("❌ You need the **Mute Members** permission.", ephemeral=True)
    locks.setdefault(interaction.guild_id, {})[target.id] = "mute"
    await apply_lock(interaction.guild, target.id, "mute")
    await interaction.response.send_message(f"🔕 **{target.display_name}** is now lock-muted.")

@bot.tree.command(name="unlock", description="Remove deafen/mute lock from a member.")
@app_commands.describe(target="Member to unlock")
async def slash_unlock(interaction: discord.Interaction, target: discord.Member):
    if not has_mute_permission(interaction):
        return await interaction.response.send_message("❌ You need the **Mute Members** permission.", ephemeral=True)
    guild_locks = locks.get(interaction.guild_id, {})
    if target.id not in guild_locks:
        return await interaction.response.send_message(f"{target.display_name} has no active lock.", ephemeral=True)
    mode = guild_locks.pop(target.id)
    if target.voice and target.voice.channel:
        if mode == "deaf":
            await target.edit(deafen=False, reason="Lock removed")
        else:
            await target.edit(mute=False, reason="Lock removed")
    await interaction.response.send_message(f"✅ Lock removed from **{target.display_name}**.")

@bot.tree.command(name="locklist", description="Show all currently locked members.")
async def slash_locklist(interaction: discord.Interaction):
    guild_locks = locks.get(interaction.guild_id, {})
    if not guild_locks:
        return await interaction.response.send_message("No members are currently locked.", ephemeral=True)
    lines = [
        f"<@{uid}> — **{'lock-deafened' if mode == 'deaf' else 'lock-muted'}**"
        for uid, mode in guild_locks.items()
    ]
    await interaction.response.send_message("**Locked members:**\n" + "\n".join(lines), ephemeral=True)

# ── Run ───────────────────────────────────────────────────────────────────────
threading.Thread(target=terminal_commands, daemon=True).start()
bot.run(TOKEN)