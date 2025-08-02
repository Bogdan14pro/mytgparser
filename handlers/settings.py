from aiogram import types, Dispatcher
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters.text import Text
from aiogram.fsm.context import FSMContext
from telethon import TelegramClient
from typing import Tuple

import config
from models import InviteSettingsStates, check_is_admin
from services.settings_manager import settings_mgr
from services.account_manager import account_mgr


async def get_settings_menu_content(user_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    current_channel = settings_mgr.get_channel() or "Не установлен"
    auto_invite_status = "Включены" if settings_mgr.is_auto_invite() else "Отключены"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Установить канал для приглашений", callback_data="set_invite_channel")],
        [InlineKeyboardButton(text=f"Автоприглашения: {auto_invite_status}", callback_data="toggle_auto_invite")],
        [InlineKeyboardButton(text="◀️ Назад в главное меню", callback_data="menu")]
    ])
    text = f"⚙️ Настройки приглашений:\nТекущий канал: <code>{current_channel}</code>"
    return text, kb


@check_is_admin
async def show_settings_menu(c: types.CallbackQuery, state: FSMContext):
    await state.clear()
    text, kb = await get_settings_menu_content(c.from_user.id)
    await c.message.edit_text(text, reply_markup=kb, parse_mode='HTML')
    await c.answer()


@check_is_admin
async def start_set_invite_channel(c: types.CallbackQuery, state: FSMContext):
    await c.message.edit_text(
        "Введите юзернейм или ссылку на публичный канал, куда будут приглашаться пользователи (например, @mychannel или https://t.me/mychannel):\n\n"
        "⚠️ Важно: Один из ваших подключенных аккаунтов должен быть администратором в этом канале.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
        ])
    )
    await state.set_state(InviteSettingsStates.channel)
    await c.answer()


@check_is_admin
async def process_invite_channel(m: types.Message, state: FSMContext):
    channel_input = m.text.strip()
    processing_message = await m.answer("⏳ Проверяю канал и пытаюсь установить его. Пожалуйста, подождите...")

    try:
        await settings_mgr.set_channel(channel_input)
        await processing_message.edit_text(f"✅ Канал для приглашений успешно установлен на <code>{channel_input}</code>.")
    except ValueError as ve:
        await processing_message.edit_text(f"❌ Ошибка установки канала: {ve}")
    except Exception as e:
        await processing_message.edit_text(f"❌ Произошла непредвиденная ошибка: {e}")
    finally:
        await state.clear()
        text, kb = await get_settings_menu_content(m.from_user.id)
        await m.answer(text, reply_markup=kb, parse_mode='HTML')


@check_is_admin
async def toggle_auto_invite(c: types.CallbackQuery):
    new_status = settings_mgr.toggle_invite()
    status_text = "Включены" if new_status else "Отключены"
    await c.answer(f"Автоприглашения: {status_text}", show_alert=True)
    text, kb = await get_settings_menu_content(c.from_user.id)
    await c.message.edit_text(text, reply_markup=kb, parse_mode='HTML')


def register_handlers(dp: Dispatcher):
    dp.callback_query.register(show_settings_menu, Text("m_settings"))
    dp.callback_query.register(start_set_invite_channel, Text("set_invite_channel"))
    dp.message.register(process_invite_channel, InviteSettingsStates.channel)
    dp.callback_query.register(toggle_auto_invite, Text("toggle_auto_invite"))
