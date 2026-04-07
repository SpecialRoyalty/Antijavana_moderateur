from datetime import datetime
from sqlalchemy import Column, Integer, BigInteger, String, DateTime, Boolean, Text
from .db import Base


class Admin(Base):
    __tablename__ = "admins"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, unique=True, index=True)
    username = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Subscriber(Base):
    __tablename__ = "subscribers"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, unique=True, index=True)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    language_code = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class GroupConfig(Base):
    __tablename__ = "group_config"

    id = Column(Integer, primary_key=True)
    group_chat_id = Column(BigInteger, nullable=True)
    group_title = Column(String, nullable=True)
    invite_link = Column(Text, nullable=True)
    join_counter = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow)


class JoinEvent(Base):
    __tablename__ = "join_events"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    language_code = Column(String, nullable=True)
    invite_link_used = Column(Text, nullable=True)
    joined_at = Column(DateTime, default=datetime.utcnow)


class PromoLog(Base):
    __tablename__ = "promo_logs"

    id = Column(Integer, primary_key=True)
    group_chat_id = Column(BigInteger)
    reason = Column(String)
    promo_message_id = Column(BigInteger, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class BroadcastLog(Base):
    __tablename__ = "broadcast_logs"

    id = Column(Integer, primary_key=True)
    admin_user_id = Column(BigInteger)
    group_chat_id = Column(BigInteger)
    text = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
