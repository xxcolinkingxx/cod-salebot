import os
import asyncio
import aiohttp
import discord
from discord.ext import tasks
from dotenv import load_dotenv

# ────────────────────────────────
# Load secrets
# ────────────────────────────────
load_dotenv("secret.env")

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID_RAW = os.getenv("DISCORD_CHANNEL_ID")

# Print debug info to confirm env loading
print("DISCORD_TOKEN:", "Loaded" if TOKEN else "Missing")
print("DISCORD_CHANNEL_ID raw:", CHANNEL_ID_RAW)

try:
    CHANNEL_ID = int(CHANNEL_ID_RAW)
except (TypeError, ValueError):
    CHANNEL_ID = 0
print("DISCORD_CHANNEL_ID as int:", CHANNEL_ID)

# ────────────────────────────────
# Game info
# ────────────────────────────────
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

# ────────────────────────────────
# Memory for seen sales
# ────────────────────────────────
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

# ────────────────────────────────
# Embed builder
# ────────────────────────────────
def create_sale_embed(name, platform, url, was, now, image_url=None):
    embed = discord.Embed(
        title=name,
        description=f"🛒 **On Sale on {platform}**\n\n💰 **Was:** {was or '—'}\n💵 **Now:** {now or '—'}\n\n[View Deal]({url})",
        color=PLATFORM_COLORS.get(platform, 0x2F3136)
    )
    if image_url:
        embed.set_image(url=image_url)
    embed.set_footer(text=f"{platform}")
    return embed

# ────────────────────────────────
# API fetchers (Steam, Xbox, PS, Battle.net)
# ────────────────────────────────
async def fetch_steam(session, appid):
    url = f"https://store.steampowered.com/api/appdetails?appids={appid}&cc=us&l=en"
    try:
        async with session.get(url) as r:
            data = await r.json()
            app = data[str(appid)]
            if app["success"]:
                info = app["data"]
                po = info.get("price_overview")
                if po and po.get("discount_percent", 0) > 0:
                    return {
                        "name": info["name"],
                        "platform": "Steam",
                        "url": f"https://store.steampowered.com/app/{appid}/",
                        "was": po.get("initial_formatted", "—"),
                        "now": po.get("final_formatted", "—"),
                        "image": info.get("header_image")
                    }
    except Exception as e:
        print(f"[Steam {appid}] Error: {e}")
    return None

async def fetch_xbox(session, product_id):
    url = f"https://displaycatalog.mp.microsoft.com/v7.0/products?bigIds={product_id}&market=US&languages=en-US"
    try:
        async with session.get(url) as r:
            data = await r.json()
            product = data["Products"][0]
            price_info = product["DisplaySkuAvailabilities"][0]["Availabilities"][0]["OrderManagementData"]["Price"]
            if price_info["MSRP"] > price_info["ListPrice"]:
                return {
                    "name": product["LocalizedProperties"][0]["Title"],
                    "platform": "Xbox",
                    "url": f"https://www.xbox.com/en-us/games/store/{product_id}",
                    "was": f"${price_info['MSRP']:.2f}",
                    "now": f"${price_info['ListPrice']:.2f}",
                    "image": product.get("Images", [{}])[0].get("Uri")
                }
    except Exception as e:
        print(f"[Xbox {product_id}] Error: {e}")
    return None

async def fetch_playstation(session, product_id):
    url = f"https://store.playstation.com/store/api/chihiro/00_09_000/container/US/en/19/{product_id}"
    try:
        async with session.get(url) as r:
            data = await r.json()
            sku = data.get("default_sku", {})
            dp = sku.get("display_price")
            op = sku.get("original_price")
            if dp and op and dp != op:
                images = sku.get("images", [])
                img_url = images[0].get("url") if images else None
                return {
                    "name": sku.get("name") or data.get("name"),
                    "platform": "PlayStation",
                    "url": f"https://store.playstation.com/en-us/product/{product_id}",
                    "was": op,
                    "now": dp,
                    "image": img_url
                }
    except Exception as e:
        print(f"[PS {product_id}] Error: {e}")
    return None

async def fetch_battlenet(session, slug):
    url = f"https://us.shop.battle.net/api/product/{slug}"
    try:
        async with session.get(url) as r:
            data = await r.json()
            price = data.get("price", {})
            discounted = price.get("discounted")
            original = price.get("original")
            if discounted and original and discounted != original:
                image_url = data.get("media", [{}])[0].get("url")
                return {
                    "name": data.get("name"),
                    "platform": "Battle.net",
                    "url": f"https://us.shop.battle.net/en-us/product/{slug}",
                    "was": f"${original}",
                    "now": f"${discounted}",
                    "image": image_url
                }
    except Exception as e:
        print(f"[Battle.net {slug}] Error: {e}")
    return None

# ────────────────────────────────
# Main sale checker
# ────────────────────────────────
async def check_all_sales():
    global seen_sales
    async with aiohttp.ClientSession() as session:
        tasks_list = []

        for name, appid in GAMES["Steam"].items():
            tasks_list.append(fetch_steam(session, appid))
        for name, pid in GAMES["Xbox"].items():
            tasks_list.append(fetch_xbox(session, pid))
        for name, pid in GAMES["PlayStation"].items():
            tasks_list.append(fetch_playstation(session, pid))
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
                    sale["name"], sale["platform"], sale["url"], sale["was"], sale["now"], sale.get("image")
                )
                await channel.send(embed=embed)
                print(f"Posted sale: {sale['name']} on {sale['platform']}")

        seen_sales = current_ids
        save_seen_sales(seen_sales)

# ────────────────────────────────
# Discord bot setup
# ────────────────────────────────
intents = discord.Intents.default()
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"✅ Logged in as {client.user}")
    check_sales.start()

@tasks.loop(minutes=30)
async def check_sales():
    await check_all_sales()

# ────────────────────────────────
# Run bot
# ────────────────────────────────
if TOKEN and CHANNEL_ID:
    client.run(TOKEN)
else:
    print("❌ Missing DISCORD_TOKEN or DISCORD_CHANNEL_ID in secret.env")
