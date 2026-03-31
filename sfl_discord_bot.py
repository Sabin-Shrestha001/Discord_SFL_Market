"""
SFL Trading Bot — Slash Commands + Website-Style Table + Persistent History
============================================================================
pip install discord.py requests python-dotenv
"""

import discord
from discord import app_commands
from discord.ext import tasks
import requests
import os
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

TOKEN            = os.getenv("DISCORD_TOKEN")
ALERT_CHANNEL_ID = int(os.getenv("ALERT_CHANNEL_ID", "0"))
GUILD_ID         = int(os.getenv("GUILD_ID", "0"))
API_URL          = "https://sfl.world/api/v1/prices"
FETCH_INTERVAL   = 60        # seconds between price fetches
HISTORY_FILE     = "sfl_price_history.json"  # persistent storage

ITEMS = [
    "Sunflower","Potato","Rhubarb","Pumpkin","Zucchini","Carrot","Yam",
    "Cabbage","Broccoli","Soybean","Beetroot","Pepper","Cauliflower",
    "Parsnip","Eggplant","Corn","Onion","Radish","Wheat","Turnip",
    "Kale","Artichoke","Barley","Tomato","Lemon","Blueberry","Orange",
    "Apple","Banana","Grape","Rice","Olive",
    "Lunara","Duskberry","Celestine",
    "Wood","Stone","Iron","Gold","Crimstone","Obsidian",
    "Egg","Honey","Leather","Wool","Merino Wool","Feather","Milk",
    "Ruffroot","Chewed Bone","Heart Leaf","Moonfur",
    "Ribbon","Dewberry","Wild Grass","Frost Pebble",
    "Goblin Emblem","Bumpkin Emblem","Sunflorian Emblem","Nightshade Emblem",
]

GROUPS = {
    "🌾 Crops": ["Sunflower","Potato","Rhubarb","Pumpkin","Zucchini","Carrot","Yam",
                 "Cabbage","Broccoli","Soybean","Beetroot","Pepper","Cauliflower",
                 "Parsnip","Eggplant","Corn","Onion","Radish","Wheat","Turnip",
                 "Kale","Artichoke","Barley","Tomato","Lemon","Blueberry","Orange",
                 "Apple","Banana","Grape","Rice","Olive"],
    "💎 Special": ["Lunara","Duskberry","Celestine"],
    "🪵 Resources": ["Wood","Stone","Iron","Gold","Crimstone","Obsidian",
                     "Egg","Honey","Leather","Wool","Merino Wool","Feather","Milk"],
    "✨ Rare": ["Ruffroot","Chewed Bone","Heart Leaf","Moonfur",
                "Ribbon","Dewberry","Wild Grass","Frost Pebble"],
    "🏅 Emblems": ["Goblin Emblem","Bumpkin Emblem","Sunflorian Emblem","Nightshade Emblem"],
}

# ─── STATE ───────────────────────────────────────────────────────────────────

prices: dict = {}
# history stored as {item: [(iso_timestamp, price), ...]}
price_history: dict = {item: [] for item in ITEMS}
alerts: list = []
alert_counter = 0

ALERTS_FILE = "sfl_alerts.json"

def load_alerts():
    global alerts, alert_counter
    if not os.path.exists(ALERTS_FILE):
        return
    try:
        with open(ALERTS_FILE, "r") as f:
            data = json.load(f)
        alerts = data.get("alerts", [])
        alert_counter = data.get("counter", 0)
        print(f"Loaded {len(alerts)} alerts from file.")
    except Exception as e:
        print(f"Alert load error: {e}")

def save_alerts():
    try:
        with open(ALERTS_FILE, "w") as f:
            json.dump({"alerts": alerts, "counter": alert_counter}, f)
    except Exception as e:
        print(f"Alert save error: {e}")
        
bot_start_time = datetime.now()
last_fetch_time = None
api_live = False

# ─── PERSISTENT HISTORY ──────────────────────────────────────────────────────

def load_history():
    global price_history
    if not os.path.exists(HISTORY_FILE):
        return
    try:
        with open(HISTORY_FILE, "r") as f:
            raw = json.load(f)
        cutoff = datetime.now() - timedelta(days=31)
        for item in ITEMS:
            entries = raw.get(item, [])
            price_history[item] = [
                (datetime.fromisoformat(t), v)
                for t, v in entries
                if datetime.fromisoformat(t) > cutoff
            ]
        print(f"[{datetime.now().strftime('%H:%M:%S')}] History loaded from file.")
    except Exception as e:
        print(f"History load error: {e}")


def save_history():
    try:
        data = {
            item: [(t.isoformat(), v) for t, v in price_history[item]]
            for item in ITEMS
        }
        with open(HISTORY_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"History save error: {e}")


# ─── PRICE FETCHING ──────────────────────────────────────────────────────────

def fetch_prices() -> bool:
    global prices, price_history, last_fetch_time, api_live
    try:
        res = requests.get(API_URL, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "application/json",
            "Referer": "https://sfl.world/",
        }, timeout=10)
        res.raise_for_status()
        p2p = res.json()["data"]["p2p"]
        now = datetime.now()
        for item in ITEMS:
            key = next((k for k in p2p if k.lower() == item.lower()), None)
            if key:
                p = float(p2p[key])
                prices[item] = p
                price_history[item].append((now, p))
                # Keep 31 days max
                cutoff = now - timedelta(days=31)
                price_history[item] = [(t, v) for t, v in price_history[item] if t > cutoff]
        last_fetch_time = now
        api_live = True
        save_history()
        return True
    except Exception as e:
        print(f"[{datetime.now()}] API Error: {e}")
        api_live = False
        return False


# ─── HELPERS ─────────────────────────────────────────────────────────────────

def fmt(p) -> str:
    if p is None: return "  N/A  "
    return f"{p:.4f}" if p >= 1 else f"{p:.6f}"


def pct_change(item: str, hours: int) -> float | None:
    hist = price_history.get(item, [])
    if not hist: return None
    now = datetime.now()
    cutoff = now - timedelta(hours=hours)
    old_entries = [(t, v) for t, v in hist if t <= cutoff]
    if not old_entries: return None
    # Use the entry closest to the cutoff time
    old_price = old_entries[-1][1]
    cur = prices.get(item)
    if not cur or old_price == 0: return None
    return ((cur - old_price) / old_price) * 100


def fmt_pct(val) -> str:
    if val is None: return "   —   "
    sign = "+" if val >= 0 else ""
    return f"{sign}{val:.2f}%"


def pct_arrow(val) -> str:
    if val is None: return "  "
    return "▲" if val >= 0 else "▼"


def make_sparkline(item: str, hours: int, points: int = 8) -> str:
    hist = price_history.get(item, [])
    if len(hist) < 2: return "········"
    now = datetime.now()
    cutoff = now - timedelta(hours=hours)
    entries = [(t, v) for t, v in hist if t >= cutoff]
    if len(entries) < 2: return "········"
    # Sample evenly
    step = max(1, len(entries) // points)
    sampled = [v for _, v in entries[::step]][-points:]
    mn, mx = min(sampled), max(sampled)
    if mx == mn: return "▄" * len(sampled)
    bars = "▁▂▃▄▅▆▇█"
    return "".join(bars[int((v - mn) / (mx - mn) * 7)] for v in sampled)


def get_signal(item: str) -> str:
    hist = price_history.get(item, [])
    if len(hist) < 5: return "HOLD"
    values = [v for _, v in hist[-20:]]
    avg = sum(values) / len(values)
    cur = prices.get(item, avg)
    dev = ((cur - avg) / avg) * 100 if avg else 0
    if dev < -4:  return "BUY"
    elif dev > 4: return "SELL"
    return "HOLD"


def signal_emoji(s: str) -> str:
    return {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}.get(s, "⚪")


# ─── BUILD PRICE TABLE (website style) ───────────────────────────────────────

def build_price_table(items: list) -> str:
    """
    Format like the website:
    Name         Price     24h        7d         30d
    Wood       0.011259  ▼-4.44%  ▼-1.97%   ▲+6.28%
    """
    lines = []
    header = f"{'Name':<16} {'Price':>10}  {'24h':>8}  {'7d':>8}  {'30d':>8}"
    sep    = "─" * len(header)
    lines.append(header)
    lines.append(sep)

    for item in items:
        p = prices.get(item)
        if p is None: continue
        c24  = pct_change(item, 24)
        c7d  = pct_change(item, 24 * 7)
        c30d = pct_change(item, 24 * 30)

        p_str   = fmt(p)
        c24_str = f"{pct_arrow(c24)}{fmt_pct(c24)}" if c24 is not None else "    —   "
        c7_str  = f"{pct_arrow(c7d)}{fmt_pct(c7d)}" if c7d is not None else "    —   "
        c30_str = f"{pct_arrow(c30d)}{fmt_pct(c30d)}" if c30d is not None else "    —   "

        lines.append(f"{item:<16} {p_str:>10}  {c24_str:>9}  {c7_str:>9}  {c30_str:>9}")

    return "\n".join(lines)


# ─── AUTOCOMPLETE ─────────────────────────────────────────────────────────────

async def item_autocomplete(interaction: discord.Interaction, current: str):
    return [
        app_commands.Choice(name=item, value=item)
        for item in ITEMS if current.lower() in item.lower()
    ][:25]


# ─── CLIENT ──────────────────────────────────────────────────────────────────

class SFLBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            print("✅ Slash commands synced instantly to your server!")
        else:
            await self.tree.sync()
            print("✅ Slash commands synced globally.")

bot = SFLBot()

# ─── BACKGROUND TASKS ────────────────────────────────────────────────────────

@tasks.loop(seconds=FETCH_INTERVAL)
async def price_loop():
    fetch_prices()
    await check_alerts()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Updated. API={'LIVE' if api_live else 'DOWN'}")


async def check_alerts():
    channel = bot.get_channel(ALERT_CHANNEL_ID)
    for alert in alerts:
        if alert["fired"]: continue
        cur = prices.get(alert["item"])
        if cur is None: continue
        triggered = (alert["direction"] == "above" and cur >= alert["target"]) or \
                    (alert["direction"] == "below" and cur <= alert["target"])
        if not triggered: continue
        alert["fired"] = True

        c24 = pct_change(alert["item"], 24)
        spark = make_sparkline(alert["item"], 24)
        sig = get_signal(alert["item"])

        embed = discord.Embed(
            title="🔔 Price Alert Triggered!",
            color=0x00e87a if alert["direction"] == "below" else 0xff4444
        )
        embed.add_field(name="Item",    value=alert["item"],                                  inline=True)
        embed.add_field(name="Price",   value=fmt(cur),                                       inline=True)
        embed.add_field(name="Target",  value=f"{alert['direction']} {fmt(alert['target'])}", inline=True)
        embed.add_field(name="24h Chg", value=f"{pct_arrow(c24)}{fmt_pct(c24)}",             inline=True)
        embed.add_field(name="Signal",  value=f"{signal_emoji(sig)} {sig}",                  inline=True)
        embed.add_field(name="24h Chart", value=f"`{spark}`",                                 inline=False)
        embed.set_footer(text=f"SFL Bot • {datetime.now().strftime('%H:%M:%S')}")

        try:
            user = await bot.fetch_user(alert["user_id"])
            await user.send(embed=embed)
        except Exception:
            pass
        if channel:
            await channel.send(f"<@{alert['user_id']}>", embed=embed)


@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    load_history()
    load_alerts()
    fetch_prices()
    price_loop.start()
    channel = bot.get_channel(ALERT_CHANNEL_ID)
    if channel:
        await channel.send("🟢 **SFL Trading Bot is online!** Type `/` to see commands.")


# ─── SLASH COMMANDS ──────────────────────────────────────────────────────────

@bot.tree.command(name="prices", description="Show all SFL market prices (website-style table)")
@app_commands.describe(group="Which category to show")
@app_commands.choices(group=[
    app_commands.Choice(name="🌾 Crops",     value="crops"),
    app_commands.Choice(name="🪵 Resources", value="resources"),
    app_commands.Choice(name="✨ Rare",      value="rare"),
    app_commands.Choice(name="💎 Special",   value="special"),
    app_commands.Choice(name="🏅 Emblems",   value="emblems"),
    app_commands.Choice(name="All",          value="all"),
])
async def slash_prices(interaction: discord.Interaction, group: str = "all"):
    await interaction.response.defer()
    if not prices:
        await interaction.followup.send("⏳ Prices loading, try again in a moment.")
        return

    group_map = {
        "crops":     ("🌾 Crops",     GROUPS["🌾 Crops"]),
        "resources": ("🪵 Resources", GROUPS["🪵 Resources"]),
        "rare":      ("✨ Rare",      GROUPS["✨ Rare"]),
        "special":   ("💎 Special",   GROUPS["💎 Special"]),
        "emblems":   ("🏅 Emblems",   GROUPS["🏅 Emblems"]),
    }

    since = last_fetch_time.strftime("%H:%M:%S") if last_fetch_time else "—"

    if group == "all":
        for label, items in GROUPS.items():
            table = build_price_table(items)
            embed = discord.Embed(
                title=f"📊 SFL P2P Prices — {label}",
                description=f"```\n{table}\n```",
                color=0x00e87a,
                timestamp=datetime.now()
            )
            embed.set_footer(text=f"Updated {since}  |  ⚠️ 24h/7d/30d grows accurate over time")
            await interaction.followup.send(embed=embed)
    else:
        label, items = group_map[group]
        table = build_price_table(items)
        embed = discord.Embed(
            title=f"📊 SFL P2P Prices — {label}",
            description=f"```\n{table}\n```",
            color=0x00e87a,
            timestamp=datetime.now()
        )
        embed.set_footer(text=f"Updated {since}  |  ⚠️ 24h/7d/30d grows accurate over time")
        await interaction.followup.send(embed=embed)


@bot.tree.command(name="price", description="Detailed price with 24h/7d/30d chart for one item")
@app_commands.describe(item="Item name — start typing to search")
@app_commands.autocomplete(item=item_autocomplete)
async def slash_price(interaction: discord.Interaction, item: str):
    await interaction.response.defer()
    matched = next((i for i in ITEMS if i.lower() == item.lower()), None)
    if not matched:
        await interaction.followup.send(f"❌ Unknown item `{item}`.")
        return
    p = prices.get(matched)
    if p is None:
        await interaction.followup.send("⏳ No price data yet.")
        return

    c24  = pct_change(matched, 24)
    c7d  = pct_change(matched, 24 * 7)
    c30d = pct_change(matched, 24 * 30)
    sig  = get_signal(matched)
    sp24 = make_sparkline(matched, 24)
    sp7d = make_sparkline(matched, 24 * 7)

    hist = [v for _, v in price_history.get(matched, [])]
    mn   = min(hist) if hist else p
    mx   = max(hist) if hist else p

    color = 0x00e87a if (c24 or 0) >= 0 else 0xff4444
    embed = discord.Embed(title=f"🔍 {matched}", color=color, timestamp=datetime.now())
    embed.add_field(name="💰 Price",    value=f"`{fmt(p)}`",                                    inline=True)
    embed.add_field(name="📶 Signal",   value=f"{signal_emoji(sig)} **{sig}**",                 inline=True)
    embed.add_field(name="\u200b",      value="\u200b",                                         inline=True)
    embed.add_field(name="24h Change",  value=f"{pct_arrow(c24)} `{fmt_pct(c24)}`",            inline=True)
    embed.add_field(name="7d Change",   value=f"{pct_arrow(c7d)} `{fmt_pct(c7d)}`",            inline=True)
    embed.add_field(name="30d Change",  value=f"{pct_arrow(c30d)} `{fmt_pct(c30d)}`",          inline=True)
    embed.add_field(name="All-time Low (stored)",  value=f"`{fmt(mn)}`",                        inline=True)
    embed.add_field(name="All-time High (stored)", value=f"`{fmt(mx)}`",                        inline=True)
    embed.add_field(name="\u200b",      value="\u200b",                                         inline=True)
    embed.add_field(name="📈 24h Chart", value=f"`{sp24}`",                                     inline=False)
    embed.add_field(name="📈 7d Chart",  value=f"`{sp7d}`",                                     inline=False)
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="alert", description="Set a price alert — get DM when triggered")
@app_commands.describe(
    item="Item to watch — start typing to search",
    direction="Trigger when price goes above or below target",
    target="Target price e.g. 0.007"
)
@app_commands.choices(direction=[
    app_commands.Choice(name="below ↓", value="below"),
    app_commands.Choice(name="above ↑", value="above"),
])
@app_commands.autocomplete(item=item_autocomplete)
async def slash_alert(interaction: discord.Interaction, item: str, direction: str, target: float):
    global alert_counter
    matched = next((i for i in ITEMS if i.lower() == item.lower()), None)
    if not matched:
        await interaction.response.send_message(f"❌ Unknown item `{item}`.", ephemeral=True)
        return
    alert_counter += 1
    alerts.append({"id": alert_counter, "user_id": interaction.user.id,
                   "item": matched, "direction": direction, "target": target, "fired": False})
    save_alerts()
    cur = prices.get(matched)
    embed = discord.Embed(title="✅ Alert Set", color=0x00e87a)
    embed.add_field(name="Item",    value=matched,                      inline=True)
    embed.add_field(name="Trigger", value=f"{direction} {fmt(target)}", inline=True)
    embed.add_field(name="Current", value=fmt(cur) if cur else "N/A",   inline=True)
    embed.add_field(name="ID",      value=f"#{alert_counter}",          inline=True)
    embed.set_footer(text="You'll be notified via DM when triggered.")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="alerts", description="List your active price alerts")
async def slash_alerts(interaction: discord.Interaction):
    user_alerts = [a for a in alerts if a["user_id"] == interaction.user.id and not a["fired"]]
    if not user_alerts:
        await interaction.response.send_message("No active alerts. Use `/alert` to set one.", ephemeral=True)
        return
    embed = discord.Embed(title=f"🔔 Your Alerts ({len(user_alerts)})", color=0xffc940)
    for a in user_alerts:
        cur = prices.get(a["item"])
        embed.add_field(
            name=f"#{a['id']} — {a['item']}",
            value=f"{a['direction']} {fmt(a['target'])} | Now: {fmt(cur) if cur else '—'}",
            inline=False
        )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="removealert", description="Remove a price alert by ID")
@app_commands.describe(alert_id="Alert ID from /alerts")
async def slash_remove(interaction: discord.Interaction, alert_id: int):
    target = next((a for a in alerts if a["id"] == alert_id and a["user_id"] == interaction.user.id), None)
    if not target:
        await interaction.response.send_message(f"❌ Alert #{alert_id} not found.", ephemeral=True)
        return
    alerts.remove(target)
    save_alerts()
    await interaction.response.send_message(f"✅ Alert #{alert_id} removed.", ephemeral=True)


@bot.tree.command(name="opportunities", description="Show best BUY and SELL signals right now")
async def slash_opportunities(interaction: discord.Interaction):
    await interaction.response.defer()
    if not prices:
        await interaction.followup.send("⏳ No price data yet.")
        return
    results = []
    for item in ITEMS:
        p = prices.get(item)
        hist = [v for _, v in price_history.get(item, [])]
        if not p or len(hist) < 5: continue
        avg = sum(hist[-20:]) / min(len(hist), 20)
        dev = ((p - avg) / avg * 100) if avg else 0
        c24 = pct_change(item, 24)
        results.append((item, p, dev, c24))

    results.sort(key=lambda x: abs(x[2]), reverse=True)
    buy_lines, sell_lines = [], []
    for item, p, dev, c24 in results[:14]:
        c24_str = f"{pct_arrow(c24)}{fmt_pct(c24)}" if c24 is not None else "—"
        line = f"**{item}** `{fmt(p)}` · 24h: {c24_str}"
        if dev < -3:  buy_lines.append(line)
        elif dev > 3: sell_lines.append(line)

    embed = discord.Embed(title="💡 Trading Opportunities", color=0xffc940, timestamp=datetime.now())
    embed.add_field(name="🟢 BUY",  value="\n".join(buy_lines)  or "None right now", inline=False)
    embed.add_field(name="🔴 SELL", value="\n".join(sell_lines) or "None right now", inline=False)
    embed.set_footer(text="Signal based on deviation from moving average.")
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="history", description="Show price history chart for an item")
@app_commands.describe(
    item="Item name — start typing to search",
    period="Time period to show"
)
@app_commands.autocomplete(item=item_autocomplete)
@app_commands.choices(period=[
    app_commands.Choice(name="Last 2 hours", value="2"),
    app_commands.Choice(name="Last 24 hours", value="24"),
    app_commands.Choice(name="Last 7 days",   value="168"),
    app_commands.Choice(name="Last 30 days",  value="720"),
])
async def slash_history(interaction: discord.Interaction, item: str, period: str = "24"):
    matched = next((i for i in ITEMS if i.lower() == item.lower()), None)
    if not matched:
        await interaction.response.send_message(f"❌ Unknown item `{item}`.", ephemeral=True)
        return
    hours = int(period)
    hist = price_history.get(matched, [])
    cutoff = datetime.now() - timedelta(hours=hours)
    entries = [(t, v) for t, v in hist if t >= cutoff]

    if len(entries) < 2:
        await interaction.response.send_message(
            f"Not enough history for {matched} over {hours}h. Bot needs to run longer to accumulate data.")
        return

    values = [v for _, v in entries]
    mn, mx = min(values), max(values)
    avg = sum(values) / len(values)
    chg = pct_change(matched, hours)

    # Sample last 15 for display
    display = entries[-15:]
    lines = [f"`{t.strftime('%m/%d %H:%M')}` {fmt(v)}" for t, v in display]
    spark = make_sparkline(matched, hours, 20)

    period_label = {2:"2h", 24:"24h", 168:"7d", 720:"30d"}[hours]
    embed = discord.Embed(title=f"📈 {matched} — Last {period_label}", color=0x00e87a)
    embed.add_field(name="Current", value=fmt(prices.get(matched)), inline=True)
    embed.add_field(name="Change",  value=f"{pct_arrow(chg)}{fmt_pct(chg)}", inline=True)
    embed.add_field(name="Avg",     value=fmt(avg),  inline=True)
    embed.add_field(name="Low",     value=fmt(mn),   inline=True)
    embed.add_field(name="High",    value=fmt(mx),   inline=True)
    embed.add_field(name="Points",  value=str(len(entries)), inline=True)
    embed.add_field(name=f"Chart ({period_label})", value=f"`{spark}`",        inline=False)
    embed.add_field(name="Recent",  value="\n".join(lines[-8:]),               inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="botstatus", description="Show bot uptime and API status")
async def slash_status(interaction: discord.Interaction):
    uptime = datetime.now() - bot_start_time
    h, r = divmod(int(uptime.total_seconds()), 3600)
    m = r // 60
    total_points = sum(len(v) for v in price_history.values())
    embed = discord.Embed(title="🤖 SFL Bot Status",
                          color=0x00e87a if api_live else 0xff4444)
    embed.add_field(name="API",            value="✅ LIVE" if api_live else "⚠️ DOWN", inline=True)
    embed.add_field(name="Uptime",         value=f"{h}h {m}m",                        inline=True)
    embed.add_field(name="Last Fetch",     value=last_fetch_time.strftime("%H:%M:%S") if last_fetch_time else "Never", inline=True)
    embed.add_field(name="Active Alerts",  value=str(sum(1 for a in alerts if not a["fired"])), inline=True)
    embed.add_field(name="Items Tracked",  value=str(len(prices)),                    inline=True)
    embed.add_field(name="History Points", value=f"{total_points:,}",                 inline=True)
    embed.add_field(name="Refresh",        value=f"Every {FETCH_INTERVAL}s",          inline=True)
    embed.add_field(name="History File",   value=f"`{HISTORY_FILE}`",                 inline=True)
    await interaction.response.send_message(embed=embed)


# ─── RUN ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not TOKEN:
        print("❌ DISCORD_TOKEN not set in .env")
    else:
        print("Starting SFL Trading Bot...")
        bot.run(TOKEN)
