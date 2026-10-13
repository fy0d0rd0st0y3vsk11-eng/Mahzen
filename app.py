import asyncio
import html
import json
import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import uvicorn

# ===================== AYARLAR =====================
TOKEN = os.getenv("DISCORD_TOKEN", "BOT_TOKENINI_BURAYA_YAZ")
OWNER_ID = int(os.getenv("OWNER_ID", "896838638040666183"))
GUILD_ID = int(os.getenv("GUILD_ID", "1559340955973455926"))
DB_FILE = os.getenv("MAHZEN_DB", "mahzen.db")
TZ = ZoneInfo("Europe/Istanbul")

GAME_ROLES = [
    "Among Us", "Minecraft", "Goose Goose Duck", "Korku / Co-op",
    "FPS", "Party oyunları", "Strateji", "Bağımsız oyunlar"
]

# ===================== VERİTABANI =====================
def db():
    con = sqlite3.connect(DB_FILE)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            starts_at TEXT NOT NULL,
            description TEXT DEFAULT '',
            channel_id INTEGER NOT NULL,
            message_id INTEGER DEFAULT 0,
            status TEXT DEFAULT 'planned'
        );
        CREATE TABLE IF NOT EXISTS attendance (
            event_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            PRIMARY KEY (event_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS polls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,
            options TEXT NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER DEFAULT 0,
            status TEXT DEFAULT 'open'
        );
        CREATE TABLE IF NOT EXISTS votes (
            poll_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            choice INTEGER NOT NULL,
            PRIMARY KEY (poll_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS member_roles (
            user_id INTEGER NOT NULL,
            role_name TEXT NOT NULL,
            PRIMARY KEY (user_id, role_name)
        );
        """)


def now():
    return datetime.now(TZ)


def parse_time(value):
    return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M").replace(tzinfo=TZ)


def format_time(value):
    return datetime.fromisoformat(value).astimezone(TZ).strftime("%d.%m.%Y • %H:%M")


def get_event(event_id):
    with db() as con:
        return con.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()


def get_poll(poll_id):
    with db() as con:
        return con.execute("SELECT * FROM polls WHERE id=?", (poll_id,)).fetchone()


def is_owner(user):
    return OWNER_ID != 0 and user.id == OWNER_ID


# ===================== DISCORD BOT =====================
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True


class FedyaBot(commands.Bot):
    async def setup_hook(self):
        init_db()
        print("🗄️ Veritabanı hazır.")

        # Kalıcı etkinlik ve anket butonlarını yeniden yükle.
        with db() as con:
            event_rows = con.execute(
                "SELECT id FROM events WHERE status='planned'"
            ).fetchall()
            poll_rows = con.execute(
                "SELECT id, options FROM polls WHERE status='open'"
            ).fetchall()

        for row in event_rows:
            self.add_view(EventView(row["id"]))
        for row in poll_rows:
            self.add_view(PollView(row["id"], row["options"].split("||")))

        try:
            if GUILD_ID:
                guild = discord.Object(id=GUILD_ID)
                self.tree.copy_global_to(guild=guild)
                synced_commands = await self.tree.sync(guild=guild)
            else:
                synced_commands = await self.tree.sync()
            print(f"✅ {len(synced_commands)} slash komutu kaydedildi.")
            for command in synced_commands:
                print(f"   /{command.name}")
        except Exception as exc:
            print(f"❌ SLASH SENKRONİZASYON HATASI: {type(exc).__name__}: {exc}")


bot = FedyaBot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"🍄 Fedya çevrimiçi: {bot.user}")
    print(f"🆔 Bot ID: {bot.user.id}")
    print(f"🏰 Sunucu ID: {GUILD_ID}")


# ===================== ETKİNLİKLER =====================
def event_embed(event):
    embed = discord.Embed(
        title=f"🍄 {event['title']}",
        description=event["description"] or "Mahzen etkinliği!",
        color=discord.Color.green()
    )
    embed.add_field(name="🕒 Başlangıç", value=format_time(event["starts_at"]), inline=False)
    with db() as con:
        people = con.execute(
            "SELECT user_id FROM attendance WHERE event_id=? AND status='yes'",
            (event["id"],)
        ).fetchall()
    mentions = [f"<@{row['user_id']}>" for row in people]
    embed.add_field(
        name=f"🎮 Katılacaklar ({len(mentions)})",
        value="\n".join(mentions) if mentions else "Henüz katılan yok.",
        inline=False
    )
    remaining = datetime.fromisoformat(event["starts_at"]) - now()
    minutes_total = max(0, int(remaining.total_seconds() // 60))
    days, minutes_total = divmod(minutes_total, 1440)
    hours, minutes = divmod(minutes_total, 60)
    embed.add_field(name="⏳ Geri sayım", value=f"{days} gün, {hours} saat, {minutes} dakika", inline=False)
    embed.set_footer(text="Mahzen • Fedya 🍄")
    return embed


async def refresh_event_message(event_id):
    event = get_event(event_id)
    if not event or not event["message_id"]:
        return
    channel = bot.get_channel(event["channel_id"])
    if channel is None:
        return
    try:
        message = await channel.fetch_message(event["message_id"])
        await message.edit(embed=event_embed(event), view=EventView(event_id))
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        pass


class EventView(discord.ui.View):
    def __init__(self, event_id):
        super().__init__(timeout=None)
        self.event_id = event_id
        yes = discord.ui.Button(
            label="Katılıyorum", emoji="🎮", style=discord.ButtonStyle.success,
            custom_id=f"fedya_event_yes_{event_id}"
        )
        no = discord.ui.Button(
            label="Katılamıyorum", emoji="✖️", style=discord.ButtonStyle.secondary,
            custom_id=f"fedya_event_no_{event_id}"
        )
        yes.callback = self.join
        no.callback = self.decline
        self.add_item(yes)
        self.add_item(no)

    async def set_status(self, interaction, status):
        event = get_event(self.event_id)
        if not event or event["status"] != "planned":
            await interaction.response.send_message("Bu etkinlik artık aktif değil.", ephemeral=True)
            return
        with db() as con:
            con.execute(
                """INSERT INTO attendance(event_id,user_id,status) VALUES(?,?,?)
                   ON CONFLICT(event_id,user_id) DO UPDATE SET status=excluded.status""",
                (self.event_id, interaction.user.id, status)
            )
        await interaction.response.send_message("Katılım tercihin kaydedildi! 🍄", ephemeral=True)
        await refresh_event_message(self.event_id)

    async def join(self, interaction):
        await self.set_status(interaction, "yes")

    async def decline(self, interaction):
        await self.set_status(interaction, "no")


# ===================== ANKETLER =====================
class PollView(discord.ui.View):
    def __init__(self, poll_id, options):
        super().__init__(timeout=None)
        self.poll_id = poll_id
        for index, option in enumerate(options[:5]):
            button = discord.ui.Button(
                label=option[:80], style=discord.ButtonStyle.primary,
                custom_id=f"fedya_poll_{poll_id}_{index}"
            )
            button.callback = self.make_callback(index)
            self.add_item(button)

    def make_callback(self, choice):
        async def callback(interaction):
            poll = get_poll(self.poll_id)
            if not poll or poll["status"] != "open":
                await interaction.response.send_message("Bu anket kapatılmış.", ephemeral=True)
                return
            with db() as con:
                con.execute(
                    """INSERT INTO votes(poll_id,user_id,choice) VALUES(?,?,?)
                       ON CONFLICT(poll_id,user_id) DO UPDATE SET choice=excluded.choice""",
                    (self.poll_id, interaction.user.id, choice)
                )
            await interaction.response.send_message("Oyun kaydedildi! 💚", ephemeral=True)
        return callback


# ===================== NORMAL MESAJLAR + FEDYA AI =====================
AI_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
AI_MODEL = os.getenv("AI_MODEL", "openrouter/free").strip()
AI_SITE_URL = os.getenv("AI_SITE_URL", "https://mahzen-fedya.onrender.com").strip()
AI_SITE_NAME = os.getenv("AI_SITE_NAME", "Mahzen Fedya").strip()
AI_SYSTEM_PROMPT = """Sen Fedya'sın: Mahzen Discord sunucusunun huysuz, zeki, esprili ve adalet takıntılı yardımcısısın. Türkçe konuş, doğal ve gerektiğinde hafif argo kullan. Kişiliğin sinirli ama aklı başında; herkese otomatik olarak hak verme. Bir tartışmada tarafları dinle, olayları ayır, kanıt ve bağlam iste, çelişkileri belirt. Kullanıcı haksızsa açıkça ama aşağılamadan söyle; haklıysa neden haklı olduğunu açıkla. Bilgi eksikse kesin hüküm verme. İnsanları hedef gösterme, tehdit etme veya tacize yönlendirme. Kişisel verileri ifşa etme. Cevaplarını genelde kısa, canlı ve komik tut. Kendini gerçek bir insan gibi tanıtma; Mahzen'in Fedya AI'ı olduğunu bil."""

async def ask_fedya_ai(user_text: str, display_name: str) -> str:
    if not AI_API_KEY:
        return (f"{display_name}, beynimin API anahtarı henüz takılmamış. 🍄 "
                "Sunucu sahibi Render'da OPENROUTER_API_KEY ayarlayınca gerçek AI olarak konuşacağım.")
    import aiohttp
    headers = {
        "Authorization": f"Bearer {AI_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": AI_SITE_URL,
        "X-Title": AI_SITE_NAME,
    }
    payload = {
        "model": AI_MODEL,
        "messages": [
            {"role": "system", "content": AI_SYSTEM_PROMPT},
            {"role": "user", "content": f"Discord kullanıcısı {display_name} diyor ki: {user_text[:3500]}"},
        ],
        "temperature": 0.8,
        "max_tokens": 500,
    }
    timeout = aiohttp.ClientTimeout(total=25)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload) as resp:
                body = await resp.text()
                if resp.status >= 400:
                    print(f"⚠️ AI API hatası {resp.status}: {body[:500]}")
                    return "Beynimin bağlantısı tekledi. 🍄 Birazdan tekrar dene; API anahtarı ve model ayarlarını da kontrol etmek lazım."
                data = json.loads(body)
                answer = data["choices"][0]["message"]["content"].strip()
                return answer[:1900] if answer else "Kafam bir an boşaldı. Bir daha söylesene. 🍄"
    except Exception as exc:
        print(f"⚠️ Fedya AI hatası: {type(exc).__name__}: {exc}")
        return "AI tarafında bir bağlantı hatası oldu. 🍄 Konsol logunu kontrol etmek lazım."

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    content = message.content.strip()
    lower = content.lower()
    mentioned = bot.user is not None and bot.user in message.mentions
    calls_fedya = lower == "fedya" or lower.startswith(("fedya ", "fedya,", "fedya:", "fedya!", "fedya?"))
    if mentioned or calls_fedya:
        cleaned = content
        if bot.user is not None:
            cleaned = cleaned.replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "").strip()
        cleaned = cleaned.removeprefix("fedya").lstrip(" ,:!?").strip()
        if not cleaned:
            cleaned = "Mahzen'de ne oluyor?"
        async with message.channel.typing():
            reply = await ask_fedya_ai(cleaned, message.author.display_name)
        await message.reply(reply, mention_author=False, allowed_mentions=discord.AllowedMentions.none())
    await bot.process_commands(message)


# ===================== SLASH KOMUTLARI =====================
@bot.tree.command(name="yardim", description="Fedya komutlarını göster.")
async def yardim(interaction: discord.Interaction):
    text = (
        "`/yardim` — Komut listesi\n"
        "`/saat` — Sıradaki etkinlik\n"
        "`/etkinlikler` — Etkinlik listesi\n"
        "`/duyuru` — Etkinlik oluştur (sahip)\n"
        "`/iptal` — Etkinlik iptal et (sahip)\n"
        "`/anket` — Anket oluştur (sahip)\n"
        "`/anket_sonucu` — Anket sonuçları\n"
        "`/roller` — Oyun rolleri\n"
        "`/profil` — Profil ve puan\n"
        "`/siralama` — Puan sıralaması\n"
        "`/yoklama` — Etkinlik katılımını puanla (sahip)"
    )
    await interaction.response.send_message(text, ephemeral=True)


@bot.tree.command(name="saat", description="Sıradaki etkinliğin saatini göster.")
async def saat(interaction: discord.Interaction):
    with db() as con:
        event = con.execute(
            """SELECT * FROM events WHERE status='planned' AND starts_at>=?
               ORDER BY starts_at LIMIT 1""",
            (now().isoformat(),)
        ).fetchone()
    if not event:
        await interaction.response.send_message("Şimdilik planlanmış etkinlik yok. 🍄")
        return
    await interaction.response.send_message(
        f"🎮 **{event['title']}**\n🕒 {format_time(event['starts_at'])}\n📝 {event['description'] or 'Açıklama yok.'}"
    )


@bot.tree.command(name="etkinlikler", description="Yaklaşan etkinlikleri göster.")
async def etkinlikler(interaction: discord.Interaction):
    with db() as con:
        events = con.execute(
            "SELECT * FROM events WHERE status='planned' ORDER BY starts_at LIMIT 10"
        ).fetchall()
    if not events:
        await interaction.response.send_message("Planlanmış etkinlik yok.")
        return
    description = "\n\n".join(
        f"**#{event['id']} • {event['title']}**\n🕒 {format_time(event['starts_at'])}"
        for event in events
    )
    await interaction.response.send_message(
        embed=discord.Embed(title="📅 Mahzen etkinlikleri", description=description, color=discord.Color.green())
    )


@bot.tree.command(name="duyuru", description="Yeni etkinlik duyur.")
@app_commands.describe(oyun="Etkinlik adı", tarih_saat="YYYY-AA-GG SS:DD", aciklama="Etkinlik açıklaması")
async def duyuru(interaction: discord.Interaction, oyun: str, tarih_saat: str, aciklama: str = ""):
    if not is_owner(interaction.user):
        await interaction.response.send_message("Bu komut yalnızca bot sahibine açık.", ephemeral=True)
        return
    try:
        start = parse_time(tarih_saat)
        if start <= now():
            raise ValueError
    except ValueError:
        await interaction.response.send_message("Gelecek tarih gir. Örnek: `2026-10-20 20:30`", ephemeral=True)
        return
    if interaction.channel is None:
        await interaction.response.send_message("Kanal bulunamadı.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    with db() as con:
        cur = con.execute(
            "INSERT INTO events(title,starts_at,description,channel_id) VALUES(?,?,?,?)",
            (oyun, start.isoformat(), aciklama, interaction.channel_id)
        )
        event_id = cur.lastrowid
    try:
        message = await interaction.channel.send(
            "🍄 **Yeni Mahzen etkinliği!**", embed=event_embed(get_event(event_id)), view=EventView(event_id)
        )
        with db() as con:
            con.execute("UPDATE events SET message_id=? WHERE id=?", (message.id, event_id))
    except discord.HTTPException as exc:
        with db() as con:
            con.execute("UPDATE events SET status='failed' WHERE id=?", (event_id,))
        await interaction.followup.send(f"Duyuru gönderilemedi: {exc}", ephemeral=True)
        return
    await interaction.followup.send(f"✅ Etkinlik oluşturuldu! No: `{event_id}`", ephemeral=True)


@bot.tree.command(name="iptal", description="Bir etkinliği iptal et.")
@app_commands.describe(etkinlik_no="İptal edilecek etkinliğin numarası")
async def iptal(interaction: discord.Interaction, etkinlik_no: int):
    if not is_owner(interaction.user):
        await interaction.response.send_message("Bu komut yalnızca bot sahibine açık.", ephemeral=True)
        return
    event = get_event(etkinlik_no)
    if not event or event["status"] != "planned":
        await interaction.response.send_message("Aktif etkinlik bulunamadı.", ephemeral=True)
        return
    with db() as con:
        con.execute("UPDATE events SET status='cancelled' WHERE id=?", (etkinlik_no,))
    channel = bot.get_channel(event["channel_id"])
    if channel and event["message_id"]:
        try:
            message = await channel.fetch_message(event["message_id"])
            await message.edit(content="❌ **Bu etkinlik iptal edildi.**", embed=None, view=None)
        except discord.HTTPException:
            pass
    await interaction.response.send_message(f"Etkinlik #{etkinlik_no} iptal edildi.", ephemeral=True)


@bot.tree.command(name="anket", description="Mahzen için anket oluştur.")
@app_commands.describe(soru="Anket sorusu", secenekler="Seçenekleri | işaretiyle ayır")
async def anket(interaction: discord.Interaction, soru: str, secenekler: str):
    if not is_owner(interaction.user):
        await interaction.response.send_message("Bu komut yalnızca bot sahibine açık.", ephemeral=True)
        return
    options = [item.strip() for item in secenekler.split("|") if item.strip()]
    if not 2 <= len(options) <= 5:
        await interaction.response.send_message("2-5 seçenek gir. Örnek: `Among Us | Minecraft | GGD`", ephemeral=True)
        return
    if interaction.channel is None:
        await interaction.response.send_message("Kanal bulunamadı.", ephemeral=True)
        return
    with db() as con:
        cur = con.execute(
            "INSERT INTO polls(question,options,channel_id) VALUES(?,?,?)",
            (soru, "||".join(options), interaction.channel_id)
        )
        poll_id = cur.lastrowid
    embed = discord.Embed(
        title=f"📊 {soru}",
        description="\n".join(f"**{i + 1}.** {option}" for i, option in enumerate(options)),
        color=discord.Color.green()
    )
    message = await interaction.channel.send(embed=embed, view=PollView(poll_id, options))
    with db() as con:
        con.execute("UPDATE polls SET message_id=? WHERE id=?", (message.id, poll_id))
    await interaction.response.send_message(f"✅ Anket oluşturuldu. No: `{poll_id}`", ephemeral=True)


@bot.tree.command(name="anket_sonucu", description="Anket sonuçlarını göster.")
@app_commands.describe(anket_no="Anket numarası")
async def anket_sonucu(interaction: discord.Interaction, anket_no: int):
    poll = get_poll(anket_no)
    if not poll:
        await interaction.response.send_message("Bu numarayla anket bulunamadı.", ephemeral=True)
        return
    options = poll["options"].split("||")
    with db() as con:
        rows = con.execute(
            "SELECT choice, COUNT(*) AS total FROM votes WHERE poll_id=? GROUP BY choice",
            (anket_no,)
        ).fetchall()
    counts = {row["choice"]: row["total"] for row in rows}
    description = "\n".join(f"**{option}** — {counts.get(i, 0)} oy" for i, option in enumerate(options))
    total = sum(counts.values())
    await interaction.response.send_message(f"📊 **{poll['question']}**\n{description}\n\nToplam oy: **{total}**")


@bot.tree.command(name="roller", description="Oynamak istediğin oyun rollerini seç.")
async def roller(interaction: discord.Interaction):
    view = discord.ui.View(timeout=300)
    for role_name in GAME_ROLES:
        button = discord.ui.Button(label=role_name, style=discord.ButtonStyle.secondary)

        async def callback(i, name=role_name):
            if not i.guild:
                await i.response.send_message("Bu komutu sunucuda kullan.", ephemeral=True)
                return
            role = discord.utils.get(i.guild.roles, name=name)
            if role is None:
                await i.response.send_message(f"Önce **{name}** rolünü oluştur.", ephemeral=True)
                return
            try:
                if role in i.user.roles:
                    await i.user.remove_roles(role)
                    answer = f"➖ **{name}** rolü kaldırıldı."
                    with db() as con:
                        con.execute("DELETE FROM member_roles WHERE user_id=? AND role_name=?", (i.user.id, name))
                else:
                    await i.user.add_roles(role)
                    answer = f"✅ **{name}** rolü verildi!"
                    with db() as con:
                        con.execute("INSERT OR IGNORE INTO member_roles VALUES(?,?)", (i.user.id, name))
                await i.response.send_message(answer, ephemeral=True)
            except discord.Forbidden:
                await i.response.send_message(
                    "Fedya'nın rolünü oyun rollerinin üstüne taşı ve botta Manage Roles iznini aç.",
                    ephemeral=True
                )
        button.callback = callback
        view.add_item(button)
    await interaction.response.send_message("🎮 Oyun rollerini seç. Tekrar basarsan rol kaldırılır.", view=view, ephemeral=True)


@bot.tree.command(name="yoklama", description="Etkinlik katılımını puanla (bot sahibi).")
@app_commands.describe(etkinlik_no="Etkinlik numarası", uye="Katılımı onaylanacak üye")
async def yoklama(interaction: discord.Interaction, etkinlik_no: int, uye: discord.Member):
    if not is_owner(interaction.user):
        await interaction.response.send_message("Bu komut yalnızca bot sahibine açık.", ephemeral=True)
        return
    event = get_event(etkinlik_no)
    if not event:
        await interaction.response.send_message("Etkinlik bulunamadı.", ephemeral=True)
        return
    with db() as con:
        con.execute(
            """INSERT INTO attendance(event_id,user_id,status) VALUES(?,?,?)
               ON CONFLICT(event_id,user_id) DO UPDATE SET status='attended'""",
            (etkinlik_no, uye.id, "attended")
        )
    await interaction.response.send_message(
        f"✅ {uye.mention} için etkinlik #{etkinlik_no} katılımı kaydedildi.", ephemeral=True
    )


@bot.tree.command(name="profil", description="Mahzen profilini göster.")
async def profil(interaction: discord.Interaction):
    with db() as con:
        count = con.execute(
            "SELECT COUNT(*) AS total FROM attendance WHERE user_id=? AND status='attended'",
            (interaction.user.id,)
        ).fetchone()["total"]
        roles = con.execute(
            "SELECT role_name FROM member_roles WHERE user_id=?",
            (interaction.user.id,)
        ).fetchall()
    achievements = []
    if count >= 1:
        achievements.append("İlk Etkinlik")
    if count >= 5:
        achievements.append("Mahzen Müdavimi")
    if count >= 10:
        achievements.append("Mahzen Efsanesi")
    embed = discord.Embed(title=f"👤 {interaction.user.display_name}", color=discord.Color.green())
    embed.add_field(name="🏆 Puan", value=str(count * 10), inline=True)
    embed.add_field(name="🎮 Katılım", value=str(count), inline=True)
    embed.add_field(name="🎖️ Başarımlar", value=", ".join(achievements) or "Henüz yok", inline=False)
    embed.add_field(name="🎯 Oyun rolleri", value=", ".join(row["role_name"] for row in roles) or "Henüz yok", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="siralama", description="Mahzen katılım puanı sıralaması.")
async def siralama(interaction: discord.Interaction):
    with db() as con:
        rows = con.execute(
            """SELECT user_id, COUNT(*) AS total FROM attendance
               WHERE status='attended' GROUP BY user_id
               ORDER BY total DESC LIMIT 10"""
        ).fetchall()
    if not rows:
        await interaction.response.send_message("Henüz katılım puanı kazanan yok.")
        return
    lines = []
    for index, row in enumerate(rows, start=1):
        lines.append(f"**{index}.** <@{row['user_id']}> — {row['total'] * 10} puan")
    await interaction.response.send_message("🏆 **Mahzen sıralaması**\n" + "\n".join(lines))


# ===================== WEB PANELİ =====================
web = FastAPI(title="Mahzen • Fedya Dashboard")


def dashboard_data():
    with db() as con:
        events = con.execute("SELECT * FROM events ORDER BY starts_at ASC LIMIT 50").fetchall()
        poll_rows = con.execute("SELECT * FROM polls ORDER BY id DESC LIMIT 12").fetchall()
        event_items = []
        for event in events:
            going = con.execute(
                "SELECT COUNT(*) AS n FROM attendance WHERE event_id=? AND status='yes'",
                (event["id"],)
            ).fetchone()["n"]
            event_items.append({
                "id": event["id"], "title": event["title"],
                "starts_at": event["starts_at"], "display_time": format_time(event["starts_at"]),
                "description": event["description"] or "", "status": event["status"], "going": going,
            })
        poll_items = []
        for poll in poll_rows:
            options = poll["options"].split("||")
            counts_rows = con.execute(
                "SELECT choice, COUNT(*) AS n FROM votes WHERE poll_id=? GROUP BY choice", (poll["id"],)
            ).fetchall()
            counts = {row["choice"]: row["n"] for row in counts_rows}
            poll_items.append({
                "id": poll["id"], "question": poll["question"], "status": poll["status"],
                "total": sum(counts.values()),
                "options": [{"label": option, "votes": counts.get(i, 0)} for i, option in enumerate(options)],
            })
    upcoming = sum(1 for e in event_items if e["status"] == "planned" and datetime.fromisoformat(e["starts_at"]) >= now())
    return {
        "updated_at": now().strftime("%d.%m.%Y %H:%M:%S"),
        "stats": {
            "upcoming_events": upcoming,
            "planned_events": sum(1 for e in event_items if e["status"] == "planned"),
            "total_going": sum(e["going"] for e in event_items if e["status"] == "planned"),
            "open_polls": sum(1 for p in poll_items if p["status"] == "open"),
        }, "events": event_items, "polls": poll_items,
    }


@web.get("/", response_class=HTMLResponse)
async def panel():
    return HTMLResponse(r"""<!doctype html>
<html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#11130f"><title>Mahzen • Fedya</title>
<style>
:root{color-scheme:dark;--bg:#10120f;--panel:#191d17;--line:#30392b;--text:#f1f5e9;--muted:#a5b09a;--green:#b8ef74;--green2:#7bc64b;--orange:#f0b66b;--red:#f18b82}*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at 15% -10%,#293b21 0,transparent 36%),radial-gradient(ellipse at 100% 5%,#30271b 0,transparent 25%),var(--bg);color:var(--text);font:15px/1.5 Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.wrap{max-width:1180px;margin:auto;padding:28px 20px 48px}.top{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:30px}.brand{display:flex;align-items:center;gap:13px}.logo{width:50px;height:50px;display:grid;place-items:center;border:1px solid #526c3e;border-radius:16px;background:linear-gradient(145deg,#2e4525,#1b2516);font-size:27px;box-shadow:0 8px 35px #0004}.eyebrow{color:var(--green);font-size:11px;letter-spacing:.18em;text-transform:uppercase;font-weight:800}.brand h1{margin:2px 0 0;font-size:23px;letter-spacing:-.04em}.live{display:flex;align-items:center;gap:8px;padding:9px 12px;border:1px solid var(--line);border-radius:999px;background:#171b15;color:var(--muted);font-size:12px}.dot{width:7px;height:7px;background:var(--green);border-radius:50%;box-shadow:0 0 12px #b8ef7488}.hero{position:relative;overflow:hidden;padding:30px;border:1px solid #3b4c30;border-radius:25px;background:linear-gradient(115deg,#24331d,#192018 65%,#211f17);margin-bottom:18px}.hero:after{content:"🍄";position:absolute;right:38px;top:12px;font-size:115px;opacity:.10;transform:rotate(14deg)}.hero h2{font-size:clamp(28px,5vw,43px);line-height:1.08;letter-spacing:-.055em;margin:8px 0 12px;max-width:650px}.hero p{margin:0;color:#c1cbb8;max-width:610px}.hero .kicker{color:var(--green);font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:.13em}.stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:13px;margin:18px 0 28px}.stat,.card{border:1px solid var(--line);background:linear-gradient(150deg,#1b2019,#161914);border-radius:18px}.stat{padding:18px}.stat .label{font-size:12px;color:var(--muted)}.stat .num{font-size:32px;font-weight:800;letter-spacing:-.05em;margin-top:5px}.stat .icon{float:right;font-size:20px}.section-head{display:flex;align-items:end;justify-content:space-between;gap:12px;margin:25px 0 13px}.section-head h3{font-size:19px;letter-spacing:-.03em;margin:0}.section-head p{color:var(--muted);font-size:12px;margin:4px 0 0}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px}.card{padding:18px;min-width:0}.card-top{display:flex;justify-content:space-between;align-items:center;gap:12px}.tag{display:inline-flex;align-items:center;gap:6px;border:1px solid #3a4d2e;background:#222e1b;color:var(--green);font-size:11px;font-weight:800;padding:5px 9px;border-radius:999px}.tag.cancelled{color:var(--red);border-color:#613b36;background:#2b1d1a}.tag.done{color:var(--muted);border-color:var(--line);background:#20231d}.card h4{font-size:18px;margin:13px 0 5px;letter-spacing:-.025em;overflow-wrap:anywhere}.desc{font-size:13px;color:var(--muted);min-height:20px;overflow-wrap:anywhere}.meta{display:flex;align-items:center;justify-content:space-between;gap:10px;border-top:1px solid var(--line);padding-top:13px;margin-top:15px;color:#cbd3c4;font-size:12px}.meta span{display:flex;align-items:center;gap:7px}.empty{padding:26px;border:1px dashed #3a4534;border-radius:17px;color:var(--muted);text-align:center;grid-column:1/-1}.poll-option{margin-top:13px}.poll-label{display:flex;justify-content:space-between;gap:10px;font-size:12px;color:#d5ddce}.bar{height:7px;margin-top:7px;border-radius:99px;background:#30372b;overflow:hidden}.fill{height:100%;border-radius:99px;background:linear-gradient(90deg,var(--green2),var(--green))}.footer{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;border-top:1px solid var(--line);margin-top:32px;padding-top:18px;color:var(--muted);font-size:12px}.refresh{color:var(--green)}@media(max-width:760px){.wrap{padding:18px 13px 30px}.top{align-items:flex-start}.live{font-size:0;padding:11px}.live .dot{margin:0}.hero{padding:23px 20px}.hero:after{right:10px;top:28px;font-size:75px}.stats{grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.stat{padding:14px}.stat .num{font-size:27px}.grid{grid-template-columns:1fr}.brand h1{font-size:20px}}
</style></head><body><main class="wrap"><header class="top"><div class="brand"><div class="logo">🍄</div><div><div class="eyebrow">Topluluk merkezi</div><h1>Mahzen <span style="color:var(--green)">/</span> Fedya</h1></div></div><div class="live"><span class="dot"></span><span>Canlı panel · 30 saniyede bir yenilenir</span></div></header>
<section class="hero"><div class="kicker">Mahzen'e hoş geldin</div><h2>Oyun geceleri burada başlar.</h2><p>Yaklaşan etkinlikleri takip et, katılım durumunu gör ve Mahzen'in sıradaki planından haberdar ol. Hepsi tek yerde. 🍄</p></section>
<section class="stats"><article class="stat"><span class="icon">📅</span><div class="label">Yaklaşan etkinlik</div><div class="num" id="upcoming">—</div></article><article class="stat"><span class="icon">🎮</span><div class="label">Planlı etkinlik</div><div class="num" id="planned">—</div></article><article class="stat"><span class="icon">🙋</span><div class="label">Katılım işaretleri</div><div class="num" id="going">—</div></article><article class="stat"><span class="icon">🗳️</span><div class="label">Açık anket</div><div class="num" id="pollCount">—</div></article></section>
<section><div class="section-head"><div><h3>📆 Etkinlik takvimi</h3><p>Discord'daki Fedya duyurularından güncellenir.</p></div><span class="tag">MAHZEN</span></div><div class="grid" id="events"><div class="empty">Etkinlikler yükleniyor…</div></div></section>
<section><div class="section-head"><div><h3>🗳️ Topluluk anketleri</h3><p>Oy durumları ve seçenekler.</p></div></div><div class="grid" id="polls"><div class="empty">Anketler yükleniyor…</div></div></section>
<footer class="footer"><span>🍄 Mahzen • Fedya Dashboard</span><span>Son güncelleme: <b class="refresh" id="updated">yükleniyor</b></span></footer></main>
<script>
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
function eventCard(e){const cls=e.status==="cancelled"?"cancelled":e.status!=="planned"?"done":"";const label=e.status==="planned"?"Planlandı":e.status==="cancelled"?"İptal edildi":e.status==="failed"?"Gönderilemedi":e.status;return `<article class="card"><div class="card-top"><span class="tag ${cls}">${esc(label)}</span><span style="color:var(--muted);font-size:11px">ETKİNLİK #${e.id}</span></div><h4>${esc(e.title)}</h4><div class="desc">${esc(e.description||"Mahzen etkinliği — ayrıntılar Discord'da.")}</div><div class="meta"><span>🕒 ${esc(e.display_time)}</span><span>🎮 ${e.going} katılıyor</span></div></article>`}
function pollCard(p){const total=p.total||0;const options=p.options.map(o=>{const pct=total?Math.round(o.votes*100/total):0;return `<div class="poll-option"><div class="poll-label"><span>${esc(o.label)}</span><b>${o.votes} · ${pct}%</b></div><div class="bar"><div class="fill" style="width:${pct}%"></div></div></div>`}).join("");return `<article class="card"><div class="card-top"><span class="tag ${p.status!=="open"?"done":""}">${p.status==="open"?"Oylama açık":"Kapalı"}</span><span style="color:var(--muted);font-size:11px">ANKET #${p.id}</span></div><h4>${esc(p.question)}</h4>${options}<div class="meta"><span>🗳️ Toplam ${total} oy</span><span>${p.options.length} seçenek</span></div></article>`}
async function refresh(){try{const r=await fetch("/api/dashboard",{cache:"no-store"});if(!r.ok)throw Error("api");const d=await r.json();document.getElementById("upcoming").textContent=d.stats.upcoming_events;document.getElementById("planned").textContent=d.stats.planned_events;document.getElementById("going").textContent=d.stats.total_going;document.getElementById("pollCount").textContent=d.stats.open_polls;document.getElementById("events").innerHTML=d.events.length?d.events.map(eventCard).join(""):'<div class="empty">Henüz etkinlik yok.<br><small>İlk duyuru için Discord’da <b>/duyuru</b> komutunu kullan.</small></div>';document.getElementById("polls").innerHTML=d.polls.length?d.polls.map(pollCard).join(""):'<div class="empty">Henüz anket yok.<br><small>İlk anket için Discord’da <b>/anket</b> komutunu kullan.</small></div>';document.getElementById("updated").textContent=d.updated_at}catch(e){document.getElementById("updated").textContent="bağlantı bekleniyor"}}refresh();setInterval(refresh,30000);
</script></body></html>""")


@web.get("/api/dashboard")
async def api_dashboard():
    return dashboard_data()


@web.get("/health")
async def health():
    return {"ok": True, "service": "mahzen-fedya"}


# ===================== BAŞLAT =====================
async def main():
    init_db()
    if not TOKEN or TOKEN == "BOT_TOKENINI_BURAYA_YAZ":
        raise RuntimeError("DISCORD_TOKEN ortam değişkenini ayarla veya TOKEN alanına bot tokenını yaz.")
    if OWNER_ID == 0 or GUILD_ID == 0:
        raise RuntimeError("OWNER_ID ve GUILD_ID değerlerini ayarla.")
    server = uvicorn.Server(
        uvicorn.Config(web, host="0.0.0.0", port=int(os.getenv("PORT", "8000")), log_level="info")
    )
    await asyncio.gather(bot.start(TOKEN), server.serve())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🍄 Fedya kapatıldı.")
