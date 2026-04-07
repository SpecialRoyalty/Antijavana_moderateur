from urllib.parse import quote


def inline_keyboard(rows):
    return {"inline_keyboard": rows}

def admin_menu():
    return inline_keyboard([
        [{"text": "📊 Voir les stats", "callback_data": "show_stats"}],
        [{"text": "🔗 Mettre à jour le lien", "callback_data": "update_link"}],
        [{"text": "📢 Broadcast groupe", "callback_data": "broadcast_group"}],
        [{"text": "📨 Envoyer le lien à tous", "callback_data": "push_link_all"}],
        [{"text": "🚀 Publish", "callback_data": "publish_promo"}],
    ])




def user_menu():
    return inline_keyboard([
        [{"text": "🔗 Obtenir le lien", "callback_data": "get_link"}],
    ])


def build_share_url(invite_link: str | None) -> str:
    """
    Ouvre la fenêtre Telegram de partage vers contacts/groupes/messages enregistrés.
    """
    if not invite_link:
        invite_link = "https://t.me"

    text = "Rejoins ce groupe :"
    return f"https://t.me/share/url?url={quote(invite_link)}&text={quote(text)}"


def promo_buttons(invite_link: str | None, bot_username: str | None):
    share_url = build_share_url(invite_link)
    bot_url = f"https://t.me/{bot_username}?start=backup" if bot_username else "https://t.me"

    return inline_keyboard([
        [{"text": "🔗 Partager", "url": share_url}],
        [{"text": "🤖 Je m’enregistre", "url": bot_url}],
    ])
