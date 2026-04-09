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
    "Ce groupe contient le plus de médias.\n\n"
    "Tout le monde doit participer : chacun doit envoyer un média avant de demander.\n\n"
    "Arrêtez de demander quand il sera possible d’enregistrer.\n"
    "Pour que les bots vous donnent la possibilité d’enregistrer, c’est simple :\n"
    "enregistrez-vous avec le bouton ci-dessous 👇👇\n\n"
    "Les bots sont 100 % automatisés et effectuent toutes les vérifications en temps réel.\n"
    "Ils vérifient que vous êtes bien enregistré et que vous participez.\n\n"
    "Cela vous permet de recevoir les nouveaux liens au cas où le groupe saute,\n"
    "et de partager le groupe.\n\n"
    "Sans ces deux conditions, vous ne pourrez pas télécharger tous les médias de façon illimitée.\n"
    "Si vous ne l’avez pas fait, ne vous étonnez pas.\n\n"
    "Tout le monde doit participer."
)

FIRST_PROMO_DELETE_AFTER = 1800
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
    r = requests.post(f"{API_URL}/setWebhook", json={"url": webhook_url}, timeout=30)
    return r.json()


def tg_post(method, payload):
    return requests.post(f"{API_URL}/{method}", json=payload, timeout=60)


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


def answer_callback_query(callback_query_id, text=""):
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    return tg_post("answerCallbackQuery", payload)


async def delete_later(chat_id, message_id, delay):
    await asyncio.sleep(delay)
    try:
        delete_message(chat_id, message_id)
    except Exception as e:
        print("DELETE LATER ERROR:", str(e), flush=True)


def send_promo(group_id, link, delay):
    r = send_photo(
        group_id,
        PROMO_PHOTO,
        PROMO_TEXT,
        promo_buttons(link, BOT_USERNAME)
    )

    try:
        data = r.json()
        print("PROMO RESPONSE:", data, flush=True)
        msg_id = data["result"]["message_id"]
        asyncio.create_task(delete_later(group_id, msg_id, delay))
        return msg_id
    except Exception as e:
        print("PROMO ERROR:", str(e), flush=True)
        return None


def language_is_french(language_code):
    if language_code is None:
        return True
    return language_code.lower().startswith("fr")


def push_new_link_to_all(db, link):
    users = get_all_subscribers(db)
    sent = 0

    for u in users:
        try:
            send_message(
                u.user_id,
                f"🔗 Le lien du groupe a été mis à jour :\n{link}",
                user_menu()
            )
            sent += 1
        except Exception as e:
            print("PUSH LINK ERROR:", str(e), flush=True)

    return sent


def handle_private(db, msg):
    user = msg["from"]
    uid = user["id"]
    chat_id = msg["chat"]["id"]
    text = msg.get("text", "").strip()

    upsert_subscriber(
        db,
        uid,
        user.get("username"),
        user.get("first_name"),
        user.get("language_code")
    )

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
        cfg = set_invite_link(db, text)
        PENDING_ACTIONS.pop(uid, None)

        sent = push_new_link_to_all(db, text)

        send_message(
            chat_id,
            f"✅ Lien mis à jour.\n\nLien : {cfg.invite_link}\nEnvoyé à {sent} utilisateur(s).",
            admin_menu()
        )
        return

    if pending == "broadcast":
        cfg = ensure_single_group_config(db)
        PENDING_ACTIONS.pop(uid, None)

        if not cfg.group_chat_id:
            send_message(chat_id, "❌ Aucun groupe défini.", admin_menu())
            return

        send_message(cfg.group_chat_id, text)
        create_broadcast_log(db, uid, cfg.group_chat_id, text)
        send_message(chat_id, "✅ Broadcast envoyé", admin_menu())
        return


def handle_group(db, msg):
    chat = msg["chat"]
    cid = chat["id"]

    set_group(db, cid, chat.get("title"))
    cfg = ensure_single_group_config(db)

    if "new_chat_members" in msg or "left_chat_member" in msg:
        try:
            delete_message(cid, msg["message_id"])
        except Exception as e:
            print("DELETE SERVICE MESSAGE ERROR:", str(e), flush=True)

    if "new_chat_members" in msg:
        added_humans = 0

        for u in msg["new_chat_members"]:
            if u.get("is_bot"):
                continue

            if u.get("language_code") and not language_is_french(u.get("language_code")):
                try:
                    tg_post("banChatMember", {"chat_id": cid, "user_id": u["id"]})
                except Exception as e:
                    print("BAN ERROR:", str(e), flush=True)
                continue

            add_join_event(
                db,
                u["id"],
                u.get("username"),
                u.get("first_name"),
                u.get("language_code"),
                None
            )
            added_humans += 1

        if added_humans == 0:
            return

        if should_send_first_promo(db):
            promo_id = send_promo(cid, cfg.invite_link, FIRST_PROMO_DELETE_AFTER)
            log_promo(db, cid, "first_join", promo_id)
        elif should_send_every_20_promo(db):
            promo_id = send_promo(cid, cfg.invite_link, EACH_20_PROMO_DELETE_AFTER)
            log_promo(db, cid, "every_20", promo_id)


def handle_my_chat_member(db, upd):
    chat = upd.get("chat", {})
    cid = chat.get("id")
    ctype = chat.get("type")

    if not cid or ctype not in ["group", "supergroup"]:
        return

    set_group(db, cid, chat.get("title"))
    cfg = ensure_single_group_config(db)

    new_status = upd.get("new_chat_member", {}).get("status")
    if new_status in ["member", "administrator"]:
        promo_id = send_promo(cid, cfg.invite_link, FIRST_PROMO_DELETE_AFTER)
        log_promo(db, cid, "bot_added", promo_id)


def handle_callback(db, cq):
    data = cq["data"]
    uid = cq["from"]["id"]
    chat_id = cq["message"]["chat"]["id"]
    callback_id = cq["id"]

    # public user callback
    if data == "get_link":
        cfg = ensure_single_group_config(db)
        answer_callback_query(callback_id, "Lien demandé")

        if cfg.invite_link:
            send_message(
                chat_id,
                f"🔗 Voici le lien actuel du groupe :\n{cfg.invite_link}",
                user_menu()
            )
        else:
            send_message(
                chat_id,
                "❌ Le lien du groupe n'a pas encore été défini.",
                user_menu()
            )
        return

    # admin only below
    if not is_admin(db, uid):
        answer_callback_query(callback_id, "Accès refusé")
        return

    if data == "update_link":
        PENDING_ACTIONS[uid] = "link"
        answer_callback_query(callback_id, "En attente du lien")
        send_message(chat_id, "Envoie le nouveau lien du groupe", admin_menu())
        return

    if data == "broadcast_group":
        PENDING_ACTIONS[uid] = "broadcast"
        answer_callback_query(callback_id, "En attente du message")
        send_message(chat_id, "Envoie le message du broadcast", admin_menu())
        return

    if data == "publish_promo":
        cfg = ensure_single_group_config(db)

        if not cfg.group_chat_id:
            answer_callback_query(callback_id, "Aucun groupe défini")
            send_message(chat_id, "❌ Aucun groupe défini.", admin_menu())
            return

        promo_id = send_promo(
            cfg.group_chat_id,
            cfg.invite_link,
            FIRST_PROMO_DELETE_AFTER
        )
        log_promo(db, cfg.group_chat_id, "manual_publish", promo_id)

        answer_callback_query(callback_id, "Promo publiée")
        send_message(chat_id, "✅ Promo publiée", admin_menu())
        return

    if data == "show_stats":
        answer_callback_query(callback_id, "Statistiques")
        send_message(chat_id, build_stats_text(db), admin_menu())
        return

    if data == "push_link_all":
        cfg = ensure_single_group_config(db)

        if not cfg.invite_link:
            answer_callback_query(callback_id, "Lien non défini")
            send_message(chat_id, "❌ Aucun lien défini.", admin_menu())
            return

        sent = push_new_link_to_all(db, cfg.invite_link)
        answer_callback_query(callback_id, "Lien envoyé")
        send_message(chat_id, f"✅ envoyé à {sent} utilisateur(s)", admin_menu())
        return


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

        elif "my_chat_member" in update:
            handle_my_chat_member(db, update["my_chat_member"])

    except Exception as e:
        import traceback
        print("WEBHOOK ERROR:", str(e), flush=True)
        traceback.print_exc()

    finally:
        db.close()

    return {"ok": True}


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000))
    )
