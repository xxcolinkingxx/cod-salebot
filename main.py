import os
import aiohttp
import asyncio
import discord
from discord.ext import tasks
from datetime import datetime
from bs4 import BeautifulSoup
import threading
from flask import Flask
from dotenv import load_dotenv

# -------------------------
# LOAD SECRETS
# -------------------------
load_dotenv("secret.env")

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "0"))

# -------------------------
# GAME LINKS
# -------------------------
STEAM_GAMES = {
    "Black Ops 1": "https://store.steampowered.com/app/42700/",
    "Black Ops 2": "https://store.steampowered.com/app/202970/",
    "Black Ops 3": "https://store.steampowered.com/app/311210/",
}
BATTLENET_GAMES = {
    "Black Ops 4": "https://us.shop.battle.net/en-us/product/call-of-duty-black-ops-4",
    "Cold War": "https://us.shop.battle.net/en-us/product/call-of-duty-black-ops-cold-war",
}
XBOX_TITLES = {
    "Black Ops 3": "https://www.xbox.com/en-US/games/store/call-of-duty-black-ops-iii/C3Q2WWJJ2T1H",
    "Black Ops 4": "https://www.xbox.com/en-US/games/store/call-of-duty-black-ops-4/C19N0723PHFL",
}
PS_TITLES = {
    "Black Ops 3": "https://store.playstation.com/en-us/product/UP0002-CUSA02290_00-CODBO3ZOMBIESEDN",
}

CHECK_INTERVAL = 3600  # seconds (1 hour)
SEEN_FILE = "seen_sales.txt"

# -------------------------
# DISCORD SETUP
# -------------------------
intents = discord.Intents.default()
client = discord.Client(intents=intents)

# -------------------------
# FILE HANDLERS
# -------------------------
def load_seen():
    if not os.path.exists(SEEN_FILE):
        return set()
    with open(SEEN_FILE, "r") as f:
        return set(line.strip() for line in f if line.strip())

def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        for item in seen:
            f.write(item + "\n")

seen_sales = load_seen()

# -------------------------
# SCRAPERS
# -------------------------
async def check_steam(session):
    found = []
    for name, url in STEAM_GAMES.items():
        try:
            async with session.get(url) as resp:
                html = await resp.text()
                soup = BeautifulSoup(html, "html.parser")
                discount = soup.select_one(".discount_pct")
                final_price = soup.select_one(".discount_final_price")
                original_price = soup.select_one(".discount_original_price")

                if discount:
                    off = discount.text.strip()
                    now = final_price.text.strip() if final_price else "N/A"
                    was = original_price.text.strip() if original_price else "N/A"
                    unique = f"steam_{name}"
                    found.append((unique, name, url, off, was, now))
        except Exception as e:
            print(f"[Steam] Error checking {name}: {e}")
    return found

async def check_battlenet(session):
    found = []
    for name, url in BATTLENET_GAMES.items():
        try:
            async with session.get(url) as resp:
                html = await resp.text()
                if any(term in html.lower() for term in ["sale", "% off", "discount"]):
                    unique = f"bnet_{name}"
                    found.append((unique, name, url, "On Sale", None, None))
        except Exception as e:
            print(f"[Battle.net] Error checking {name}: {e}")
    return found

async def check_xbox(session):
    found = []
    for name, url in XBOX_TITLES.items():
        try:
            async with session.get(url) as resp:
                html = await resp.text()
                if any(term in html.lower() for term in ["% off", "discount", "save"]):
                    unique = f"xbox_{name}"
                    found.append((unique, name, url, "On Sale", None, None))
        except Exception as e:
            print(f"[Xbox] Error checking {name}: {e}")
    return found

async def check_playstation(session):
    found = []
    for name, url in PS_TITLES.items():
        try:
            async with session.get(url) as resp:
                html = await resp.text()
                if any(term in html.lower() for term in ["% off", "discount", "save"]):
                    unique = f"ps_{name}"
                    found.append((unique, name, url, "On Sale", None, None))
        except Exception as e:
            print(f"[PlayStation] Error checking {name}: {e}")
    return found

# -------------------------
# SALE CHECK LOOP
# -------------------------
@tasks.loop(seconds=CHECK_INTERVAL)
async def sale_check_loop():
    global seen_sales
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Checking for sales...")

    async with aiohttp.ClientSession() as session:
        results = []
        for fn in [check_steam, check_battlenet, check_xbox, check_playstation]:
            results.extend(await fn(session))

    new_sales = [s for s in results if s[0] not in seen_sales]
    if not new_sales:
        print("No new sales found.")
        return

    channel = client.get_channel(CHANNEL_ID)
    if not channel:
        print("❌ Invalid channel ID or missing permissions.")
        return

    for unique, name, url, off, was, now in new_sales:
        platform = unique.split("_")[0].capitalize()
        embed = discord.Embed(
            title=f"🔥 {name} is on Sale!",
            description=f"[View it here]({url})",
            color=discord.Color.green(),
        )
        embed.add_field(name="Platform", value=platform, inline=True)

        if was and now:
            embed.add_field(name="Price", value=f"~~{was}~~ → **{now}** ({off})", inline=False)
        else:
            embed.add_field(name="Status", value=off, inline=False)

        embed.set_footer(text=datetime.now().strftime("%Y-%m-%d %H:%M"))

        await channel.send(embed=embed)

        # Optional ping — uncomment to enable
        # await channel.send("<@&ROLE_ID>")

        seen_sales.add(unique)

    save_seen(seen_sales)
    print(f"✅ Posted {len(new_sales)} new sales.")

# -------------------------
# CLEANUP LOOP
# -------------------------
@tasks.loop(hours=12)
async def cleanup_seen():
    global seen_sales
    async with aiohttp.ClientSession() as session:
        current = set()
        for fn in [check_steam, check_battlenet, check_xbox, check_playstation]:
            res = await fn(session)
            current.update(s[0] for s in res)
        removed = seen_sales - current
        if removed:
            print(f"🧹 Cleaning {len(removed)} expired sales...")
            seen_sales -= removed
            save_seen(seen_sales)

# -------------------------
# DISCORD EVENTS
# -------------------------
@client.event
async def on_ready():
    print(f"✅ Logged in as {client.user}")
    sale_check_loop.start()
    cleanup_seen.start()

# -------------------------
# KEEP-ALIVE WEB SERVER (for Render Free)
# -------------------------
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive and running!", 200

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

threading.Thread(target=run_web).start()

# -------------------------
# RUN BOT
# -------------------------
if TOKEN and CHANNEL_ID:
    client.run(TOKEN)
else:
    print("❌ Missing DISCORD_TOKEN or DISCORD_CHANNEL_ID in secret.env")
