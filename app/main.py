import os
import asyncio
import requests
from fastapi import FastAPI, Request
from .db import Base, engine, SessionLocal
from .keyboards import admin_menu, promo_buttons
from .services import (
    ensure_single_group_config,
    ensure_admin,
    is_admin,
    upsert_subscriber,
    set_group,
    set_invite_link,
    add_join_event,
    should_send_promo,
    create_broadcast_log,
    build_stats_text,
)

app = FastAPI()

BOT_TOKEN = os.getenv("BOT_TOKEN")
BASE_URL = os.getenv("BASE_URL")
ADMIN_IDS = os.getenv("ADMIN_IDS", "")
PROMO_PHOTO = os.getenv("PROMO_PHOTO")
PROMO_TEXT = os.getenv("PROMO_TEXT", "🚀 Rejoins notre communauté et partage le groupe.")
BOT_USERNAME = os.getenv("BOT_USERNAME")

API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else None

# états temporaires admin
PENDING_ACTIONS = {}  # user_id -> "await_invite_link" | "await_broadcast"


@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        ensure_single_group_config(db)
        if ADMIN_IDS.strip():
            for raw_id in ADMIN_IDS.split(","):
                raw_id = raw_id.strip()
                if raw_id:
                    try:
                        ensure_admin(db, int(raw_id), None)
                    except ValueError:
                        pass
    finally:
        db.close()


@app.get("/")
async def root():
    return {"status": "ok", "message": "Second bot is running"}


@app.get("/set-webhook")
async def set_webhook():
    if not BOT_TOKEN:
        return {"ok": False, "error": "BOT_TOKEN missing"}
    if not BASE_URL:
        return {"ok": False, "error": "BASE_URL missing"}

    webhook_url = f"{BASE_URL}/webhook"
    r = requests.post(f"{API_URL}/setWebhook", json={"url": webhook_url}, timeout=30)
    return r.json()


def tg_post(method: str, payload: dict):
    return requests.post(f"{API_URL}/{method}", json=payload, timeout=60)


def send_message(chat_id: int, text: str, reply_markup: dict | None = None):
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return tg_post("sendMessage", payload)


def send_photo(chat_id: int, photo: str, caption: str, reply_markup: dict | None = None):
    payload = {
        "chat_id": chat_id,
        "photo": photo,
        "caption": caption,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return tg_post("sendPhoto", payload)


def delete_message(chat_id: int, message_id: int):
    return tg_post("deleteMessage", {"chat_id": chat_id, "message_id": message_id})


def ban_chat_member(chat_id: int, user_id: int):
    return tg_post("banChatMember", {"chat_id": chat_id, "user_id": user_id})


def answer_callback_query(callback_query_id: str, text: str = ""):
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    return tg_post("answerCallbackQuery", payload)


def edit_message_text(chat_id: int, message_id: int, text: str, reply_markup: dict | None = None):
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return tg_post("editMessageText", payload)


async def delete_later(chat_id: int, message_id: int, delay_seconds: int):
    await asyncio.sleep(delay_seconds)
    try:
        delete_message(chat_id, message_id)
    except Exception as e:
        print("DELETE LATER ERROR:", str(e), flush=True)


def language_is_french(language_code: str | None) -> bool:
    if language_code is None:
        return True
    return language_code.lower().startswith("fr")


def handle_private_message(db, message: dict):
    from_user = message.get("from", {})
    user_id = from_user.get("id")
    username = from_user.get("username")
    first_name = from_user.get("first_name")
    language_code = from_user.get("language_code")
    chat_id = message["chat"]["id"]
    text = message.get("text", "")

    if not user_id:
        return

    # enregistre l'utilisateur privé
    upsert_subscriber(db, user_id, username, first_name, language_code)

    if text == "/start":
        if is_admin(db, user_id):
            send_message(chat_id, "👑 Panneau admin", reply_markup=admin_menu())
        else:
            db_config = ensure_single_group_config(db)
            if db_config.invite_link:
                send_message(
                    chat_id,
                    f"✅ Tu es bien enregistré.\n\nVoici le lien actuel du groupe :\n{db_config.invite_link}"
                )
            else:
                send_message(
                    chat_id,
                    "✅ Tu es bien enregistré.\nLe lien du groupe n'est pas encore défini."
                )
        return

    if not is_admin(db, user_id):
        return

    pending = PENDING_ACTIONS.get(user_id)

    if pending == "await_invite_link":
        set_invite_link(db, text.strip())
        PENDING_ACTIONS.pop(user_id, None)
        send_message(chat_id, "✅ Lien du groupe mis à jour.", reply_markup=admin_menu())
        return

    if pending == "await_broadcast":
        config = ensure_single_group_config(db)
        if not config.group_chat_id:
            send_message(chat_id, "❌ Aucun groupe défini.", reply_markup=admin_menu())
            PENDING_ACTIONS.pop(user_id, None)
            return

        send_message(int(config.group_chat_id), text)
        create_broadcast_log(db, user_id, int(config.group_chat_id), text)
        PENDING_ACTIONS.pop(user_id, None)
        send_message(chat_id, "✅ Broadcast envoyé dans le groupe.", reply_markup=admin_menu())
        return

    if text == "/admin":
        send_message(chat_id, "👑 Panneau admin", reply_markup=admin_menu())


def handle_group_message(db, message: dict):
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    chat_title = chat.get("title")
    message_id = message.get("message_id")

    if not chat_id:
        return

    # fixe le groupe surveillé automatiquement au premier usage
    set_group(db, chat_id, chat_title)

    # suppression des notifications de service join/leave
    if "new_chat_members" in message or "left_chat_member" in message:
        try:
            delete_message(chat_id, message_id)
        except Exception as e:
            print("DELETE SERVICE MESSAGE ERROR:", str(e), flush=True)

    # nouveaux membres
    if "new_chat_members" in message:
        invite_link_obj = message.get("invite_link")
        invite_link_value = invite_link_obj.get("invite_link") if isinstance(invite_link_obj, dict) else None

        for user in message["new_chat_members"]:
            user_id = user.get("id")
            username = user.get("username")
            first_name = user.get("first_name")
            language_code = user.get("language_code")

            if not user_id:
                continue

            # filtre langue v1
            if not language_is_french(language_code):
                try:
                    ban_chat_member(chat_id, user_id)
                except Exception as e:
                    print("BAN ERROR:", str(e), flush=True)
                continue

            _, config = add_join_event(
                db=db,
                user_id=user_id,
                username=username,
                first_name=first_name,
                language_code=language_code,
                invite_link=invite_link_value,
            )

            if should_send_promo(config):
                if PROMO_PHOTO:
                    r = send_photo(
                        chat_id=chat_id,
                        photo=PROMO_PHOTO,
                        caption=PROMO_TEXT,
                        reply_markup=promo_buttons(config.invite_link, BOT_USERNAME),
                    )
                else:
                    r = send_message(
                        chat_id=chat_id,
                        text=PROMO_TEXT,
                        reply_markup=promo_buttons(config.invite_link, BOT_USERNAME),
                    )

                try:
                    data = r.json()
                    if data.get("ok"):
                        promo_message_id = data["result"]["message_id"]
                        asyncio.create_task(
                            delete_later(
                                chat_id=chat_id,
                                message_id=promo_message_id,
                                delay_seconds=config.promo_message_delete_after,
                            )
                        )
                except Exception as e:
                    print("PROMO SEND ERROR:", str(e), flush=True)


def handle_callback(db, callback_query: dict):
    callback_id = callback_query["id"]
    data = callback_query["data"]
    from_user = callback_query.get("from", {})
    user_id = from_user.get("id")
    chat_id = callback_query["message"]["chat"]["id"]
    message_id = callback_query["message"]["message_id"]

    if not user_id or not is_admin(db, user_id):
        answer_callback_query(callback_id, "Accès refusé")
        return

    if data == "show_stats":
        answer_callback_query(callback_id, "Statistiques")
        edit_message_text(chat_id, message_id, build_stats_text(db), reply_markup=admin_menu())
        return

    if data == "update_invite_link":
        PENDING_ACTIONS[user_id] = "await_invite_link"
        answer_callback_query(callback_id, "En attente du lien")
        edit_message_text(
            chat_id,
            message_id,
            "🔗 Envoie maintenant le nouveau lien du groupe en message privé.",
            reply_markup=admin_menu(),
        )
        return

    if data == "broadcast_group":
        PENDING_ACTIONS[user_id] = "await_broadcast"
        answer_callback_query(callback_id, "En attente du message")
        edit_message_text(
            chat_id,
            message_id,
            "📢 Envoie maintenant le texte du broadcast en message privé.",
            reply_markup=admin_menu(),
        )
        return


@app.post("/webhook")
async def webhook(request: Request):
    if not BOT_TOKEN:
        return {"ok": False, "error": "BOT_TOKEN missing"}

    update = await request.json()
    db = SessionLocal()

    try:
        if "message" in update:
            message = update["message"]
            chat_type = message.get("chat", {}).get("type")

            if chat_type == "private":
                handle_private_message(db, message)
            elif chat_type in ["group", "supergroup"]:
                handle_group_message(db, message)

        elif "callback_query" in update:
            handle_callback(db, update["callback_query"])

    except Exception as e:
        print("WEBHOOK ERROR:", str(e), flush=True)
    finally:
        db.close()

    return {"ok": True}
