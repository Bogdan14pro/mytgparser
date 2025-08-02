import asyncio
import logging
import time
from telethon import TelegramClient, errors
from telethon.sessions import StringSession
from telethon.tl.functions.channels import InviteToChannelRequest
from telethon.tl.types import User
from telethon.tl.functions.messages import GetHistoryRequest
from telethon.tl.types import Channel
from typing import Optional

import config
from services.account_manager import account_mgr
from services.settings_manager import settings_mgr
from services.report_generator import make_report, make_caption
import models
from aiogram import Bot
from aiogram.types import FSInputFile

logger = logging.getLogger(__name__)

bot = Bot(token=config.BOT_TOKEN)

async def api_call(coro_func, *args, timeout=30, max_backoff=4, **kwargs):
    backoff = 1
    while True:
        try:
            return await asyncio.wait_for(coro_func(*args, **kwargs), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(f"Timeout for {coro_func.__name__}. Retrying with backoff {backoff}")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)
        except errors.FloodWaitError as e:
            logger.warning(f"FloodWaitError for {coro_func.__name__}. Waiting {e.seconds} seconds.")
            await asyncio.sleep(e.seconds + 1)
            backoff = 1
        except errors.RPCError as e:
            logger.error(f"RPC Error for {coro_func.__name__}: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in api_call for {coro_func.__name__}: {e}")
            raise

class TaskRunner:
    def __init__(self):
        self.running_tasks = {}
        self.running_tasks_count = 0

    async def run(self, task: models.Task, admin_user_id: int):
        if self.running_tasks_count >= config.MAX_CONCURRENT_SCRAPING_TASKS:
            task.status = "queued"
            await bot.send_message(admin_user_id,
                                   f"Задача <code>{task.id}</code> поставлена в очередь. Макс. количество одновременно выполняемых задач: {config.MAX_CONCURRENT_SCRAPING_TASKS}.")
            return

        self.running_tasks_count += 1
        self.running_tasks[task.id] = asyncio.create_task(
            self._run_task_internal(task, admin_user_id)
        )
        logger.info(f"Starting task {task.id}. Current running tasks: {self.running_tasks_count}")
        await bot.send_message(admin_user_id, f"Задача <code>{task.id}</code> запущена.")

    async def _run_task_internal(self, task: models.Task, admin_user_id: int):
        client: Optional[TelegramClient] = None
        acc = None
        try:
            task.status = "running"
            task.started_at = time.monotonic()

            acc = await account_mgr.get_free_account()
            if not acc:
                raise RuntimeError("Нет свободных аккаунтов для выполнения задачи.")

            client = acc.client()
            await client.start()
            task.account_phone = acc.phone

            entity = await api_call(client.get_entity, task.target_chat)

            if isinstance(entity, Channel):
                task.chat_id = entity.id
                task.chat_title = entity.title
                logger.info(f"Target is Channel: {entity.title} ({entity.id})")
            elif isinstance(entity, User) and entity.bot:
                raise ValueError(f"Цель {task.target_chat} является ботом, сбор из ботов не поддерживается.")
            else:
                try:
                    full_entity = await api_call(client(entity))
                    if hasattr(full_entity, 'chats') and len(full_entity.chats) > 0:
                        chat_obj = full_entity.chats[0]
                        if isinstance(chat_obj, Channel):
                            task.chat_id = chat_obj.id
                            task.chat_title = chat_obj.title
                            logger.info(f"Target is Channel (via User entity): {chat_obj.title} ({chat_obj.id})")
                        elif isinstance(chat_obj, models.Chat):
                            task.chat_id = chat_obj.id
                            task.chat_title = chat_obj.title
                            logger.info(f"Target is Chat: {chat_obj.title} ({chat_obj.id})")
                        else:
                            raise ValueError("Цель не является поддерживаемым типом (канал или группа).")
                    else:
                        raise ValueError("Цель не является поддерживаемым типом (канал или группа).")
                except Exception as e:
                    raise ValueError(
                        f"Не удалось получить информацию о цели {task.target_chat}: {e}.")

            if task.message_limit > 0:
                logger.info(f"Collecting users from {task.chat_title} (limit {task.message_limit} messages)...")
                total_messages = 0
                async for msg in client.iter_messages(entity, limit=task.message_limit):
                    total_messages += 1
                    if msg.sender and isinstance(msg.sender, User) and not msg.sender.bot:
                        user_stub = models.UserStub(
                            user_id=msg.sender.id,
                            username=msg.sender.username,
                            first_name=msg.sender.first_name,
                            last_name=msg.sender.last_name,
                            phone=msg.sender.phone
                        )
                        if user_stub.user_id not in [u.user_id for u in task.collected_users]:
                            task.collected_users.append(user_stub)
                            if len(task.collected_users) >= task.user_limit and task.user_limit > 0:
                                logger.info(f"Collected {len(task.collected_users)} users. Reached user limit.")
                                break
                    if total_messages % 100 == 0:
                        logger.info(
                            f"Processed {total_messages} messages, collected {len(task.collected_users)} users.")
                logger.info(
                    f"Finished collecting. Total messages processed: {total_messages}, total users collected: {len(task.collected_users)}")
            elif task.user_limit > 0 and task.message_limit == 0:
                logger.info(f"Collecting users directly from chat participants (limit {task.user_limit})...")
                if isinstance(entity, (Channel, models.Chat)):
                    try:
                        async for participant in client.iter_participants(entity, limit=task.user_limit):
                            if isinstance(participant, User) and not participant.bot:
                                user_stub = models.UserStub(
                                    user_id=participant.id,
                                    username=participant.username,
                                    first_name=participant.first_name,
                                    last_name=participant.last_name,
                                    phone=participant.phone
                                )
                                if user_stub.user_id not in [u.user_id for u in task.collected_users]:
                                    task.collected_users.append(user_stub)
                                    if len(task.collected_users) >= task.user_limit:
                                        logger.info(f"Collected {len(task.collected_users)} users. Reached user limit.")
                                        break
                        logger.info(
                            f"Finished collecting participants. Total users collected: {len(task.collected_users)}")
                    except errors.RPCError as e:
                        logger.warning(f"Ошибка при получении участников чата {task.chat_title}: {e}")
                        await bot.send_message(admin_user_id,
                                               f"⚠️ Не удалось собрать участников из {task.chat_title}: {e}")
                else:
                    logger.warning("Прямой сбор участников возможен только для каналов/групп.")
                    await bot.send_message(admin_user_id,
                                           "⚠️ Прямой сбор участников возможен только для каналов/групп.")

            if task.invite_enabled and len(task.collected_users) > 0:
                invite_channel_username = settings_mgr.get_channel()
                if invite_channel_username:
                    logger.info(f"Inviting collected users to {invite_channel_username}...")
                    try:
                        invite_channel_entity = await api_call(client.get_entity, invite_channel_username)
                        if not isinstance(invite_channel_entity, Channel):
                            raise ValueError("Канал для приглашений не является действительным каналом Telegram.")

                        for user_stub in task.collected_users:
                            try:
                                await api_call(InviteToChannelRequest, invite_channel_entity, [user_stub.user_id])
                                task.invited_users.append(user_stub)
                                logger.info(f"Invited user {user_stub.user_id} to {invite_channel_username}")
                                await asyncio.sleep(config.INVITE_DELAY_SEC)

                            except errors.RPCError as rpc_e:
                                if isinstance(rpc_e, errors.FloodWaitError):
                                    logger.warning(f"FloodWaitError during invite: {rpc_e.seconds}s. Waiting...")
                                    await asyncio.sleep(rpc_e.seconds + 1)
                                    task.failed_other += 1
                                elif isinstance(rpc_e, errors.UserPrivacyRestrictedError):
                                    task.failed_privacy += 1
                                    logger.warning(f"User {user_stub.user_id} privacy restricted.")
                                elif isinstance(rpc_e, errors.UserAlreadyParticipantError):
                                    task.already_participants_list.append(user_stub)
                                    task.already_participants += 1
                                    logger.info(f"User {user_stub.user_id} already a participant.")
                                elif isinstance(rpc_e, errors.UserBlockedError):
                                    task.failed_other += 1
                                    logger.warning(f"User {user_stub.user_id} blocked the bot.")
                                else:
                                    task.failed_other += 1
                                    logger.error(f"Other RPCError inviting {user_stub.user_id}: {rpc_e}")
                            except Exception as e:
                                task.failed_other += 1
                                logger.error(f"Unhandled error during invitation for user {user_stub.user_id}: {e}")

                        task.invite_status = "success"
                        logger.info(
                            f"Finished inviting users to {invite_channel_username}. Invited: {len(task.invited_users)}")

                    except ValueError as e:
                        task.invite_status = "failed"
                        logger.error(f"Ошибка при подготовке к приглашению: {e}")
                        await bot.send_message(admin_user_id,
                                               f"❌ Ошибка приглашения: {e}. Проверьте канал в настройках.")
                    except Exception as e:
                        task.invite_status = "failed"
                        logger.exception(f"Непредвиденная ошибка при приглашении в канал {invite_channel_username}")
                        await bot.send_message(admin_user_id,
                                               f"❌ Неизвестная ошибка при приглашении: {e}. Проверьте канал в настройках.")
                else:
                    task.invite_status = "skipped_no_channel"
                    await bot.send_message(admin_user_id,
                                           "⚠️ Приглашение пропущено: канал для приглашений не установлен в настройках.")

            task.finished_at = time.monotonic()
            report_path = await make_report(task, task.target_chat if task.target_chat else "users_list")
            report_caption = make_caption(task, task.target_chat if task.target_chat else "Список пользователей")

            await bot.send_document(admin_user_id, FSInputFile(report_path), caption=report_caption)

            task.status = "completed"
            logger.info(f"Task {task.id} completed in {task.duration():.2f} sec")

        except Exception as e:
            task.status = "failed"
            logger.exception(f"❌ Ошибка в задаче {task.id}")
            await bot.send_message(admin_user_id,
                                   f"❌ Ошибка в задаче <code>{task.id}</code>: {e}. Подробности в логах.")

        finally:
            self.running_tasks_count -= 1
            if task.id in self.running_tasks:
                del self.running_tasks[task.id]

            if client and client.is_connected():
                await client.disconnect()
            if acc:
                await account_mgr.release(acc)

            logger.info(f"Task {task.id} finished. Current running tasks: {self.running_tasks_count}")

task_runner = TaskRunner()
