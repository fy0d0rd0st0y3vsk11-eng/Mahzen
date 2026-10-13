from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp
import discord
from discord import app_commands
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
APP_NAME = "Fedya"
BRAND = "Mahzen"
GREEN = 0x315B45
GREEN_MUTED = 0x233A2F
DARK = 0x111512
TIMEZONE = ZoneInfo(os.getenv("TIMEZONE", "Europe/Istanbul"))
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
OWNER_ID = int(os.getenv("OWNER_ID", "0") or 0)
GUILD_ID = int(os.getenv("GUILD_ID", "0") or 0)
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", "data/mahzen.db"))
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
AI_MODEL = os.getenv("AI_MODEL", "openrouter/auto").strip()
AI_SITE_URL = os.getenv("AI_SITE_URL", "https://mahzen-fedya.onrender.com").strip()
AI_SITE_NAME = os.getenv("AI_SITE_NAME", "Mahzen | Fedya").strip()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("fedya")

GAME_ROLES = [
    "Among Us",
    "Minecraft",
    "Gartic Phone",
    "Critical Ops",
    "Horror / Co-op",
    "Party Games",
    "Strategy",
    "Indie Games",
    "Night Owl",
]

AI_SYSTEM_PROMPT = """Sen Fedya'sın; Mahzen Discord topluluğunun kısa, zeki ve doğal konuşan yardımcı asistanısın.
Türkçe konuş; kullanıcı başka dilde yazarsa o dilde yanıt ver. Gereksiz rol yapma, aşırı emoji,
cringe internet dili ve kendini gerçek insan gibi tanıtma. Gerekli olduğunda espri yap ama kimseyi
küçümseme. Tartışmalarda taraf tutmadan bağlamı ayır; emin olmadığında bunu söyle. Kişisel bilgileri
ifşa etmeye, tacize veya tehditlere yardımcı olma. Yanıtları genellikle kısa ve kullanışlı tut."""


def now_local() -> datetime:
    return datetime.now(TIMEZONE)


def parse_event_time(raw: str) -> datetime:
    """Parse YYYY-MM-DD HH:MM as Istanbul local time."""
    value = datetime.strptime(raw.strip(), "%Y-%m-%d %H:%M")
    return value.replace(tzinfo=TIMEZONE)


def format_time(raw: str) -> str:
    value = datetime.fromisoformat(raw)
    if value.tzinfo is None:
        value = value.replace(tzinfo=TIMEZONE)
    return value.astimezone(TIMEZONE).strftime("%d.%m.%Y · %H:%M")


def db_connect() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DATABASE_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    return con


def init_db() -> None:
    with db_connect() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                starts_at TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                channel_id INTEGER NOT NULL,
                message_id INTEGER,
                status TEXT NOT NULL DEFAULT 'planned',
                created_by INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS event_rsvps (
                event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('yes','no')),
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(event_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS polls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT NOT NULL,
                options TEXT NOT NULL,
                channel_id INTEGER NOT NULL,
                message_id INTEGER,
                status TEXT NOT NULL DEFAULT 'open',
                created_by INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS votes (
                poll_id INTEGER NOT NULL REFERENCES polls(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL,
                choice INTEGER NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(poll_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS attendance (
                event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'attended',
                marked_by INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(event_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS member_roles (
                user_id INTEGER NOT NULL,
                role_name TEXT NOT NULL,
                PRIMARY KEY(user_id, role_name)
            );
            """
        )
        # Additive migrations keep an existing Mahzen database usable after upgrade.
        migrations = {
            "events": [
                ("created_by", "INTEGER NOT NULL DEFAULT 0"),
                ("created_at", "TEXT NOT NULL DEFAULT ''"),
            ],
            "polls": [
                ("created_by", "INTEGER NOT NULL DEFAULT 0"),
                ("created_at", "TEXT NOT NULL DEFAULT ''"),
            ],
            "attendance": [("marked_by", "INTEGER NOT NULL DEFAULT 0")],
        }
        for table, columns in migrations.items():
            existing = {row["name"] for row in con.execute(f"PRAGMA table_info({table})").fetchall()}
            for column, declaration in columns:
                if column not in existing:
                    con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


def decode_options(raw: str) -> list[str]:
    """Read both the new JSON format and the previous app's `||` format."""
    try:
        value = json.loads(raw)
        if isinstance(value, list):
            return [str(item) for item in value]
    except (json.JSONDecodeError, TypeError):
        pass
    return [item for item in str(raw).split("||") if item]


def query_one(sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
    with db_connect() as con:
        return con.execute(sql, params).fetchone()


def query_all(sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    with db_connect() as con:
        return con.execute(sql, params).fetchall()


def is_owner(user: discord.abc.User) -> bool:
    return bool(OWNER_ID and user.id == OWNER_ID) or bool(
        isinstance(user, discord.Member) and user.guild_permissions.administrator
    )


def base_embed(title: str, description: str = "") -> discord.Embed:
    embed = discord.Embed(title=title, description=description or None, color=GREEN)
    embed.set_footer(text="MAHZEN  /  FEDYA")
    return embed


def event_embed(event: sqlite3.Row) -> discord.Embed:
    rsvps = query_all(
        "SELECT status, COUNT(*) AS n FROM event_rsvps WHERE event_id=? GROUP BY status",
        (event["id"],),
    )
    counts = {row["status"]: row["n"] for row in rsvps}
    embed = base_embed(event["title"], event["description"] or "Açıklama eklenmemiş.")
    embed.add_field(name="Tarih", value=format_time(event["starts_at"]), inline=True)
    embed.add_field(name="Katılacak", value=str(counts.get("yes", 0)), inline=True)
    embed.add_field(name="Katılmayacak", value=str(counts.get("no", 0)), inline=True)
    embed.add_field(name="Etkinlik no", value=f"#{event['id']}", inline=False)
    return embed


def get_event(event_id: int) -> sqlite3.Row | None:
    return query_one("SELECT * FROM events WHERE id=?", (event_id,))


def get_poll(poll_id: int) -> sqlite3.Row | None:
    return query_one("SELECT * FROM polls WHERE id=?", (poll_id,))


class EventView(discord.ui.View):
    def __init__(self, event_id: int):
        super().__init__(timeout=None)
        self.event_id = event_id
        yes = discord.ui.Button(label="Katılacağım", style=discord.ButtonStyle.success, custom_id=f"event:{event_id}:yes")
        no = discord.ui.Button(label="Katılamıyorum", style=discord.ButtonStyle.secondary, custom_id=f"event:{event_id}:no")
        yes.callback = self.make_callback("yes")
        no.callback = self.make_callback("no")
        self.add_item(yes)
        self.add_item(no)

    def make_callback(self, status: str):
        async def callback(interaction: discord.Interaction) -> None:
            event = get_event(self.event_id)
            if not event or event["status"] != "planned":
                await interaction.response.send_message("Bu etkinlik artık aktif değil.", ephemeral=True)
                return
            with db_connect() as con:
                con.execute(
                    "INSERT INTO event_rsvps(event_id,user_id,status,updated_at) VALUES(?,?,?,?) "
                    "ON CONFLICT(event_id,user_id) DO UPDATE SET status=excluded.status, updated_at=excluded.updated_at",
                    (self.event_id, interaction.user.id, status, now_local().isoformat()),
                )
            await interaction.response.send_message(
                "Katılım tercihin kaydedildi." if status == "yes" else "Katılamayacağını kaydettim.",
                ephemeral=True,
            )
            try:
                if interaction.message:
                    await interaction.message.edit(embed=event_embed(event), view=self)
            except discord.HTTPException:
                log.exception("Etkinlik mesajı güncellenemedi: event=%s", self.event_id)
        return callback


class PollView(discord.ui.View):
    def __init__(self, poll_id: int, options: list[str]):
        super().__init__(timeout=None)
        self.poll_id = poll_id
        for index, option in enumerate(options[:5]):
            button = discord.ui.Button(
                label=option[:80], style=discord.ButtonStyle.secondary,
                custom_id=f"poll:{poll_id}:{index}", row=index // 3,
            )
            button.callback = self.make_callback(index)
            self.add_item(button)

    def make_callback(self, choice: int):
        async def callback(interaction: discord.Interaction) -> None:
            poll = get_poll(self.poll_id)
            if not poll or poll["status"] != "open":
                await interaction.response.send_message("Bu anket kapatılmış.", ephemeral=True)
                return
            with db_connect() as con:
                con.execute(
                    "INSERT INTO votes(poll_id,user_id,choice,updated_at) VALUES(?,?,?,?) "
                    "ON CONFLICT(poll_id,user_id) DO UPDATE SET choice=excluded.choice, updated_at=excluded.updated_at",
                    (self.poll_id, interaction.user.id, choice, now_local().isoformat()),
                )
            await interaction.response.send_message("Oy tercihin kaydedildi.", ephemeral=True)
        return callback


class FedyaBot(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self._synced = False

    async def setup_hook(self) -> None:
        init_db()
        # Re-register persistent buttons after process restarts.
        for event in query_all("SELECT id FROM events WHERE status='planned' AND message_id IS NOT NULL"):
            self.add_view(EventView(event["id"]))
        for poll in query_all("SELECT id, options FROM polls WHERE status='open' AND message_id IS NOT NULL"):
            self.add_view(PollView(poll["id"], decode_options(poll["options"])))
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("%s slash komutu test sunucusuna kaydedildi.", len(synced))
        else:
            synced = await self.tree.sync()
            log.info("%s slash komutu global olarak kaydedildi.", len(synced))
        self._synced = True

    async def on_ready(self) -> None:
        global _discord_last_error
        _discord_last_error = None
        log.info("Fedya çevrimiçi: %s (id=%s)", self.user, self.user.id if self.user else "?")
        try:
            await self.change_presence(
                activity=discord.Activity(type=discord.ActivityType.watching, name="Mahzen'i")
            )
        except discord.HTTPException:
            log.exception("Durum ayarlanamadı")

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        # Keep AI replies intentional: reply only to a direct mention or a DM.
        is_dm = isinstance(message.channel, discord.DMChannel)
        mentioned = self.user is not None and self.user in message.mentions
        if not (is_dm or mentioned):
            return
        cleaned = message.content
        if self.user:
            cleaned = re.sub(rf"<@!?{self.user.id}>", "", cleaned).strip()
        if not cleaned:
            cleaned = "Mahzen'de ne oluyor?"
        async with message.channel.typing():
            answer = await ask_fedya_ai(cleaned[:3500], message.author.display_name)
        try:
            await message.reply(answer[:1900], mention_author=False, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            log.exception("AI yanıtı gönderilemedi")


bot = FedyaBot()


# ---------------------------------------------------------------------------
# AI
# ---------------------------------------------------------------------------
async def ask_fedya_ai(user_text: str, display_name: str) -> str:
    if not OPENROUTER_API_KEY:
        return "AI henüz yapılandırılmamış. Sunucu yöneticisi Render'da OPENROUTER_API_KEY ayarlamalı."
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": AI_SITE_URL,
        "X-Title": AI_SITE_NAME,
    }
    payload = {
        "model": AI_MODEL,
        "messages": [
            {"role": "system", "content": AI_SYSTEM_PROMPT},
            {"role": "user", "content": f"Discord kullanıcısı {display_name} diyor ki: {user_text}"},
        ],
        "temperature": 0.7,
        "max_tokens": 450,
    }
    timeout = aiohttp.ClientTimeout(total=25)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                "https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload
            ) as response:
                if response.status >= 400:
                    body = (await response.text())[:350]
                    log.warning("OpenRouter HTTP %s: %s", response.status, body)
                    return "AI bağlantısı şu an yanıt vermiyor. Biraz sonra tekrar dene."
                data = await response.json(content_type=None)
        answer = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return answer.strip()[:1900] or "Yanıt boş döndü; bir kez daha sorar mısın?"
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, IndexError) as exc:
        log.warning("OpenRouter isteği başarısız: %s", type(exc).__name__)
        return "AI bağlantısı kesildi. Biraz sonra tekrar dene."


# ---------------------------------------------------------------------------
# Slash commands — keep all 11 original names
# ---------------------------------------------------------------------------
@bot.tree.command(name="yardim", description="Fedya komutlarını ve kullanımını göster.")
async def yardim(interaction: discord.Interaction) -> None:
    embed = base_embed("Fedya / Komut rehberi", "Mahzen araçları. Gereksiz kalabalık yok.")
    embed.add_field(name="Etkinlikler", value="`/saat` · `/etkinlikler` · `/duyuru` · `/iptal` · `/yoklama`", inline=False)
    embed.add_field(name="Topluluk", value="`/anket` · `/anket_sonucu` · `/roller`", inline=False)
    embed.add_field(name="Üye profili", value="`/profil` · `/siralama`", inline=False)
    embed.add_field(name="AI", value="Fedya'ya mesajda bahset veya DM'den yaz.", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="saat", description="Sıradaki planlanmış etkinliğin saatini göster.")
async def saat(interaction: discord.Interaction) -> None:
    event = query_one(
        "SELECT * FROM events WHERE status='planned' AND starts_at>=? ORDER BY starts_at LIMIT 1",
        (now_local().isoformat(),),
    )
    if not event:
        await interaction.response.send_message("Şu anda yaklaşan etkinlik yok.", ephemeral=True)
        return
    await interaction.response.send_message(embed=event_embed(event))


@bot.tree.command(name="etkinlikler", description="Yaklaşan etkinlikleri listele.")
async def etkinlikler(interaction: discord.Interaction) -> None:
    events = query_all(
        "SELECT * FROM events WHERE status='planned' AND starts_at>=? ORDER BY starts_at LIMIT 10",
        (now_local().isoformat(),),
    )
    if not events:
        await interaction.response.send_message("Yaklaşan etkinlik bulunmuyor.", ephemeral=True)
        return
    embed = base_embed("Mahzen / Etkinlik takvimi")
    for event in events:
        rsvps = query_one("SELECT COUNT(*) AS n FROM event_rsvps WHERE event_id=? AND status='yes'", (event["id"],))
        embed.add_field(
            name=f"#{event['id']} · {event['title']}",
            value=f"{format_time(event['starts_at'])} · {rsvps['n']} kişi katılacak",
            inline=False,
        )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="duyuru", description="Yeni bir etkinlik oluştur ve duyur.")
@app_commands.describe(oyun="Etkinliğin adı", tarih_saat="YYYY-AA-GG SS:DD (Türkiye saati)", aciklama="Kısa açıklama")
async def duyuru(interaction: discord.Interaction, oyun: str, tarih_saat: str, aciklama: str = "") -> None:
    if not is_owner(interaction.user):
        await interaction.response.send_message("Bu komut yöneticiye açık.", ephemeral=True)
        return
    if not interaction.guild or not interaction.channel:
        await interaction.response.send_message("Bu komutu sunucu kanalında kullan.", ephemeral=True)
        return
    try:
        start = parse_event_time(tarih_saat)
        if start <= now_local():
            raise ValueError("past")
    except ValueError:
        await interaction.response.send_message("Tarih gelecekte olmalı. Örnek: `2026-10-20 20:30`", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    with db_connect() as con:
        cursor = con.execute(
            "INSERT INTO events(title,starts_at,description,channel_id,created_by) VALUES(?,?,?,?,?)",
            (oyun.strip()[:100], start.isoformat(), aciklama.strip()[:1000], interaction.channel_id, interaction.user.id),
        )
        event_id = cursor.lastrowid
    event = get_event(event_id)
    try:
        message = await interaction.channel.send(embed=event_embed(event), view=EventView(event_id))
        with db_connect() as con:
            con.execute("UPDATE events SET message_id=? WHERE id=?", (message.id, event_id))
    except discord.HTTPException:
        with db_connect() as con:
            con.execute("UPDATE events SET status='failed' WHERE id=?", (event_id,))
        await interaction.followup.send("Duyuru gönderilemedi. Kanal izinlerini kontrol et.", ephemeral=True)
        return
    await interaction.followup.send(f"Etkinlik oluşturuldu: `#{event_id}`", ephemeral=True)


@bot.tree.command(name="iptal", description="Planlanmış bir etkinliği iptal et.")
@app_commands.describe(etkinlik_no="İptal edilecek etkinliğin numarası")
async def iptal(interaction: discord.Interaction, etkinlik_no: int) -> None:
    if not is_owner(interaction.user):
        await interaction.response.send_message("Bu komut yöneticiye açık.", ephemeral=True)
        return
    event = get_event(etkinlik_no)
    if not event or event["status"] != "planned":
        await interaction.response.send_message("Aktif etkinlik bulunamadı.", ephemeral=True)
        return
    with db_connect() as con:
        con.execute("UPDATE events SET status='cancelled' WHERE id=?", (etkinlik_no,))
    channel = bot.get_channel(event["channel_id"])
    if channel and event["message_id"]:
        try:
            message = await channel.fetch_message(event["message_id"])
            await message.edit(embed=base_embed("Etkinlik iptal edildi", f"#{etkinlik_no} · {event['title']}"), view=None)
        except discord.HTTPException:
            log.info("İptal edilen etkinlik mesajı güncellenemedi: %s", etkinlik_no)
    await interaction.response.send_message(f"Etkinlik `#{etkinlik_no}` iptal edildi.", ephemeral=True)


@bot.tree.command(name="anket", description="2–5 seçenekli bir anket oluştur.")
@app_commands.describe(soru="Anket sorusu", secenekler="Seçenekleri | karakteriyle ayır")
async def anket(interaction: discord.Interaction, soru: str, secenekler: str) -> None:
    if not is_owner(interaction.user):
        await interaction.response.send_message("Bu komut yöneticiye açık.", ephemeral=True)
        return
    if not interaction.channel:
        await interaction.response.send_message("Kanal bulunamadı.", ephemeral=True)
        return
    clean_question = soru.strip()
    options = [part.strip() for part in secenekler.split("|") if part.strip()]
    if not clean_question:
        await interaction.response.send_message("Anket sorusu boş olamaz.", ephemeral=True)
        return
    if not 2 <= len(options) <= 5 or any(len(x) > 80 for x in options):
        await interaction.response.send_message("2–5 seçenek gir; her seçenek en fazla 80 karakter. Örnek: `Among Us | Minecraft | GGD`", ephemeral=True)
        return
    # Creating a message may take longer than Discord's initial interaction window.
    await interaction.response.defer(ephemeral=True)
    with db_connect() as con:
        cursor = con.execute(
            "INSERT INTO polls(question,options,channel_id,created_by) VALUES(?,?,?,?)",
            (clean_question[:200], json.dumps(options, ensure_ascii=False), interaction.channel_id, interaction.user.id),
        )
        poll_id = cursor.lastrowid
    embed = base_embed(clean_question[:200], "Bir seçeneğe basarak oy ver. Oyunu değiştirmen mümkün.")
    embed.add_field(name="Seçenekler", value="\n".join(f"**{i + 1}.** {option}" for i, option in enumerate(options)), inline=False)
    try:
        message = await interaction.channel.send(embed=embed, view=PollView(poll_id, options))
        with db_connect() as con:
            con.execute("UPDATE polls SET message_id=? WHERE id=?", (message.id, poll_id))
    except discord.HTTPException:
        with db_connect() as con:
            con.execute("UPDATE polls SET status='failed' WHERE id=?", (poll_id,))
        await interaction.followup.send("Anket gönderilemedi. Kanal izinlerini kontrol et.", ephemeral=True)
        return
    await interaction.followup.send(f"Anket oluşturuldu: `#{poll_id}`", ephemeral=True)


@bot.tree.command(name="anket_sonucu", description="Bir anketin güncel sonuçlarını göster.")
@app_commands.describe(anket_no="Anket numarası")
async def anket_sonucu(interaction: discord.Interaction, anket_no: int) -> None:
    poll = get_poll(anket_no)
    if not poll:
        await interaction.response.send_message("Bu numarayla anket bulunamadı.", ephemeral=True)
        return
    options = decode_options(poll["options"])
    rows = query_all("SELECT choice, COUNT(*) AS n FROM votes WHERE poll_id=? GROUP BY choice", (anket_no,))
    counts = {row["choice"]: row["n"] for row in rows}
    total = sum(counts.values())
    embed = base_embed(f"Anket sonuçları / #{anket_no}", poll["question"])
    for i, option in enumerate(options):
        n = counts.get(i, 0)
        pct = (n / total * 100) if total else 0
        bar = "█" * round(pct / 10) + "░" * (10 - round(pct / 10))
        embed.add_field(name=option, value=f"`{bar}`  {n} oy · %{pct:.0f}", inline=False)
    embed.add_field(name="Toplam oy", value=str(total), inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="roller", description="Oyun ilgi alanı rollerini seç veya kaldır.")
async def roller(interaction: discord.Interaction) -> None:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("Bu komutu sunucuda kullan.", ephemeral=True)
        return
    view = discord.ui.View(timeout=300)
    for role_name in GAME_ROLES:
        button = discord.ui.Button(label=role_name, style=discord.ButtonStyle.secondary)
        async def callback(i: discord.Interaction, name: str = role_name) -> None:
            if not i.guild or not isinstance(i.user, discord.Member):
                await i.response.send_message("Bu komutu sunucuda kullan.", ephemeral=True)
                return
            role = discord.utils.get(i.guild.roles, name=name)
            if role is None:
                await i.response.send_message(f"Sunucuda `{name}` rolü henüz oluşturulmamış.", ephemeral=True)
                return
            try:
                if role in i.user.roles:
                    await i.user.remove_roles(role, reason="Fedya self-role menu")
                    with db_connect() as con:
                        con.execute("DELETE FROM member_roles WHERE user_id=? AND role_name=?", (i.user.id, name))
                    answer = f"{name} rolü kaldırıldı."
                else:
                    await i.user.add_roles(role, reason="Fedya self-role menu")
                    with db_connect() as con:
                        con.execute("INSERT OR IGNORE INTO member_roles(user_id,role_name) VALUES(?,?)", (i.user.id, name))
                    answer = f"{name} rolü eklendi."
                await i.response.send_message(answer, ephemeral=True)
            except discord.Forbidden:
                await i.response.send_message("Fedya'nın Manage Roles izni olmalı ve bot rolü oyun rollerinin üstünde olmalı.", ephemeral=True)
            except discord.HTTPException:
                log.exception("Rol güncellenemedi")
                await i.response.send_message("Rol güncellenemedi; tekrar dene.", ephemeral=True)
        button.callback = callback
        view.add_item(button)
    await interaction.response.send_message(embed=base_embed("Oyun rolleri", "İlgilendiğin oyunları seç. Aynı düğmeye yeniden basarsan rol kaldırılır."), view=view, ephemeral=True)


@bot.tree.command(name="yoklama", description="Bir etkinlik için katılım puanı kaydet (yönetici).")
@app_commands.describe(etkinlik_no="Etkinlik numarası", uye="Katılımı onaylanacak üye")
async def yoklama(interaction: discord.Interaction, etkinlik_no: int, uye: discord.Member) -> None:
    if not is_owner(interaction.user):
        await interaction.response.send_message("Bu komut yöneticiye açık.", ephemeral=True)
        return
    event = get_event(etkinlik_no)
    if not event:
        await interaction.response.send_message("Etkinlik bulunamadı.", ephemeral=True)
        return
    with db_connect() as con:
        con.execute(
            "INSERT INTO attendance(event_id,user_id,status,marked_by) VALUES(?,?,?,?) "
            "ON CONFLICT(event_id,user_id) DO UPDATE SET status='attended', marked_by=excluded.marked_by",
            (etkinlik_no, uye.id, "attended", interaction.user.id),
        )
    await interaction.response.send_message(f"{uye.mention} için `#{etkinlik_no}` katılımı kaydedildi.", ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


@bot.tree.command(name="profil", description="Katılım puanını, rollerini ve başarımlarını göster.")
async def profil(interaction: discord.Interaction) -> None:
    row = query_one("SELECT COUNT(*) AS n FROM attendance WHERE user_id=? AND status='attended'", (interaction.user.id,))
    count = row["n"] if row else 0
    roles = query_all("SELECT role_name FROM member_roles WHERE user_id=? ORDER BY role_name", (interaction.user.id,))
    achievements = []
    if count >= 1: achievements.append("İlk Etkinlik")
    if count >= 5: achievements.append("Mahzen Müdavimi")
    if count >= 10: achievements.append("Mahzen Efsanesi")
    embed = base_embed(f"{interaction.user.display_name} / Profil")
    embed.set_thumbnail(url=interaction.user.display_avatar.url)
    embed.add_field(name="Puan", value=str(count * 10), inline=True)
    embed.add_field(name="Katılım", value=str(count), inline=True)
    embed.add_field(name="Başarımlar", value=" · ".join(achievements) or "Henüz başarı yok", inline=False)
    embed.add_field(name="Oyun rolleri", value=" · ".join(row["role_name"] for row in roles) or "Henüz rol seçilmedi", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="siralama", description="Mahzen katılım puanı sıralamasını göster.")
async def siralama(interaction: discord.Interaction) -> None:
    rows = query_all(
        "SELECT user_id, COUNT(*) AS n FROM attendance WHERE status='attended' GROUP BY user_id ORDER BY n DESC, user_id ASC LIMIT 10"
    )
    if not rows:
        await interaction.response.send_message("Henüz katılım puanı kazanılmamış.", ephemeral=True)
        return
    lines = []
    medals = ["1.", "2.", "3."]
    for index, row in enumerate(rows):
        label = medals[index] if index < 3 else f"{index + 1}."
        lines.append(f"**{label}** <@{row['user_id']}> — **{row['n'] * 10}** puan")
    await interaction.response.send_message(embed=base_embed("Mahzen / Sıralama", "\n".join(lines)))


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
    log.error("Slash komut hatası (%s): %s", getattr(interaction.command, "name", "?"), repr(error), exc_info=error)
    message = "Komut çalışırken bir hata oluştu. Hata kaydı konsola yazıldı."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException:
        pass


# ---------------------------------------------------------------------------
# FastAPI health endpoint and lightweight status page
# ---------------------------------------------------------------------------
_shutdown_event = asyncio.Event()
_discord_task: asyncio.Task | None = None
_discord_last_error: str | None = None


async def _wait_before_retry(seconds: int) -> None:
    """Wait for a retry delay, but wake immediately during web-service shutdown."""
    try:
        await asyncio.wait_for(_shutdown_event.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass


async def supervise_discord_gateway() -> None:
    """Keep gateway startup failures visible and retry instead of silently leaving web-only mode."""
    global _discord_last_error
    delay = 5
    while not _shutdown_event.is_set():
        try:
            log.info("Discord gateway bağlantısı başlatılıyor.")
            await bot.start(DISCORD_TOKEN, reconnect=True)
            if not _shutdown_event.is_set():
                _discord_last_error = "Discord bağlantısı beklenmedik şekilde sonlandı."
                log.error(_discord_last_error)
        except asyncio.CancelledError:
            raise
        except discord.LoginFailure:
            _discord_last_error = "Discord token doğrulanamadı; Render DISCORD_TOKEN değerini kontrol edin."
            log.exception(_discord_last_error)
            delay = 60
        except Exception as exc:
            _discord_last_error = type(exc).__name__
            log.exception("Discord gateway başlatılamadı; %s saniye sonra yeniden denenecek.", delay)
        if _shutdown_event.is_set():
            break
        await _wait_before_retry(delay)
        delay = min(max(delay * 2, 5), 60)


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _discord_task, _discord_last_error
    init_db()
    _shutdown_event.clear()
    _discord_last_error = None
    if DISCORD_TOKEN:
        _discord_task = asyncio.create_task(supervise_discord_gateway(), name="fedya-discord-supervisor")
    else:
        _discord_task = None
        _discord_last_error = "DISCORD_TOKEN eksik."
        log.error("DISCORD_TOKEN eksik. Web sağlık kontrolü açık, Discord botu başlamadı.")
    try:
        yield
    finally:
        _shutdown_event.set()
        if not bot.is_closed():
            await bot.close()
        if _discord_task:
            _discord_task.cancel()
            try:
                await asyncio.wait_for(_discord_task, timeout=8)
            except asyncio.CancelledError:
                pass
            except asyncio.TimeoutError:
                log.warning("Discord gateway görevi 8 saniye içinde kapanmadı.")
            except Exception:
                log.exception("Discord görev kapanışı sırasında hata")
        _discord_task = None


web = FastAPI(title="Fedya · Mahzen", version="2.0.0", lifespan=lifespan)


@web.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({
        "status": "ok",
        "service": "fedya",
        "discord_configured": bool(DISCORD_TOKEN),
        "discord_connected": bot.is_ready(),
        "discord_task_running": bool(_discord_task and not _discord_task.done()),
        "discord_last_error": _discord_last_error,
        "ai_configured": bool(OPENROUTER_API_KEY),
        "time": now_local().isoformat(),
    })


@web.get("/", response_class=HTMLResponse)
async def home() -> str:
    state = "Connected" if bot.is_ready() else "Starting / offline"
    ai_state = "Configured" if OPENROUTER_API_KEY else "Not configured"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Fedya · Mahzen</title><style>
:root{{color-scheme:dark;--bg:#0d100e;--panel:#151b17;--line:#29372e;--green:#7da58a;--muted:#a5b1a8}}
*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 15% 0%,#1b2b20 0,transparent 34%),var(--bg);color:#edf2ed;font:16px/1.6 system-ui,sans-serif;min-height:100vh;display:grid;place-items:center;padding:24px}}
main{{width:min(680px,100%)}}.eyebrow{{letter-spacing:.18em;text-transform:uppercase;color:var(--green);font-size:12px;font-weight:700}}h1{{font-size:clamp(42px,9vw,72px);line-height:1;margin:12px 0 14px;letter-spacing:-.06em}}p{{color:var(--muted)}}.panel{{margin-top:26px;border:1px solid var(--line);background:#121713d9;border-radius:18px;padding:22px}}.row{{display:flex;justify-content:space-between;gap:20px;padding:13px 0;border-bottom:1px solid var(--line)}}.row:last-child{{border:0}}.value{{color:var(--green);font-weight:650}}a{{color:var(--green)}}footer{{margin-top:18px;color:#68756c;font-size:12px}}
</style></head><body><main><div class="eyebrow">Mahzen / Community infrastructure</div><h1>Fedya<span style="color:var(--green)">.</span></h1><p>Minimal, reliable tools for the community. This page is a service status screen, not a control panel.</p><section class="panel"><div class="row"><span>Web service</span><span class="value">Online</span></div><div class="row"><span>Discord gateway</span><span class="value">{state}</span></div><div class="row"><span>OpenRouter AI</span><span class="value">{ai_state}</span></div><div class="row"><span>Health endpoint</span><span><a href="/health">/health</a></span></div></section><footer>FEDYA / MAHZEN · Private community bot</footer></main></body></html>"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:web", host="0.0.0.0", port=int(os.getenv("PORT", "10000")), log_level="info")
