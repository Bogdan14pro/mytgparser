import logging
from aiogram import types, Dispatcher, Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters.text import Text
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    FloodWaitError,
    ApiIdInvalidError,
    AuthRestartError,
    PasswordHashInvalidError,
    RPCError
)
from telethon.tl.types import User
from typing import Tuple, Optional
import asyncio

import config
from services.account_manager import account_mgr
from models import AddAccountStates, \
    check_is_admin, validate_phone_number, validate_api_id, validate_api_hash # Обновлено: добавлены валидаторы

logger = logging.getLogger(__name__)

#  глобал Future для каллбэков
telethon_futures: dict[int, asyncio.Future] = {}


async def get_main_menu_content(user_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    """
    Возвращает текст и клавиатуру главного админского меню.
    """
    kb_rows = [
        [InlineKeyboardButton(text="Управление аккаунтами", callback_data="m_acc")],
        [InlineKeyboardButton(text="Начать сбор", callback_data="m_start_scraping")],
        [InlineKeyboardButton(text="Начать приглашение", callback_data="m_start_inviting")],
        [InlineKeyboardButton(text="Список задач", callback_data="m_tasks")],
        [InlineKeyboardButton(text="Настройки приглашений", callback_data="m_settings")]
    ]
    kb_rows.append([InlineKeyboardButton(text="❌ Закрыть меню", callback_data="close_menu")])

    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    text = (
        f"<b>Добро пожаловать в админ-панель, {user_id}!</b>\n\n"
        "Выберите действие:"
    )
    return text, kb

async def get_accounts_menu_content() -> Tuple[str, InlineKeyboardMarkup]:
    """
    Возвращает текст и клавиатуру для меню управления аккаунтами.
    """
    accounts = account_mgr.accounts
    text = "<b>Управление аккаунтами:</b>\n\n"
    if not accounts:
        text += "Нет подключенных аккаунтов.\n"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить аккаунт", callback_data="add_acc")],
            [InlineKeyboardButton(text="◀️ Назад в главное меню", callback_data="menu")]
        ])
    else:
        for i, acc in enumerate(accounts):
            status = "✅"
            try:
                # Проверка
                if not acc.is_busy and not await acc.is_authorized():
                    status = "❌"
            except Exception as e:
                logger.warning(f"Ошибка проверки статуса аккаунта {acc.phone}: {e}")
                status = "⚠️" # Не удалось проверить статус
            text += f"{i + 1}. {status} <code>{acc.phone}</code> (ID: <code>{acc.user_id or 'N/A'}</code>)\n"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить аккаунт", callback_data="add_acc")],
            [InlineKeyboardButton(text="🗑️ Удалить аккаунт", callback_data="del_acc")],
            [InlineKeyboardButton(text="Список аккаунтов", callback_data="list_acc")],
            [InlineKeyboardButton(text="◀️ Назад в главное меню", callback_data="menu")]
        ])
    return text, kb

@check_is_admin
async def cmd_menu(message: types.Message):
    """Хендлер для команды /start или /menu."""
    text, kb = await get_main_menu_content(message.from_user.id)
    await message.answer(text, reply_markup=kb)

@check_is_admin
async def go_to_main_menu(c: types.CallbackQuery, state: FSMContext):
    """Хендлер для возврата в главное меню."""
    await state.clear()
    text, kb = await get_main_menu_content(c.from_user.id)
    await c.message.edit_text(text, reply_markup=kb)
    await c.answer()

@check_is_admin
async def close_menu(c: types.CallbackQuery):
    """Хендлер для закрытия меню."""
    await c.message.delete()
    await c.answer()


@check_is_admin
async def cancel_all(c: types.CallbackQuery, state: FSMContext):
    """Хендлер для отмены любого текущего FSM-состояния."""
    user_id = c.from_user.id
    if user_id in telethon_futures and not telethon_futures[user_id].done():
        telethon_futures[user_id].set_result(None)
    await state.clear()
    await c.message.answer("❌ Действие отменено.")
    await go_to_main_menu(c, state)

@check_is_admin
async def menu_accounts(c: types.CallbackQuery):
    """Хендлер для отображения меню управления аккаунтами."""
    text, kb = await get_accounts_menu_content()
    await c.message.edit_text(text, reply_markup=kb)
    await c.answer()


@check_is_admin
async def add_acc_start(c: types.CallbackQuery, state: FSMContext):
    """Начало процесса добавления аккаунта: запрос номера телефона."""
    await c.message.answer(
        "Введите номер телефона аккаунта Telegram (в формате +79XXXXXXXXX):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
        ])
    )
    await state.set_state(AddAccountStates.phone)
    await c.answer()

@check_is_admin
async def add_acc_phone(message: types.Message, state: FSMContext):
    """Обработка введенного номера телефона."""
    phone = message.text.strip()
    if not validate_phone_number(phone):
        await message.answer("Неверный формат номера телефона. Пожалуйста, введите в формате +79XXXXXXXXX:")
        return

    await state.update_data(phone=phone)
    await message.answer(
        "Введите API ID (число):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
        ])
    )
    await state.set_state(AddAccountStates.api)

@check_is_admin
async def add_acc_api(message: types.Message, state: FSMContext, bot: Bot):
    """Обработка введенного API ID и попытка авторизации."""
    api_id_str = message.text.strip()
    if not validate_api_id(api_id_str):
        await message.answer("API ID должен быть числом. Пожалуйста, введите корректный API ID:")
        return

    await state.update_data(api_id=int(api_id_str))

    data = await state.get_data()
    phone = data['phone']
    api_id = data['api_id']

    await message.answer("Введите API Hash (32 символа):",
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                             [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
                         ]))
    await state.set_state(AddAccountStates.password)

@check_is_admin
async def add_acc_api_hash(message: types.Message, state: FSMContext, bot: Bot):
    """Обработка введенного API Hash и попытка авторизации."""
    api_hash = message.text.strip()
    if not validate_api_hash(api_hash):
        await message.answer("API Hash должен состоять из 32 шестнадцатеричных символов. Пожалуйста, введите корректный API Hash:")
        return

    await state.update_data(api_hash=api_hash)

    data = await state.get_data()
    phone = data['phone']
    api_id = data['api_id']
    api_hash = data['api_hash']

    user_id = message.from_user.id
    telethon_futures[user_id] = asyncio.Future()

    processing_message = await message.answer("Попытка авторизации аккаунта... Ожидайте запроса кода или пароля.")

    try:
        # ряльна
        account = await account_mgr.add_account(
            phone=phone,
            api_id=api_id,
            api_hash=api_hash,
            bot_instance=bot,
            chat_id=user_id,
            fsm_state=state
        )
        await processing_message.edit_text(f"✅ Аккаунт <code>{account.phone}</code> успешно добавлен!")
    except PhoneCodeExpiredError:
        await processing_message.edit_text("❌ Срок действия кода истек. Пожалуйста, попробуйте добавить аккаунт заново.")
    except PhoneCodeInvalidError:
        await processing_message.edit_text("❌ Введен неверный код. Пожалуйста, попробуйте добавить аккаунт заново.")
    except ApiIdInvalidError:
        await processing_message.edit_text("❌ Неверный API ID или API Hash. Проверьте данные и попробуйте снова.")
    except SessionPasswordNeededError:
        await processing_message.edit_text("❌ Требуется двухфакторная аутентификация (2FA), но пароль не был предоставлен или неверный. Пожалуйста, попробуйте добавить аккаунт заново.")
    except PasswordHashInvalidError:
        await processing_message.edit_text("❌ Введен неверный 2FA-пароль. Пожалуйста, попробуйте добавить аккаунт заново.")
    except FloodWaitError as e:
        await processing_message.edit_text(f"❌ Слишком много попыток. Пожалуйста, подождите {e.seconds} секунд и попробуйте снова.")
    except AuthRestartError:
        await processing_message.edit_text("❌ Процесс авторизации был перезапущен Telegram. Пожалуйста, попробуйте добавить аккаунт заново.")
    except asyncio.TimeoutError:
        await processing_message.edit_text("❌ Время ожидания ввода истекло. Пожалуйста, попробуйте добавить аккаунт заново.")
    except ValueError as e:
        await processing_message.edit_text(f"❌ Ошибка добавления аккаунта: {e}")
    except Exception as e:
        logger.error(f"Непредвиденная ошибка при добавлении аккаунта.", exc_info=True)
        await processing_message.edit_text(f"❌ Непредвиденная ошибка при добавлении аккаунта. Пожалуйста, проверьте логи: {e}")
    finally:
        await state.clear()
        if user_id in telethon_futures:
            del telethon_futures[user_id]
        text, kb = await get_accounts_menu_content()
        await message.answer(text, reply_markup=kb)


@check_is_admin
async def add_acc_code(message: types.Message, state: FSMContext):
    """Хендлер для получения кода авторизации Telethon."""
    user_id = message.from_user.id
    if user_id in telethon_futures and not telethon_futures[user_id].done():
        telethon_futures[user_id].set_result(message.text.strip())
        await state.set_state(None)
    else:
        await message.answer("Неожиданный ввод кода. Пожалуйста, начните процесс добавления аккаунта заново.")
        await state.clear()


@check_is_admin
async def add_acc_password(message: types.Message, state: FSMContext):
    """Хендлер для получения 2FA-пароля Telethon."""
    user_id = message.from_user.id
    if user_id in telethon_futures and not telethon_futures[user_id].done():
        telethon_futures[user_id].set_result(message.text.strip())
        await state.set_state(None)
    else:
        await message.answer("Неожиданный ввод пароля. Пожалуйста, начните процесс добавления аккаунта заново.")
        await state.clear()


async def telethon_code_callback(chat_id: int, fsm_state: FSMContext, bot_instance: Bot) -> str:
    """
    Коллбэк для Telethon, который запрашивает код авторизации у пользователя через Aiogram.
    """
    await bot_instance.send_message(chat_id, "Введите полученный код авторизации Telegram:")
    await fsm_state.set_state(AddAccountStates.code)
    future = telethon_futures[chat_id]
    try:
        code = await asyncio.wait_for(future, timeout=config.AUTH_TIMEOUT_SEC)
        if code is None:
            raise asyncio.TimeoutError
        return code
    except asyncio.TimeoutError:
        await bot_instance.send_message(chat_id, "❌ Время ожидания ввода кода истекло. Пожалуйста, начните добавление аккаунта заново.")
        raise
    except Exception:
        raise

async def telethon_password_callback(chat_id: int, fsm_state: FSMContext, bot_instance: Bot) -> str:
    """
    Коллбэк для Telethon, который запрашивает 2FA-пароль у пользователя через Aiogram.
    """
    await bot_instance.send_message(chat_id, "Введите облачный пароль (2FA):")
    await fsm_state.set_state(AddAccountStates.password)
    future = telethon_futures[chat_id]
    try:
        password = await asyncio.wait_for(future, timeout=config.AUTH_TIMEOUT_SEC)
        if password is None:
            raise asyncio.TimeoutError
        return password
    except asyncio.TimeoutError:
        await bot_instance.send_message(chat_id, "❌ Время ожидания ввода 2FA-пароля истекло. Пожалуйста, начните добавление аккаунта заново.")
        raise
    except Exception:
        raise


@check_is_admin
async def del_acc_start(c: types.CallbackQuery, state: FSMContext):
    """Начало процесса удаления аккаунта: запрос индекса."""
    accounts = account_mgr.accounts
    if not accounts:
        await c.message.answer("Нет аккаунтов для удаления.")
        await c.answer()
        return

    text = "<b>Выберите номер аккаунта для удаления:</b>\n"
    for i, acc in enumerate(accounts):
        text += f"{i + 1}. <code>{acc.phone}</code>\n"

    await c.message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
        ])
    )
    await state.set_state(AddAccountStates.delete_confirm)
    await c.answer()

@check_is_admin
async def del_acc_confirm(message: types.Message, state: FSMContext):
    """подверждение удаление акка по индексу."""
    user_input = message.text.strip()
    accounts = account_mgr.accounts

    if not user_input.isdigit():
        await message.answer("Пожалуйста, введите номер аккаунта (число).")
        return

    idx = int(user_input) - 1

    if not (0 <= idx < len(accounts)):
        await message.answer("Неверный номер аккаунта. Пожалуйста, выберите существующий аккаунт из списка.")
        return

    try:
        phone_to_delete = accounts[idx].phone
        account_mgr.delete(idx)
        await message.answer(f"✅ Аккаунт <code>{phone_to_delete}</code> успешно удален.")
    except IndexError:
        await message.answer("Неверный номер аккаунта.")
    except Exception as e:
        logger.error(f"Ошибка при удалении аккаунта: {e}", exc_info=True)
        await message.answer(f"❌ Произошла ошибка при удалении аккаунта: {e}")
    finally:
        await state.clear()
        text, kb = await get_accounts_menu_content()
        await message.answer(text, reply_markup=kb)


@check_is_admin
async def list_accounts(c: types.CallbackQuery):
    accounts = account_mgr.accounts
    if not accounts:
        await c.message.answer("Нет подключенных аккаунтов.")
    else:
        text = "<b>Список аккаунтов:</b>\n"
        for i, acc in enumerate(accounts):
            status = "✅"
            try:
                if not acc.is_busy and not await acc.is_authorized():
                    status = "❌"
            except Exception as e:
                logger.warning(f"Ошибка проверки статуса аккаунта {acc.phone}: {e}")
                status = "⚠️"
            text += f"{i + 1}. {status} <code>{acc.phone}</code> (ID: <code>{acc.user_id or 'N/A'}</code>)\n"

        await c.message.answer(text)
    await c.answer()


def register_handlers(dp: Dispatcher):
    dp.message.register(cmd_menu, Command(commands=["start", "menu"]))
    dp.callback_query.register(go_to_main_menu, Text("menu"))
    dp.callback_query.register(cancel_all, Text("cancel"))
    dp.callback_query.register(close_menu, Text("close_menu"))
    dp.callback_query.register(menu_accounts, Text("m_acc"))
    dp.callback_query.register(add_acc_start, Text("add_acc"))
    dp.message.register(add_acc_phone, AddAccountStates.phone)
    dp.message.register(add_acc_api, AddAccountStates.api)
    dp.message.register(add_acc_api_hash, AddAccountStates.password)
    dp.message.register(add_acc_code, AddAccountStates.code)
    dp.message.register(add_acc_password, AddAccountStates.password)
    dp.callback_query.register(del_acc_start, Text("del_acc"))
    dp.message.register(del_acc_confirm, AddAccountStates.delete_confirm)
    dp.callback_query.register(list_accounts, Text("list_acc"))