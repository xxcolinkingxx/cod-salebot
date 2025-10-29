import os
import asyncio
import aiohttp
import discord
from discord.ext import tasks
from dotenv import load_dotenv

# ────────────────────────────────────────────────
# Load secrets
# ────────────────────────────────────────────────
load_dotenv("secret.env")
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", 0))
print("TOKEN =", TOKEN)
print("CHANNEL_ID =", CHANNEL_ID)


# ────────────────────────────────────────────────
# Game info
# ────────────────────────────────────────────────
GAMES = {
    "Steam": {
        "Call of Duty: Black Ops III": 311210,
        "Call of Duty: Infinite Warfare": 292730,
    },
    "Xbox": {
        "Call of Duty: Black Ops III": "BP67CCPVDVZQ",
        "Call of Duty: Infinite Warfare": "BTCMZJ6X9FGL",
    },
    "PlayStation": {
        "Call of Duty: Black Ops III": "UP0002-CUSA02624_00-CODBLACKOPS30000",
        "Call of Duty: Infinite Warfare": "UP0002-CUSA02910_00-CODINFWARFARE000",
    },
    "Battle.net": {
        "Call of Duty: Black Ops 4": "call-of-duty-black-ops-4",
    }
}

PLATFORM_COLORS = {
    "Steam": 0x1B2838,
    "Xbox": 0x107C10,
    "PlayStation": 0x003087,
    "Battle.net": 0x009AE4,
}

# ────────────────────────────────────────────────
# Seen sales memory
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

seen_sales = load_seen_sales()

# ────────────────────────────────────────────────
# Embed builder
# ────────────────────────────────────────────────
def create_sale_embed(name, platform, url, was, now, image_url=None):
    embed = discord.Embed(
        title=name,
        description=f"🛒 **On Sale on {platform}**\n\n💰 **Was:** {was}\n💵 **Now:** {now}\n\n[View Deal]({url})",
        color=PLATFORM_COLORS.get(platform, 0x2F3136)
    )
    if image_url:
        embed.set_image(url=image_url)
    embed.set_footer(text=f"{platform}")
    return embed

# ────────────────────────────────────────────────
# API fetchers
# ────────────────────────────────────────────────
async def fetch_steam(session, appid):
    url = f"https://store.steampowered.com/api/appdetails?appids={appid}&cc=us&l=en"
    async with session.get(url) as r:
        data = await r.json()
        app = data[str(appid)]
        if app["success"]:
            info = app["data"]
            if info.get("price_overview") and info["price_overview"]["discount_percent"] > 0:
                return {
                    "name": info["name"],
                    "platform": "Steam",
                    "url": f"https://store.steampowered.com/app/{appid}/",
                    "was": info["price_overview"]["initial_formatted"],
                    "now": info["price_overview"]["final_formatted"],
                    "image": info.get("header_image")
                }
    return None

async def fetch_xbox(session, product_id):
    url = f"https://displaycatalog.mp.microsoft.com/v7.0/products?bigIds={product_id}&market=US&languages=en-US"
    async with session.get(url) as r:
        data = await r.json()
        try:
            product = data["Products"][0]
            price_info = product["DisplaySkuAvailabilities"][0]["Availabilities"][0]["OrderManagementData"]["Price"]
            if price_info["ListPrice"] > price_info["MSRP"]:
                return None
            if price_info["ListPrice"] > price_info["MSRP"]:  # sanity double-check
                return None
            if price_info["MSRP"] > price_info["ListPrice"]:
                return {
                    "name": product["LocalizedProperties"][0]["Title"],
                    "platform": "Xbox",
                    "url": f"https://www.xbox.com/en-us/games/store/{product_id}",
                    "was": f"${price_info['MSRP']:.2f}",
                    "now": f"${price_info['ListPrice']:.2f}",
                    "image": product["Images"][0]["Uri"]
                }
        except Exception:
            return None
    return None

async def fetch_playstation(session, product_id):
    url = f"https://store.playstation.com/store/api/chihiro/00_09_000/container/US/en/19/{product_id}"
    async with session.get(url) as r:
        data = await r.json()
        try:
            sku = data["default_sku"]
            if "display_price" in sku and "original_price" in sku and sku["display_price"] != sku["original_price"]:
                return {
                    "name": sku["name"],
                    "platform": "PlayStation",
                    "url": f"https://store.playstation.com/en-us/product/{product_id}",
                    "was": sku["original_price"],
                    "now": sku["display_price"],
                    "image": sku.get("images", [{}])[0].get("url")
                }
        except Exception:
            return None
    return None

async def fetch_battlenet(session, product_slug):
    url = f"https://us.shop.battle.net/api/product/{product_slug}"
    async with session.get(url) as r:
        data = await r.json()
        try:
            price = data.get("price", {})
            if price.get("discounted") and price["discounted"] != price["original"]:
                return {
                    "name": data["name"],
                    "platform": "Battle.net",
                    "url": f"https://us.shop.battle.net/en-us/product/{product_slug}",
                    "was": f"${price['original']}",
                    "now": f"${price['discounted']}",
                    "image": data.get("media", [{}])[0].get("url")
                }
        except Exception:
            return None
    return None

# ────────────────────────────────────────────────
# Main sale checker
# ────────────────────────────────────────────────
async def check_all_sales():
    global seen_sales
    async with aiohttp.ClientSession() as session:
        tasks_list = []

        # Steam
        for name, appid in GAMES["Steam"].items():
            tasks_list.append(fetch_steam(session, appid))
        # Xbox
        for name, pid in GAMES["Xbox"].items():
            tasks_list.append(fetch_xbox(session, pid))
        # PlayStation
        for name, pid in GAMES["PlayStation"].items():
            tasks_list.append(fetch_playstation(session, pid))
        # Battle.net
        for name, slug in GAMES["Battle.net"].items():
            tasks_list.append(fetch_battlenet(session, slug))

        results = await asyncio.gather(*tasks_list)

        channel = client.get_channel(CHANNEL_ID)
        if not channel:
            print("Channel not found.")
            return

        current_ids = set()
        for sale in filter(None, results):
            unique_id = f"{sale['platform']}_{sale['name']}"
            current_ids.add(unique_id)
            if unique_id not in seen_sales:
                embed = create_sale_embed(
                    sale["name"],
                    sale["platform"],
                    sale["url"],
                    sale["was"],
                    sale["now"],
                    sale.get("image")
                )
                await channel.send(embed=embed)
                print(f"Posted sale: {sale['name']} on {sale['platform']}")

        # remove old sales
        seen_sales = current_ids
        save_seen_sales(seen_sales)

# ────────────────────────────────────────────────
# Discord bot
# ────────────────────────────────────────────────
intents = discord.Intents.default()
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"✅ Logged in as {client.user}")
    check_sales.start()

@tasks.loop(minutes=30)
async def check_sales():
    await check_all_sales()

if TOKEN and CHANNEL_ID:
    client.run(TOKEN)
else:
    print("❌ Missing DISCORD_TOKEN or CHANNEL_ID in secret.env")

