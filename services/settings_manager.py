import json
import os
import asyncio
import logging
from typing import Optional
from telethon import TelegramClient, errors
from telethon.tl.functions.channels import GetFullChannelRequest

import config
from services.account_manager import account_mgr

logger = logging.getLogger(__name__)


class SettingsManager:
    def __init__(self):
        self._lock = asyncio.Lock()
        self.settings = {
            "invite_channel": None,
            "auto_invite": False
        }
        self._load()

    def _load(self):
        if os.path.exists(config.SETTINGS_FILE):
            try:
                with open(config.SETTINGS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for key in ("invite_channel", "auto_invite"):
                    if key in data:
                        self.settings[key] = data[key]
                logger.info(f"Settings loaded from {config.SETTINGS_FILE}")
            except Exception as e:
                logger.error(
                    f"Ошибка загрузки настроек из {config.SETTINGS_FILE}: {e}. Используем настройки по умолчанию.")
                self.settings = {"invite_channel": None, "auto_invite": False}
                self._save()
        else:
            logger.info(f"Settings file {config.SETTINGS_FILE} not found. Using default settings.")
            self._save()

    def _save(self):
        try:
            with open(config.SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=4)
            logger.info(f"Settings saved to {config.SETTINGS_FILE}")
        except Exception as e:
            logger.error(f"Ошибка сохранения настроек в {config.SETTINGS_FILE}: {e}")

    async def set_channel(self, channel_input: str) -> str:
        if not account_mgr.accounts:
            raise ValueError("Нет подключенных аккаунтов для проверки канала.")

        test_account = None
        client = None
        for acc in account_mgr.accounts:
            try:
                client = await account_mgr.acquire(acc)
                test_account = acc
                break
            except Exception as e:
                logger.warning(f"Не удалось получить клиент для аккаунта {acc.phone} для проверки канала: {e}")
                if client and client.is_connected():
                    await client.disconnect()
                if acc.is_busy:
                    await account_mgr.release(acc)
                continue

        if not test_account or not client:
            raise ValueError("Нет доступных авторизованных аккаунтов для проверки канала.")

        try:
            entity = await client.get_entity(channel_input)

            if not isinstance(entity, (errors.rpcerrorlist.ChannelInvalidError,
                                       errors.rpcerrorlist.PeerIdInvalidError)):
                try:
                    full_channel = await client(GetFullChannelRequest(entity))
                    self.settings["invite_channel"] = channel_input
                    self._save()
                    return channel_input
                except Exception as e:
                    logger.error(f"Error getting full channel info for {channel_input}: {e}")
                    raise ValueError(
                        f"Не удалось получить информацию о канале '{channel_input}'. Возможно, бот не является администратором, или ссылка неверна. {e}")
            else:
                raise ValueError("Это не канал или группа. Пожалуйста, введите ссылку на канал или группу.")

        except errors.rpcerrorlist.UsernameInvalidError:
            raise ValueError("Неверный юзернейм канала/группы.")
        except errors.rpcerrorlist.ChannelPrivateError:
            raise ValueError("Канал является приватным, бот не может в него войти.")
        except errors.rpcerrorlist.ChatIdInvalidError:
            raise ValueError("Неверный ID чата/группы.")
        except errors.rpcerrorlist.PeerIdInvalidError:
            raise ValueError("Неверный формат ссылки/юзернейма или объект не найден.")
        except errors.rpcerrorlist.AuthKeyUnregisteredError:
            raise ValueError("Аккаунт, используемый для проверки, не авторизован. Переавторизуйте его.")
        except Exception as e:
            logger.exception(f"Неизвестная ошибка при проверке канала {channel_input}")
            raise ValueError(f"Неизвестная ошибка при проверке канала: {e}")
        finally:
            if client and client.is_connected():
                await client.disconnect()
            if test_account:
                await account_mgr.release(test_account)

    def get_channel(self) -> Optional[str]:
        return self.settings.get("invite_channel")

    def toggle_invite(self) -> bool:
        self.settings["auto_invite"] = not self.settings.get("auto_invite", False)
        self._save()
        return self.settings["auto_invite"]

    def is_auto_invite(self) -> bool:
        return bool(self.settings.get("auto_invite", False))


settings_mgr = SettingsManager()
