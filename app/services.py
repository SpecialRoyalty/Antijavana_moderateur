from datetime import datetime
from sqlalchemy.orm import Session
from .models import Admin, Subscriber, GroupConfig, JoinEvent, PromoLog, BroadcastLog


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


def upsert_subscriber(db: Session, user_id: int, username: str | None, first_name: str | None, language_code: str | None):
    sub = db.query(Subscriber).filter(Subscriber.user_id == user_id).first()
    if not sub:
        sub = Subscriber(
            user_id=user_id,
            username=username,
            first_name=first_name,
            language_code=language_code,
        )
        db.add(sub)
    else:
        sub.username = username
        sub.first_name = first_name
        sub.language_code = language_code

    db.commit()
    db.refresh(sub)
    return sub


def get_all_subscribers(db: Session):
    return db.query(Subscriber).order_by(Subscriber.id.asc()).all()


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
    invite_link_used: str | None,
):
    config = ensure_single_group_config(db)

    event = JoinEvent(
        user_id=user_id,
        username=username,
        first_name=first_name,
        language_code=language_code,
        invite_link_used=invite_link_used,
    )
    db.add(event)

    config.join_counter += 1
    config.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(event)
    db.refresh(config)
    return event, config


def get_join_count(db: Session) -> int:
    config = ensure_single_group_config(db)
    return config.join_counter


def should_send_first_promo(db: Session) -> bool:
    return db.query(PromoLog).filter(PromoLog.reason == "first_join").count() == 0


def should_send_every_20_promo(db: Session) -> bool:
    count = get_join_count(db)
    return count > 0 and count % 20 == 0


def log_promo(db: Session, group_chat_id: int, reason: str, promo_message_id: int | None):
    row = PromoLog(
        group_chat_id=group_chat_id,
        reason=reason,
        promo_message_id=promo_message_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def create_broadcast_log(db: Session, admin_user_id: int, group_chat_id: int, text: str):
    row = BroadcastLog(
        admin_user_id=admin_user_id,
        group_chat_id=group_chat_id,
        text=text,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def build_stats_text(db: Session) -> str:
    config = ensure_single_group_config(db)
    subs = db.query(Subscriber).count()
    joins = db.query(JoinEvent).count()

    return (
        "📊 Statistiques\n\n"
        f"Groupe : {config.group_title or config.group_chat_id or 'Non défini'}\n"
        f"Lien actuel : {config.invite_link or 'Non défini'}\n"
        f"Total joins : {joins}\n"
        f"Compteur joins : {config.join_counter}\n"
        f"Abonnés bot : {subs}"
    )
