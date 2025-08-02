import re
import uuid
import time
import config
from functools import wraps
from aiogram.fsm.state import State, StatesGroup
from typing import Optional, List
from aiogram import types
from dataclasses import dataclass, field
from telethon import TelegramClient, types as telethon_types, errors as telethon_errors
import asyncio

class AddAccountStates(StatesGroup):
    phone = State()
    api = State()
    code = State()
    password = State()
    delete_confirm = State()

class ReauthAccountStates(StatesGroup):
    select = State()
    code = State()
    password = State()

class InviteSettingsStates(StatesGroup):
    channel = State()

class ScrapingStates(StatesGroup):
    step1 = State()
    step2 = State()
    step3 = State()
    step4 = State()

class SeparateInviteStates(StatesGroup):
    user_limit = State()

@dataclass
class UserStub:
    user_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None

@dataclass
class Task:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    admin_id: int = 0
    target_chat: Optional[str] = None
    chat_id: Optional[int] = None
    chat_title: Optional[str] = None
    message_limit: int = 0
    user_limit: int = 0
    invite_enabled: bool = False
    account_phone: Optional[str] = None
    status: str = "pending"
    created_at: float = field(default_factory=time.monotonic)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    collected_users: List[UserStub] = field(default_factory=list)
    invited_users: List[UserStub] = field(default_factory=list)
    failed_privacy: int = 0
    already_participants: int = 0
    failed_other: int = 0
    invite_status: Optional[str] = None
    already_participants_list: List[UserStub] = field(default_factory=list)

    def duration(self) -> float:
        if self.started_at and self.finished_at:
            return self.finished_at - self.started_at
        return 0.0

def validate_phone_number(phone: str) -> bool:
    return re.fullmatch(r'^\+\d{10,15}$', phone) is not None

def validate_api_id(api_id: str) -> bool:
    return api_id.isdigit()

def validate_api_hash(api_hash: str) -> bool:
    return re.fullmatch(r'^[0-9a-fA-F]{32}$', api_hash) is not None

async def validate_target(target: str, client: TelegramClient) -> bool:
    try:
        entity = await client.get_entity(target)
        return isinstance(entity, (telethon_types.Channel, telethon_types.Chat))
    except (ValueError, telethon_errors.rpcerrorlist.UsernameNotOccupiedError,
            telethon_errors.rpcerrorlist.ChannelInvalidError,
            telethon_errors.rpcerrorlist.ChatIdInvalidError,
            telethon_errors.rpcerrorlist.PeerIdInvalidError):
        return False
    except Exception:
        return False

def validate_positive_int(value: str, maximum: Optional[int] = None) -> bool:
    if not value.isdigit():
        return False
    v = int(value)
    if maximum is not None:
        return 1 <= v <= maximum
    return v >= 1

def check_is_admin(handler):
    @wraps(handler)
    async def wrapper(event, *args, **kwargs):
        user_id = event.from_user.id
        if user_id not in config.ADMIN_IDS:
            if isinstance(event, types.CallbackQuery):
                await event.answer("У вас нет прав для выполнения этой команды.", show_alert=True)
            elif isinstance(event, types.Message):
                await event.answer("У вас нет прав для выполнения этой команды.")
            return
        return await handler(event, *args, **kwargs)
    return wrapper
