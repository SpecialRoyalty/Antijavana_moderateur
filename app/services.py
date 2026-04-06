from datetime import datetime
from sqlalchemy.orm import Session
from .models import Admin, Subscriber, GroupConfig, JoinEvent, BroadcastLog


def ensure_single_group_config(db: Session) -> GroupConfig:
    config = db.query(GroupConfig).first()
    if not config:
        config = GroupConfig()
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


def ensure_admin(db: Session, user_id: int, username: str | None = None):
    admin = db.query(Admin).filter(Admin.user_id == user_id).first()
    if not admin:
        admin = Admin(user_id=user_id, username=username, is_active=True)
        db.add(admin)
        db.commit()
        db.refresh(admin)
    return admin


def is_admin(db: Session, user_id: int) -> bool:
    return db.query(Admin).filter(Admin.user_id == user_id, Admin.is_active == True).first() is not None


def upsert_subscriber(
    db: Session,
    user_id: int,
    username: str | None,
    first_name: str | None,
    language_code: str | None,
):
    subscriber = db.query(Subscriber).filter(Subscriber.user_id == user_id).first()
    if not subscriber:
        subscriber = Subscriber(
            user_id=user_id,
            username=username,
            first_name=first_name,
            language_code=language_code,
        )
        db.add(subscriber)
    else:
        subscriber.username = username
        subscriber.first_name = first_name
        subscriber.language_code = language_code

    db.commit()
    db.refresh(subscriber)
    return subscriber


def set_group(db: Session, chat_id: int, title: str | None):
    config = ensure_single_group_config(db)
    config.group_chat_id = chat_id
    config.group_title = title
    config.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(config)
    return config


def set_invite_link(db: Session, invite_link: str):
    config = ensure_single_group_config(db)
    config.invite_link = invite_link
    config.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(config)
    return config


def add_join_event(
    db: Session,
    user_id: int,
    username: str | None,
    first_name: str | None,
    language_code: str | None,
    invite_link: str | None,
):
    event = JoinEvent(
        user_id=user_id,
        username=username,
        first_name=first_name,
        language_code=language_code,
        invite_link=invite_link,
    )
    db.add(event)

    config = ensure_single_group_config(db)
    config.join_counter += 1
    config.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(event)
    db.refresh(config)
    return event, config


def should_send_promo(config: GroupConfig) -> bool:
    if config.join_counter <= 0:
        return False
    return config.join_counter % config.welcome_every == 0


def create_broadcast_log(db: Session, admin_user_id: int, group_chat_id: int, text: str):
    log = BroadcastLog(
        admin_user_id=admin_user_id,
        group_chat_id=group_chat_id,
        text=text,
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def build_stats_text(db: Session) -> str:
    config = ensure_single_group_config(db)
    subscribers = db.query(Subscriber).count()
    joins = db.query(JoinEvent).count()

    group_name = config.group_title or config.group_chat_id or "Non défini"
    invite_link = config.invite_link or "Non défini"

    return (
        "📊 Statistiques\n\n"
        f"Groupe : {group_name}\n"
        f"Lien actuel : {invite_link}\n"
        f"Total joins comptés : {joins}\n"
        f"Compteur actuel : {config.join_counter}\n"
        f"Message promo tous les : {config.welcome_every}\n"
        f"Suppression promo après : {config.promo_message_delete_after}s\n"
        f"Abonnés bot privés : {subscribers}"
    )
