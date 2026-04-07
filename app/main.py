import os
import requests
from fastapi import FastAPI, Request
from .db import Base, engine

app = FastAPI()

BOT_TOKEN = os.getenv("BOT_TOKEN")
BASE_URL = os.getenv("BASE_URL")
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else None


@app.on_event("startup")
def startup():
    print("STARTUP OK", flush=True)
    Base.metadata.create_all(bind=engine)
    print("TABLES CREATED", flush=True)


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


def send_message(chat_id: int, text: str):
    return requests.post(
        f"{API_URL}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=30
    )


@app.post("/webhook")
async def webhook(request: Request):
    update = await request.json()
    print("UPDATE RECUE:", update, flush=True)

    if "message" in update:
        message = update["message"]
        chat_id = message["chat"]["id"]
        text = message.get("text", "")

        if text == "/start":
            send_message(chat_id, "✅ /start reçu")

    return {"ok": True}
