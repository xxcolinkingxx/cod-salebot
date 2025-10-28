import os
import asyncio
import aiohttp
import discord
from discord.ext import tasks
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import re

# --- Load secrets ---
load_dotenv("secret.env")

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))

intents = discord.Intents.default()
client = discord.Client(intents=intents)

# --- Store titles ---
STEAM_TITLES = {
    "Black Ops 1": "https://store.steampowered.com/app/42700/Call_of_Duty_Black_Ops/",
    "Black Ops 2": "https://store.steampowered.com/app/202970/Call_of_Duty_Black_Ops_II/",
    "Black Ops 3": "https://store.steampowered.com/app/311210/Call_of_Duty_Black_Ops_III/",
    "Black Ops Cold War": "https://store.steampowered.com/app/1940340/Call_of_Duty_Black_Ops_Cold_War/",
}

BATTLE_TITLES = {
    "Black Ops 4": "https://us.shop.battle.net/en-us/product/call-of-duty-black-ops-4",
}

XBOX_TITLES = {
    "Black Ops 1": "https://www.xbox.com/en-US/games/store/call-of-duty-black-ops/C1S3LPG1GR8V",
    "Black Ops 2": "https://www.xbox.com/en-US/games/store/call-of-duty-black-ops-ii/BSZB2X7F1VHQ",
    "Black Ops 3": "https://www.xbox.com/en-US/games/store/call-of-duty-black-ops-iii/BXH2MFJ43QK7",
    "Black Ops Cold War": "https://www.xbox.com/en-US/games/store/call-of-duty-black-ops-cold-war/9N4LGGJ7C2TL",
}

PS_TITLES = {
    "Black Ops 3": "https://store.playstation.com/en-us/product/UP0002-CUSA02290_00-CODBO3FULLGAME00",
    "Black Ops Cold War": "https://store.playstation.com/en-us/product/UP0002-CUSA15010_00-CODBOCWSTANDARD0",
    "Black Ops 4": "https://store.playstation.com/en-us/product/UP0002-CUSA11100_00-CODBO4PREORDER000",
}

# --- Load / Save sales memory ---
def load_seen_sales():
    try:
        with open("seen_sales.txt", "r") as f:
            return set(f.read().splitlines())
    except FileNotFoundError:
        return set()

def save_seen_sales(seen):
    with open("seen_sales.txt", "w") as f:
        f.write("\n".join(sorted(seen)))

# --- Price normalization ---
def normalize_price(price: str) -> str:
    price = price.strip()
    # Detect currency symbol
    if "€" in price:
        currency = "EUR"
    elif "£" in price:
        currency = "GBP"
    elif "$" in price:
        currency = "USD"
    else:
        currency = "USD"  # fallback
    # Extract numeric value
    num = re.findall(r"[\d.,]+", price)
    value = num[0] if num else price
    return f"${value} {currency}"

# --- Scraper functions ---

async def check_steam(session):
    found = []
    for name, url in STEAM_TITLES.items():
        try:
            async with session.get(url) as resp:
                html = await resp.text()
                soup = BeautifulSoup(html, "html.parser")
                discount = soup.select_one(".discount_pct")
                price_now = soup.select_one(".discount_final_price")
                price_was = soup.select_one(".discount_original_price")

                if discount and price_now and price_was:
                    unique = f"steam_{name}"
                    found.append((unique, name, url, discount.text.strip(),
                                  normalize_price(price_was.text), normalize_price(price_now.text)))
        except Exception as e:
            print(f"[Steam] Error checking {name}: {e}")
    return found


async def check_battle_net(session):
    found = []
    for name, url in BATTLE_TITLES.items():
        try:
            async with session.get(url, headers={"User-Agent": "Mozilla/5.0"}) as resp:
                html = await resp.text()
                soup = BeautifulSoup(html, "html.parser")

                current_price = soup.select_one('span[data-testid="product-price"]')
                original_price = soup.select_one('span[data-testid="product-strikethrough-price"]')

                if original_price and current_price:
                    unique = f"bnet_{name}"
                    found.append((unique, name, url, "On Sale",
                                  normalize_price(original_price.text), normalize_price(current_price.text)))
        except Exception as e:
            print(f"[Battle.net] Error checking {name}: {e}")
    return found


async def check_xbox(session):
    found = []
    for name, url in XBOX_TITLES.items():
        try:
            async with session.get(url, headers={"User-Agent": "Mozilla/5.0"}) as resp:
                html = await resp.text()
                soup = BeautifulSoup(html, "html.parser")

                price_now = soup.select_one('[itemprop="price"]')
                price_was = soup.select_one('.Price-text--strikethrough')

                if price_now and price_was:
                    unique = f"xbox_{name}"
                    found.append((unique, name, url, "On Sale",
                                  normalize_price(price_was.text), normalize_price(price_now.text)))
        except Exception as e:
            print(f"[Xbox] Error checking {name}: {e}")
    return found


async def check_playstation(session):
    found = []
    for name, url in PS_TITLES.items():
        try:
            async with session.get(url, headers={"User-Agent": "Mozilla/5.0"}) as resp:
                html = await resp.text()
                soup = BeautifulSoup(html, "html.parser")

                current_price = soup.select_one('[data-qa="mfeCtaMain#offer0#finalPrice"]')
                original_price = soup.select_one('[data-qa="mfeCtaMain#offer0#originalPrice"]')

                if original_price and current_price:
                    unique = f"ps_{name}"
                    found.append((unique, name, url, "On Sale",
                                  normalize_price(original_price.text), normalize_price(current_price.text)))
        except Exception as e:
            print(f"[PlayStation] Error checking {name}: {e}")
    return found

# --- Combine all stores ---
async def check_all_stores():
    async with aiohttp.ClientSession() as session:
        results = await asyncio.gather(
            check_steam(session),
            check_battle_net(session),
            check_xbox(session),
            check_playstation(session),
        )
        return [sale for store_sales in results for sale in store_sales]


# --- Discord Bot Behavior ---
@client.event
async def on_ready():
    print(f"✅ Logged in as {client.user}")
    check_sales.start()


@tasks.loop(minutes=60)
async def check_sales():
    print("🔎 Checking all stores...")
    channel = client.get_channel(CHANNEL_ID)
    seen = load_seen_sales()
    new_seen = set(seen)

    found_sales = await check_all_stores()

    for sale_id, name, url, off, was, now in found_sales:
        if sale_id not in seen:
            embed = discord.Embed(
                title=f"{name} is on sale!",
                url=url,
                description=f"**{off}** — Was **{was}**, now **{now}**",
                color=0x00ff99
            )
            embed.set_footer(text="Call of Duty Sale Tracker")
            await channel.send(embed=embed)
            new_seen.add(sale_id)

    # Remove old sales if no longer active
    current_ids = {s[0] for s in found_sales}
    for old_sale in list(seen):
        if old_sale not in current_ids:
            new_seen.discard(old_sale)

    save_seen_sales(new_seen)
    print("✅ Done checking.")


client.run(TOKEN)
