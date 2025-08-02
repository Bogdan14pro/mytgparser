import os
import json
import asyncio
import logging
from typing import Callable, Any, Optional, Union

import config
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import User
from aiogram import Bot
from aiogram.fsm.context import FSMContext

logger = logging.getLogger(__name__)


class Account:
    def __init__(
            self,
            phone: str,
            api_id: int,
            api_hash: str,
            session_string: Optional[str] = None,
            user_id: Optional[int] = None,
            username: Optional[str] = None,
            first_name: Optional[str] = None,
            last_name: Optional[str] = None
    ):
        self.phone = phone
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_string = session_string
        self.user_id = user_id
        self.username = username
        self.first_name = first_name
        self.last_name = last_name
        self.is_busy = False
        self.lock = asyncio.Lock()

    def __repr__(self):
        return (f"Account(phone='{self.phone}', user_id={self.user_id}, "
                f"session_string={'<set>' if self.session_string else '<None>'}, "
                f"is_busy={self.is_busy})")

    def client(self) -> TelegramClient:
        if self.session_string:
            return TelegramClient(StringSession(self.session_string), self.api_id, self.api_hash)
        else:
            logger.warning(
                f"Creating TelegramClient for {self.phone} without session_string. Authorization will be required.")
            return TelegramClient(None, self.api_id, self.api_hash)

    async def is_authorized(self) -> bool:
        if not self.session_string:
            logger.debug(f"Account {self.phone} is not authorized: no session_string.")
            return False
        client = self.client()
        try:
            await client.connect()
            is_auth = await client.is_user_authorized()
            logger.debug(f"Account {self.phone} authorization status: {is_auth}")
            return is_auth
        except Exception as e:
            logger.warning(f"Ошибка проверки авторизации для {self.phone}: {e}")
            return False
        finally:
            if client and client.is_connected():
                await client.disconnect()


class AccountManager:
    def __init__(self):
        self.accounts: list[Account] = []
        self._load()

    def _load(self):
        if os.path.exists(config.ACCOUNTS_FILE):
            try:
                with open(config.ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.accounts = []
                    for acc_data in data:
                        logger.debug(f"Attempting to load account data: {acc_data}")
                        if "session_string" not in acc_data or not acc_data.get("session_string"):
                            logger.warning(
                                f"Loaded account data for {acc_data.get('phone', 'unknown')} has no valid session_string.")
                        self.accounts.append(Account(
                            phone=acc_data["phone"],
                            api_id=acc_data["api_id"],
                            api_hash=acc_data["api_hash"],
                            session_string=acc_data.get("session_string"),
                            user_id=acc_data.get("user_id"),
                            username=acc_data.get("username"),
                            first_name=acc_data.get("first_name"),
                            last_name=acc_data.get("last_name")
                        ))
                logger.info(f"Загружено {len(self.accounts)} аккаунтов.")
                if self.accounts:
                    logger.debug(f"Loaded accounts list: {self.accounts}")
            except json.JSONDecodeError as e:
                logger.error(
                    f"Ошибка загрузки аккаунтов (JSONDecodeError): {e}. Файл accounts.json может быть поврежден. Создаю новый пустой список аккаунтов.")
                self.accounts = []
            except Exception as e:
                logger.error(f"Неизвестная ошибка при загрузке аккаунтов: {e}")
                self.accounts = []

    def _save(self):
        try:
            with open(config.ACCOUNTS_FILE, "w", encoding="utf-8") as f:
                json.dump([
                    {
                        "phone": a.phone,
                        "api_id": a.api_id,
                        "api_hash": a.api_hash,
                        "session_string": a.session_string,
                        "user_id": a.user_id,
                        "username": a.username,
                        "first_name": a.first_name,
                        "last_name": a.last_name
                    }
                    for a in self.accounts
                ], f, indent=4, ensure_ascii=False)
            logger.info(f"Saved {len(self.accounts)} accounts to {config.ACCOUNTS_FILE}")
        except Exception as e:
            logger.error(f"Ошибка сохранения аккаунтов: {e}")

    async def add_account(
            self,
            phone: str,
            api_id: int,
            api_hash: str,
            bot_instance: Bot,
            chat_id: int,
            fsm_state: FSMContext,
            code_callback: Optional[Callable[[int, FSMContext, Bot], Any]] = None,
            password_callback: Optional[Callable[[int, FSMContext, Bot], Any]] = None
    ) -> Account:
        for acc in self.accounts:
            if acc.phone == phone:
                if await acc.is_authorized():
                    raise ValueError(f"Аккаунт {phone} уже добавлен и авторизован.")
                else:
                    logger.warning(f"Аккаунт {phone} существует, но не авторизован. Попробуем переавторизовать.")
                    self.accounts.remove(acc)
                    self._save()
                    break

        client = TelegramClient(StringSession(), api_id, api_hash)

        if code_callback:
            client.code_callback = lambda: code_callback(chat_id, fsm_state, bot_instance)
        if password_callback:
            client.password_callback = lambda: password_callback(chat_id, fsm_state, bot_instance)

        try:
            logger.info(f"Попытка авторизации аккаунта {phone}...")
            await client.start(phone=phone)

            logger.info(f"Авторизация аккаунта {phone} завершена.")
            me: User = await client.get_me()
            session_string = client.session.save()
            logger.debug(f"Session string obtained for {phone}: {'<set>' if session_string else '<None>'}")

            a = Account(
                phone=phone,
                api_id=api_id,
                api_hash=api_hash,
                session_string=session_string,
                user_id=me.id,
                username=me.username,
                first_name=me.first_name,
                last_name=me.last_name
            )
            self.accounts.append(a)
            self._save()
            logger.info(f"Account {phone} successfully added and saved.")
            return a
        except Exception as e:
            logger.error(f"Ошибка при авторизации аккаунта {phone}: {e}", exc_info=True)
            raise
        finally:
            if client and client.is_connected():
                await client.disconnect()

    def delete(self, idx: int):
        if 0 <= idx < len(self.accounts):
            phone_to_delete = self.accounts[idx].phone
            del self.accounts[idx]
            self._save()
            logger.info(f"Account {phone_to_delete} deleted.")
        else:
            raise IndexError("Неверный индекс аккаунта.")

    async def acquire(self, account: Account) -> TelegramClient:
        async with account.lock:
            if account.is_busy:
                raise RuntimeError(f"Аккаунт {account.phone} уже занят.")
            client = account.client()
            try:
                await client.connect()
                if not await client.is_user_authorized():
                    await client.disconnect()
                    raise RuntimeError(f"Аккаунт {account.phone} не авторизован или сессия недействительна.")
                account.is_busy = True
                logger.debug(f"Account {account.phone} acquired.")
                return client
            except Exception as e:
                if client and client.is_connected():
                    await client.disconnect()
                logger.error(f"Ошибка при получении клиента для аккаунта {account.phone}: {e}")
                raise RuntimeError(f"Не удалось получить клиента для {account.phone}: {e}")

    async def release(self, account: Account):
        async with account.lock:
            if account.is_busy:
                account.is_busy = False
                logger.debug(f"Account {account.phone} released.")
            else:
                logger.warning(f"Попытка освободить незанятый аккаунт {account.phone}. Возможно, ошибка логики.")

    async def get_free_account(self) -> Optional[Account]:
        for account in self.accounts:
            async with account.lock:
                if not account.is_busy:
                    if await account.is_authorized():
                        return account
                    else:
                        logger.warning(f"Аккаунт {account.phone} не авторизован и будет пропущен.")
        return None


account_mgr = AccountManager()
