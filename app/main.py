import os
import asyncio
import requests
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request

from .db import Base, engine, SessionLocal
from . import models
from .keyboards import admin_menu, user_menu, promo_buttons
from .services import (
    ensure_single_group_config,
    ensure_admin,
    is_admin,
    upsert_subscriber,
    get_all_subscribers,
    set_group,
    set_invite_link,
    add_join_event,
    should_send_first_promo,
    should_send_every_20_promo,
    log_promo,
    create_broadcast_log,
    build_stats_text,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
BASE_URL = os.getenv("BASE_URL")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_IDS = os.getenv("ADMIN_IDS", "")
BOT_USERNAME = os.getenv("BOT_USERNAME")

API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

PROMO_PHOTO = "https://i.postimg.cc/hPF89qS6/photo-5857106632125386141-y.jpg"
PROMO_TEXT = (
    "🔥 Bienvenue à tous les Anti-Javana.\n\n"
    "Javana est un scam.UNE ARNAQUE!\n"
    "Ils récupèrent les vidéos que nous publions pour alimenter leur VIP… "
    "et ensuite nous les faire payer.\n\n"
    "Alors un groupe a décidé de ne plus se plier et de se rebeller.\n\n"
    "Ici, pas de hiérarchie, pas de discrimination.\n"
    "Seulement des bots sous intelligence artificielle pour assurer le bon fonctionnement du groupe.\n\n"
    "Trop, c’est trop.\n"
    "Nous savons que cela dérange.\n"
    "Mais nos bots détectent les traîtres, les signalements abusifs et les infiltrations.\n\n"
    "Clique sur le bouton pour t’enregistrer et recevoir en temps réel le nouveau lien "
    "si le groupe venait à disparaître.\n"
    "Le remplacement est immédiat, automatisé, et actif 24h/24.\n\n"
    "Le contenu ne disparaît jamais.\n\n"
    "Par le peuple, pour le peuple.")

FIRST_PROMO_DELETE_AFTER = 600
EACH_20_PROMO_DELETE_AFTER = 300

PENDING_ACTIONS = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("STARTUP OK", flush=True)
    print("DATABASE_URL =", DATABASE_URL, flush=True)
    print("KNOWN TABLES =", list(Base.metadata.tables.keys()), flush=True)

    Base.metadata.create_all(bind=engine)
    print("TABLES CREATED", flush=True)

    db = SessionLocal()
    try:
        ensure_single_group_config(db)

        for raw_id in ADMIN_IDS.split(","):
            raw_id = raw_id.strip()
            if raw_id:
                ensure_admin(db, int(raw_id), None)

    finally:
        db.close()

    yield


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def root():
    return {"status": "ok"}


@app.get("/set-webhook")
async def set_webhook():
    webhook_url = f"{BASE_URL}/webhook"
    r = requests.post(f"{API_URL}/setWebhook", json={"url": webhook_url})
    return r.json()


def tg_post(method, payload):
    return requests.post(f"{API_URL}/{method}", json=payload)


def send_message(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return tg_post("sendMessage", payload)


def send_photo(chat_id, photo, caption, reply_markup=None):
    payload = {
        "chat_id": chat_id,
        "photo": photo,
        "caption": caption,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return tg_post("sendPhoto", payload)


def delete_message(chat_id, message_id):
    return tg_post("deleteMessage", {"chat_id": chat_id, "message_id": message_id})


async def delete_later(chat_id, message_id, delay):
    await asyncio.sleep(delay)
    try:
        delete_message(chat_id, message_id)
    except:
        pass


def send_promo(group_id, link, delay):
    r = send_photo(
        group_id,
        PROMO_PHOTO,
        PROMO_TEXT,
        promo_buttons(link, BOT_USERNAME)
    )

    try:
        msg_id = r.json()["result"]["message_id"]
        asyncio.create_task(delete_later(group_id, msg_id, delay))
        return msg_id
    except:
        return None


def handle_private(db, msg):
    user = msg["from"]
    uid = user["id"]
    chat_id = msg["chat"]["id"]
    text = msg.get("text", "")

    upsert_subscriber(db, uid, user.get("username"), user.get("first_name"), user.get("language_code"))

    if text == "/start":
        if is_admin(db, uid):
            send_message(chat_id, "👑 Admin panel", admin_menu())
        else:
            send_message(chat_id, "✅ Enregistré", user_menu())
        return

    if not is_admin(db, uid):
        return

    pending = PENDING_ACTIONS.get(uid)

    if pending == "link":
        set_invite_link(db, text)
        PENDING_ACTIONS.pop(uid)
        send_message(chat_id, "✅ Lien mis à jour", admin_menu())

    if pending == "broadcast":
        cfg = ensure_single_group_config(db)
        send_message(cfg.group_chat_id, text)
        PENDING_ACTIONS.pop(uid)
        send_message(chat_id, "✅ Broadcast envoyé", admin_menu())


def handle_group(db, msg):
    chat = msg["chat"]
    cid = chat["id"]

    set_group(db, cid, chat.get("title"))
    cfg = ensure_single_group_config(db)

    if "new_chat_members" in msg:
        for u in msg["new_chat_members"]:
            if u.get("is_bot"):
                continue

            if u.get("language_code") and not u["language_code"].startswith("fr"):
                tg_post("banChatMember", {"chat_id": cid, "user_id": u["id"]})
                continue

            add_join_event(db, u["id"], u.get("username"), u.get("first_name"), u.get("language_code"), None)

        if should_send_first_promo(db):
            send_promo(cid, cfg.invite_link, FIRST_PROMO_DELETE_AFTER)

        elif should_send_every_20_promo(db):
            send_promo(cid, cfg.invite_link, EACH_20_PROMO_DELETE_AFTER)


def handle_callback(db, cq):
    data = cq["data"]
    uid = cq["from"]["id"]
    chat_id = cq["message"]["chat"]["id"]

    if not is_admin(db, uid):
        return

    if data == "update_link":
        PENDING_ACTIONS[uid] = "link"
        send_message(chat_id, "Envoie le lien")

    elif data == "broadcast_group":
        PENDING_ACTIONS[uid] = "broadcast"
        send_message(chat_id, "Envoie le message")

    elif data == "publish_promo":
        cfg = ensure_single_group_config(db)

        send_promo(
            cfg.group_chat_id,
            cfg.invite_link,
            FIRST_PROMO_DELETE_AFTER
        )

        send_message(chat_id, "✅ Promo publiée")

    elif data == "show_stats":
        send_message(chat_id, build_stats_text(db))

    elif data == "push_link_all":
        cfg = ensure_single_group_config(db)
        users = get_all_subscribers(db)

        for u in users:
            send_message(u.user_id, cfg.invite_link)

        send_message(chat_id, "✅ envoyé")


@app.post("/webhook")
async def webhook(req: Request):
    update = await req.json()
    print("UPDATE:", update, flush=True)

    db = SessionLocal()

    try:
        if "message" in update:
            msg = update["message"]
            if msg["chat"]["type"] == "private":
                handle_private(db, msg)
            else:
                handle_group(db, msg)

        elif "callback_query" in update:
            handle_callback(db, update["callback_query"])

    finally:
        db.close()

    return {"ok": True}


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
