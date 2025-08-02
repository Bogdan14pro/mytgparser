from aiogram import types, Dispatcher
from aiogram.filters import Text
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import config
from services.settings_manager import settings_mgr
from services.task_runner import task_runner
from models import Task, check_is_admin
import asyncio


class SeparateInviteStates(StatesGroup):
    user_limit = State()


@check_is_admin
async def start_inviting_process(c: types.CallbackQuery, state: FSMContext):
    invite_channel = settings_mgr.get_channel()
    if not invite_channel:
        await c.message.answer("⚠️ Сначала укажите канал для приглашений в разделе 'Настройки приглашений'.")
        await c.answer()
        return

    await c.message.answer(
        "Введите максимальное количество пользователей для приглашения (число):",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]]
        )
    )
    await state.set_state(SeparateInviteStates.user_limit)
    await c.answer()


@check_is_admin
async def process_invite_user_limit(message: types.Message, state: FSMContext):
    user_limit_str = message.text.strip()
    if not user_limit_str.isdigit():
        return await message.answer("Пожалуйста, введите число.")

    user_limit = int(user_limit_str)
    if user_limit <= 0:
        return await message.answer("Число должно быть положительным.")

    if user_limit > config.MAX_USER_LIMIT:
        return await message.answer(f"Максимальный лимит пользователей: {config.MAX_USER_LIMIT}.")

    task = Task(
        admin_id=message.from_user.id,
        target_chat=None,
        message_limit=0,
        user_limit=user_limit,
        invite_enabled=True
    )

    await state.clear()
    await message.answer(f"✅ Задача #{task.id} на приглашение {user_limit} пользователей добавлена.")
    asyncio.create_task(task_runner.run(task, admin_user_id=message.from_user.id))


def register_handlers(dp: Dispatcher):
    dp.callback_query.register(start_inviting_process, Text("m_start_inviting"))
    dp.message.register(process_invite_user_limit, SeparateInviteStates.user_limit)
