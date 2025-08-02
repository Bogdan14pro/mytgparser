import os
import openpyxl
import asyncio
import re
from openpyxl.styles import Font
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import config
from models import Task

_executor = ThreadPoolExecutor(max_workers=3)


def _save_workbook(wb, path):
    ws = wb.active
    for col in ws.columns:
        max_len = max(len(str(c.value)) if c.value is not None else 0 for c in col)
        ws.column_dimensions[col[0].column_letter].width = max_len + 2
    wb.save(path)


async def make_report(task: Task, chat_title: str) -> str:
    sanitized_chat_title = re.sub(r'[<>:"/\\|?*]', '_', chat_title)
    sanitized_chat_title = re.sub(r'[^\x20-\x7E]', '', sanitized_chat_title)
    if len(sanitized_chat_title) > 50:
        sanitized_chat_title = sanitized_chat_title[:50]

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"report_{sanitized_chat_title}_{timestamp}.xlsx"
    path = os.path.join(config.REPORTS_DIR, file_name)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Собранные пользователи"

    headers = ["ID пользователя", "Имя пользователя", "Имя", "Фамилия", "Телефон", "Статус приглашения"]
    ws.append(headers)
    for col_idx, header in enumerate(headers, 1):
        ws.cell(row=1, column=col_idx).font = Font(bold=True)

    unique_users = {}
    for user in task.collected_users:
        unique_users[user.user_id] = {"data": user, "status": "Собран"}

    for user in task.invited_users:
        if user.user_id in unique_users:
            unique_users[user.user_id]["status"] = "Приглашен"
        else:
            unique_users[user.user_id] = {"data": user, "status": "Приглашен (вне сбора)"}

    already_participants_ids = {u.user_id for u in task.already_participants_list}

    for user_id, data in unique_users.items():
        status = data["status"]
        if user_id in already_participants_ids:
            status = "Уже участник"

        user = data["data"]
        ws.append([
            user.user_id,
            user.username,
            user.first_name,
            user.last_name,
            user.phone,
            status
        ])

    ws.auto_filter.ref = ws.dimensions
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(_executor, _save_workbook, wb, path)
    return path


def make_caption(task: Task, chat_title: str) -> str:
    duration_str = f"{task.duration():.2f} сек." if task.started_at else "N/A"
    account_info = task.account_phone if hasattr(task, 'account_phone') and task.account_phone else 'N/A'

    return (
        f"📊 **Отчет по задаче:** `{task.id}`\n"
        f"🔗 **Источник сбора:** `{chat_title}`\n"
        f"⚡ **Аккаунт:** `{account_info}`\n"
        f"👥 **Всего собрано пользователей:** `{len(task.collected_users)}`\n"
        f"⏳ **Длительность:** `{duration_str}`\n\n"
        f"📊 **Отчет по приглашениям:**\n"
        f"✅ Приглашено успешно: `{len(task.invited_users)}`\n"
        f"👤 Уже были участниками: `{task.already_participants}`\n"
        f"🔒 Приватность: `{task.failed_privacy}`\n"
        f"❌ Другие ошибки: `{task.failed_other}`\n"
    )
