def inline_keyboard(rows):
    return {"inline_keyboard": rows}


def admin_menu():
    return inline_keyboard([
        [{"text": "📊 Voir les stats", "callback_data": "show_stats"}],
        [{"text": "🔗 Mettre à jour le lien du groupe", "callback_data": "update_invite_link"}],
        [{"text": "📢 Broadcast dans le groupe", "callback_data": "broadcast_group"}],
    ])


def promo_buttons(invite_link: str | None, bot_username: str | None):
    share_url = invite_link or "https://t.me"
    bot_url = f"https://t.me/{bot_username}?start=backup" if bot_username else "https://t.me"

    return inline_keyboard([
        [{"text": "🔗 Partager le groupe", "url": share_url}],
        [{"text": "🤖 Recevoir le lien de secours", "url": bot_url}],
    ])
