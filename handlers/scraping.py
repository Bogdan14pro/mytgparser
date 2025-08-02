import logging
from aiogram import types, Dispatcher
from aiogram.filters import Text
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from telethon.tl.types import Channel, Chat
from telethon import TelegramClient, errors

import config
from services.task_runner import task_runner
from services.settings_manager import settings_mgr
from services.account_manager import account_mgr
from models import ScrapingStates, Task, validate_target, validate_positive_int, check_is_admin
import asyncio

logger = logging.getLogger(__name__)

@check_is_admin
async def start_scraping_process(c: types.CallbackQuery, state: FSMContext):
    await c.message.answer(
        "Шаг 1/4: Цель сбора\n"
        "Введите ссылку на Telegram чат/канал (например, https://t.me/durov или @durov)",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
        ])
    )
    await state.set_state(ScrapingStates.step1)
    await c.answer()

@check_is_admin
async def process_target_chat(m: types.Message, state: FSMContext):
    target_chat = m.text.strip()
    processing_message = await m.answer("⏳ Проверяю цель, пожалуйста, подождите...")

    client = None
    acc = None
    try:
        acc = await account_mgr.get_free_account()
        if not acc:
            await processing_message.edit_text("❌ Нет доступных аккаунтов для проверки. Пожалуйста, добавьте аккаунт.")
            await state.clear()
            return

        client = acc.client()
        await client.start()

        chat_entity = await validate_target(target_chat, client)

        if not chat_entity:
            await processing_message.edit_text("❌ Неверная ссылка на чат/канал или он недоступен. Попробуйте еще раз.")
            return

        await state.update_data(target_chat=target_chat)

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Собрать всех", callback_data="msg_0")],
            [InlineKeyboardButton(text="100 сообщений", callback_data="msg_100")],
            [InlineKeyboardButton(text="500 сообщений", callback_data="msg_500")],
            [InlineKeyboardButton(text="1000 сообщений", callback_data="msg_1000")],
            [InlineKeyboardButton(text="Указать свой лимит", callback_data="msg_custom")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
        ])
        await processing_message.edit_text(
            "Шаг 2/4: Лимит сообщений\n"
            "Выберите количество последних сообщений, из которых собирать пользователей. "
            "Это поможет ограничить объем сбора. (0 - все доступные сообщения)",
            reply_markup=kb
        )
        await state.set_state(ScrapingStates.step2)

    except errors.RPCError as e:
        logger.error(f"Ошибка Telethon при обработке целевого чата: {e}")
        await processing_message.edit_text(f"❌ Произошла ошибка Telegram API: {e}. Пожалуйста, попробуйте снова.")
    except Exception as e:
        logger.exception("Непредвиденная ошибка при обработке целевого чата:")
        await processing_message.edit_text("❌ Произошла непредвиденная ошибка. Пожалуйста, попробуйте снова.")
    finally:
        if client and client.is_connected():
            await client.disconnect()
        if acc:
            await account_mgr.release(acc)

@check_is_admin
async def process_message_limit_callback(c: types.CallbackQuery, state: FSMContext):
    if c.data == "msg_custom":
        await c.message.edit_text(
            "Шаг 2/4: Лимит сообщений\n"
            "Введите свой лимит сообщений (число от 1 до 10000):",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
            ])
        )
    else:
        message_limit = int(c.data.split('_')[1])
        await state.update_data(message_limit=message_limit)
        await show_user_limit_options(c.message, state)
    await c.answer()

@check_is_admin
async def process_message_limit_input(m: types.Message, state: FSMContext):
    message_limit_str = m.text.strip()
    if not validate_positive_int(message_limit_str, config.MAX_MSG_LIMIT):
        return await m.answer(f"Пожалуйста, введите положительное число до {config.MAX_MSG_LIMIT}.")
    message_limit = int(message_limit_str)
    await state.update_data(message_limit=message_limit)
    await show_user_limit_options(m, state)

async def show_user_limit_options(message: types.Message, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Собрать всех", callback_data="usr_0")],
        [InlineKeyboardButton(text="100 пользователей", callback_data="usr_100")],
        [InlineKeyboardButton(text="500 пользователей", callback_data="usr_500")],
        [InlineKeyboardButton(text="1000 пользователей", callback_data="usr_1000")],
        [InlineKeyboardButton(text="Указать свой лимит", callback_data="usr_custom")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
    ])
    await message.answer(
        "Шаг 3/4: Лимит пользователей\n"
        "Выберите максимальное количество пользователей для сбора. "
        "Это предотвратит сбор слишком большого количества данных. (0 - собрать всех)",
        reply_markup=kb
    )
    await state.set_state(ScrapingStates.step3)

@check_is_admin
async def process_user_limit_callback(c: types.CallbackQuery, state: FSMContext):
    if c.data == "usr_custom":
        await c.message.edit_text(
            "Шаг 3/4: Лимит пользователей\n"
            "Введите свой лимит пользователей (число от 1 до 5000):",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
            ])
        )
    else:
        user_limit = int(c.data.split('_')[1])
        await state.update_data(user_limit=user_limit)
        await show_invite_option(c.message, state)
    await c.answer()

@check_is_admin
async def process_user_limit_input(m: types.Message, state: FSMContext):
    user_limit_str = m.text.strip()
    if not validate_positive_int(user_limit_str, config.MAX_USER_LIMIT):
        return await m.answer(f"Пожалуйста, введите положительное число до {config.MAX_USER_LIMIT}.")
    user_limit = int(user_limit_str)
    await state.update_data(user_limit=user_limit)
    await show_invite_option(m, state)

async def show_invite_option(message: types.Message, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Да, пригласить", callback_data="invite_yes")],
        [InlineKeyboardButton(text="Нет, только собрать", callback_data="invite_no")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
    ])
    await message.answer(
        "Шаг 4/4: Приглашение\n"
        "После сбора пользователей, хотите ли вы автоматически пригласить их в канал, "
        "указанный в 'Настройках приглашений'?",
        reply_markup=kb
    )
    await state.set_state(ScrapingStates.step4)

@check_is_admin
async def process_invite_choice(c: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    invite_choice = c.data.split('_')[1] == "yes"

    if invite_choice and not settings_mgr.get_channel():
        await c.message.answer(
            "⚠️ Для автоматического приглашения необходимо сначала указать канал в 'Настройках приглашений'. Пожалуйста, выберите 'Нет, только собрать' или настройте канал.")
        await c.answer()
        return

    task = Task(
        admin_id=c.from_user.id,
        target_chat=data["target_chat"],
        message_limit=data.get("message_limit", 0),
        user_limit=data.get("user_limit", 0),
        invite_enabled=invite_choice
    )

    await state.clear()
    await c.message.answer(
        f"Ваша задача <code>{task.id}</code> на сбор данных из «{task.target_chat}» поставлена в очередь."
    )
    await c.answer()
    asyncio.create_task(task_runner.run(task, admin_user_id=c.from_user.id))

def register_handlers(dp: Dispatcher):
    dp.callback_query.register(start_scraping_process, Text("m_start_scraping"))
    dp.message.register(process_target_chat, ScrapingStates.step1)
    dp.callback_query.register(process_message_limit_callback, Text(startswith="msg_"), ScrapingStates.step2)
    dp.message.register(process_message_limit_input, ScrapingStates.step2)
    dp.callback_query.register(process_user_limit_callback, Text(startswith="usr_"), ScrapingStates.step3)
    dp.message.register(process_user_limit_input, ScrapingStates.step3)
    dp.callback_query.register(process_invite_choice, Text(startswith="invite_"), ScrapingStates.step4)
