import os
import asyncio
import aiohttp
import discord
from discord.ext import tasks
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# ────────────────────────────────────────────────
# Load secrets
# ────────────────────────────────────────────────
load_dotenv("secret.env")
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", 0))

# ────────────────────────────────────────────────
# Game URLs
# ────────────────────────────────────────────────
STEAM_TITLES = {
    "Call of Duty: Black Ops III": "https://store.steampowered.com/app/311210/",
    "Call of Duty: Infinite Warfare": "https://store.steampowered.com/app/292730/",
}

PS_TITLES = {
    "Call of Duty: Black Ops III": "https://store.playstation.com/en-us/product/UP0002-CUSA02624_00-CODBLACKOPS30000",
    "Call of Duty: Infinite Warfare": "https://store.playstation.com/en-us/product/UP0002-CUSA02910_00-CODINFWARFARE000",
}

XBOX_TITLES = {
    "Call of Duty: Black Ops III": "https://www.xbox.com/en-us/games/store/call-of-duty-black-ops-iii/BP67CCPVDVZQ",
    "Call of Duty: Infinite Warfare": "https://www.xbox.com/en-us/games/store/call-of-duty-infinite-warfare/BTCMZJ6X9FGL",
}

BATTLENET_TITLES = {
    "Call of Duty: Black Ops 4": "https://us.shop.battle.net/en-us/product/call-of-duty-black-ops-4",
}

# ────────────────────────────────────────────────
# Utility helpers
# ────────────────────────────────────────────────
def load_seen_sales():
    if not os.path.exists("seen_sales.txt"):
        return set()
    with open("seen_sales.txt", "r") as f:
        return set(line.strip() for line in f.readlines())

def save_seen_sales(seen):
    with open("seen_sales.txt", "w") as f:
        for item in seen:
            f.write(item + "\n")

def create_sale_embed(name, platform, url, off, was=None, now=None, image_url=None):
    colors = {"Steam": 0x1B2838, "PlayStation": 0x003087, "Xbox": 0x107C10, "Battle.net": 0x009AE4}
    color = colors.get(platform, 0x2F3136)
    embed = discord.Embed(
        title=name,
        description=f"🛒 **On Sale on {platform}**\n\n💰 **Was:** {was or '—'}\n💵 **Now:** {now or '—'}\n\n[View Deal]({url})",
        color=color,
    )
    embed.set_footer(text=f"{platform} | {off}")
    if image_url:
        embed.set_image(url=image_url)
    return embed

def get_image_from_store(soup, platform):
    img = None
    if platform == "Steam":
        img = soup.select_one(".game_header_image_full")
    elif platform == "PlayStation":
        img = soup.select_one('img[data-qa="gameBackgroundImage#image#image"]')
    elif platform == "Xbox":
        img = soup.select_one("img.ProductDetailsHeader-module__productImage___3pklz")
    elif platform == "Battle.net":
        img = soup.select_one("img[src*='cdn']")
    return img["src"] if img and img.get("src") else None

# ────────────────────────────────────────────────
# Platform checkers
# ────────────────────────────────────────────────
async def check_steam(session):
    found = []
    for name, url in STEAM_TITLES.items():
        try:
            async with session.get(url) as r:
                html = await r.text()
                soup = BeautifulSoup(html, "html.parser")
                discount_block = soup.select_one(".discount_block")
                if discount_block:
                    was = discount_block.select_one(".discount_original_price")
                    now = discount_block.select_one(".discount_final_price")
                    off = discount_block.select_one(".discount_pct")
                    img = get_image_from_store(soup, "Steam")
                    unique = f"steam_{name}"
                    found.append((unique, name, "Steam", url,
                                  off.text.strip() if off else "Sale",
                                  was.text.strip() if was else None,
                                  now.text.strip() if now else None,
                                  img))
        except Exception as e:
            print(f"[Steam] {name}: {e}")
    return found

async def check_playstation(session):
    found = []
    for name, url in PS_TITLES.items():
        try:
            async with session.get(url, headers={"User-Agent": "Mozilla/5.0"}) as r:
                html = await r.text()
                soup = BeautifulSoup(html, "html.parser")
                now = soup.select_one('[data-qa="mfeCtaMain#offer0#finalPrice"]')
                was = soup.select_one('[data-qa="mfeCtaMain#offer0#originalPrice"]')
                if was and now:
                    img = get_image_from_store(soup, "PlayStation")
                    unique = f"ps_{name}"
                    found.append((unique, name, "PlayStation", url, "On Sale",
                                  was.text.strip(), now.text.strip(), img))
        except Exception as e:
            print(f"[PS] {name}: {e}")
    return found

async def check_xbox(session):
    found = []
    for name, url in XBOX_TITLES.items():
        try:
            async with session.get(url, headers={"User-Agent": "Mozilla/5.0"}) as r:
                html = await r.text()
                soup = BeautifulSoup(html, "html.parser")
                now = soup.select_one(".Price-module__boldText___1kR5T, span[data-price-final]")
                was = soup.select_one(".Price-module__strikethroughText___1FaDW")
                if was and now:
                    img = get_image_from_store(soup, "Xbox")
                    unique = f"xbox_{name}"
                    found.append((unique, name, "Xbox", url, "On Sale",
                                  was.text.strip(), now.text.strip(), img))
        except Exception as e:
            print(f"[Xbox] {name}: {e}")
    return found

async def check_battlenet(session):
    found = []
    for name, url in BATTLENET_TITLES.items():
        try:
            async with session.get(url, headers={"User-Agent": "Mozilla/5.0"}) as r:
                html = await r.text()
                soup = BeautifulSoup(html, "html.parser")
                now = soup.select_one(".ProductPrice-current")
                was = soup.select_one(".ProductPrice-original")
                if was and now:
                    img = get_image_from_store(soup, "Battle.net")
                    unique = f"bnet_{name}"
                    found.append((unique, name, "Battle.net", url, "On Sale",
                                  was.text.strip(), now.text.strip(), img))
        except Exception as e:
            print(f"[Battle.net] {name}: {e}")
    return found

# ────────────────────────────────────────────────
# Discord Bot setup
# ────────────────────────────────────────────────
intents = discord.Intents.default()
client = discord.Client(intents=intents)
seen_sales = load_seen_sales()

@client.event
async def on_ready():
    print(f"✅ Logged in as {client.user}")
    check_sales.start()

@tasks.loop(minutes=30)
async def check_sales():
    global seen_sales
    new_seen = set()
    async with aiohttp.ClientSession() as session:
        all_sales = []
        for checker in [check_steam, check_playstation, check_xbox, check_battlenet]:
            all_sales.extend(await checker(session))

        channel = client.get_channel(CHANNEL_ID)
        if not channel:
            print("Channel not found.")
            return

        for unique, name, platform, url, off, was, now, img in all_sales:
            new_seen.add(unique)
            if unique not in seen_sales:
                embed = create_sale_embed(name, platform, url, off, was, now, img)
                await channel.send(embed=embed)
                print(f"Posted sale: {name} on {platform}")

    # Forget old sales (so when sale ends, it can trigger again)
    seen_sales = new_seen
    save_seen_sales(seen_sales)

# ────────────────────────────────────────────────
# Run
# ────────────────────────────────────────────────
if TOKEN and CHANNEL_ID:
    client.run(TOKEN)
else:
    print("❌ Missing DISCORD_TOKEN or CHANNEL_ID in secret.env")
