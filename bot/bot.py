import os
import logging
import asyncio
import requests
import re
from datetime import datetime
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    FSInputFile
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

# ==============================
# ENV / CONFIG
# ==============================
load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))
BACKEND_URL = "https://buyer-bot-0tle.onrender.com"

logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN, parse_mode="HTML")
dp = Dispatcher()


# это та самая папка с ботом

# ==============================
# FSM
# ==============================
class CreateLinkFSM(StatesGroup):
    waiting_for_title = State()
    waiting_for_price = State()
    waiting_for_percent = State()
    waiting_for_confirmation = State()

class SalesReportFSM(StatesGroup):
    waiting_for_period = State()
    waiting_for_custom_range = State()

class ClientsReportFSM(StatesGroup):
    waiting_for_period = State()
    waiting_for_custom_range = State()

class CancelOrderFSM(StatesGroup):
    waiting_for_order_id = State()

class DeleteSalesReportFSM(StatesGroup):
    waiting_for_period = State()
    waiting_for_custom_range = State()
    waiting_for_confirm = State()

class RestoreFSM(StatesGroup):
    choose_type = State()
    waiting_order_id = State()
    confirm_restore_order = State()
    choose_sales_archive = State()
    confirm_restore_sales = State()

# ==============================
# HELPERS
# ==============================
def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_CHAT_ID

def is_strict_number(value: str) -> bool:
    return value.isdigit() and int(value) > 0

def format_date(d):
    return d[:10] if d else "..."

async def show_start_menu(msg: types.Message):
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="Создать ссылку на оплату"),
            ],
            [
                KeyboardButton(text="Отчёт по клиентам"),
                KeyboardButton(text="Отчёт по продажам")
                
            ],
            [
                KeyboardButton(text="Удалить отчет по продажам"),
                KeyboardButton(text="Отменить заказ")
                
            ], 
            [
                KeyboardButton(text="Восстановить данные")
            ]
        ],
        resize_keyboard=True
    )

    await msg.answer("Админ-меню:", reply_markup=kb)


# ==============================
# /start
# ==============================
@dp.message(Command("start"))
async def start_cmd(msg: types.Message):
    if not is_admin(msg.from_user.id):
        return

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="Создать ссылку на оплату"),
            ],
            [
                KeyboardButton(text="Отчёт по клиентам"),
                KeyboardButton(text="Отчёт по продажам")
                
            ],
            [
                KeyboardButton(text="Удалить отчет по продажам"),
                KeyboardButton(text="Отменить заказ")
            ], 
            [
                KeyboardButton(text="Восстановить данные")
            ]
        ],
        resize_keyboard=True
    )

    await msg.answer("Админ-меню:", reply_markup=kb)


# ==============================
# MENU
# ==============================
@dp.message(StateFilter(None))
async def menu_handler(msg: types.Message, state: FSMContext):
    if not is_admin(msg.from_user.id):
        return

    text = msg.text.lower()

    if text == "создать ссылку на оплату":
        await state.set_state(CreateLinkFSM.waiting_for_title)
        await msg.answer("Введите название товара:")
        return

    if text == "отчёт по продажам":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="1 день", callback_data="report_1"),
                InlineKeyboardButton(text="7 дней", callback_data="report_7"),
            ],
            [
                InlineKeyboardButton(text="30 дней", callback_data="report_30"),
                InlineKeyboardButton(text="За всё время", callback_data="report_all"),
            ],
            [
                InlineKeyboardButton(text="Свой период", callback_data="report_custom"),
            ]
        ])

        await state.set_state(SalesReportFSM.waiting_for_period)
        await msg.answer("Выберите период:", reply_markup=kb)
        return
    
    if text == "отчёт по клиентам":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="1 день", callback_data="clients_1"),
                InlineKeyboardButton(text="7 дней", callback_data="clients_7"),
            ],
            [
                InlineKeyboardButton(text="30 дней", callback_data="clients_30"),
                InlineKeyboardButton(text="За всё время", callback_data="clients_all"),
            ],
            [
                InlineKeyboardButton(text="Свой период", callback_data="clients_custom"),
            ]
        ])

        await state.set_state(ClientsReportFSM.waiting_for_period)
        await msg.answer("Выберите период:", reply_markup=kb)
        return
    
    if text == "отменить заказ":
        await state.set_state(CancelOrderFSM.waiting_for_order_id)
        await msg.answer(
            "Введите ID заказа для отмены.\n\n"
            "Формат: <b>ГГГГММДД_XXX</b>\n"
            "Пример: <code>20251020_001</code>"
        )
        return
    
    if text == "удалить отчет по продажам":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="1 день", callback_data="del_sales_1"),
                InlineKeyboardButton(text="7 дней", callback_data="del_sales_7"),
            ],
            [
                InlineKeyboardButton(text="30 дней", callback_data="del_sales_30"),
                InlineKeyboardButton(text="За всё время", callback_data="del_sales_all"),
            ],
            [
                InlineKeyboardButton(text="Свой период", callback_data="del_sales_custom"),
            ]
        ])

        await state.set_state(DeleteSalesReportFSM.waiting_for_period)
        await msg.answer("Выберите период удаления:", reply_markup=kb)
        return
    
    if text == "восстановить данные":
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="Восстановить заказ")],
                [KeyboardButton(text="Восстановить отчет по продажам")],
                [KeyboardButton(text="Отмена")]
            ],
            resize_keyboard=True
        )

        await state.set_state(RestoreFSM.choose_type)
        await msg.answer("Что вы хотите восстановить?", reply_markup=kb)
        return
    
    await msg.answer("Команда не распознана.")

@dp.message(CreateLinkFSM.waiting_for_title)
async def step_title(msg: types.Message, state: FSMContext):
    if not msg.text.strip():
        return await msg.answer("Название не может быть пустым.")

    await state.update_data(title=msg.text.strip())
    await state.set_state(CreateLinkFSM.waiting_for_price)
    await msg.answer("Введите стоимость товара (₽):")


@dp.message(CreateLinkFSM.waiting_for_price)
async def step_price(msg: types.Message, state: FSMContext):
    if not is_strict_number(msg.text):
        return await msg.answer("Стоимость должна быть положительным числом. Пример: 8000")

    await state.update_data(price=int(msg.text))
    await state.set_state(CreateLinkFSM.waiting_for_percent)
    await msg.answer("Введите процент агентского вознаграждения (например 10):")


@dp.message(CreateLinkFSM.waiting_for_percent)
async def step_percent(msg: types.Message, state: FSMContext):
    if not is_strict_number(msg.text):
        return await msg.answer("Процент должен быть числом. Пример: 10")

    percent = int(msg.text)
    if percent > 100:
        return await msg.answer("Процент не может быть больше 100.")

    await state.update_data(percent=percent)
    data = await state.get_data()

    price = data["price"]
    fee = price * percent // 100
    total = price + fee

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Подтвердить", callback_data="confirm")],
        [InlineKeyboardButton(text="Отменить", callback_data="cancel")]
    ])

    await state.set_state(CreateLinkFSM.waiting_for_confirmation)
    await msg.answer(
        f"<b>Проверьте данные:</b>\n\n"
        f"Товар: {data['title']}\n"
        f"Стоимость: {price}₽\n"
        f"Агентское вознаграждение: {percent}% ({fee}₽)\n\n"
        f"<b>ИТОГО: {total}₽</b>",
        reply_markup=kb
    )


@dp.callback_query(CreateLinkFSM.waiting_for_confirmation)
async def step_confirm(call: types.CallbackQuery, state: FSMContext):
    if call.data == "cancel":
        await state.clear()
        return await call.message.edit_text("❌ Операция отменена.")

    data = await state.get_data()

    resp = requests.post(
        f"{BACKEND_URL}/api/products/create",
        json={
            "title": data["title"],
            "base_price": data["price"],
            "percent": data["percent"]
        }
    )

    if resp.status_code != 200:
        await state.clear()
        return await call.message.edit_text("Ошибка создания товара.")

    product_id = resp.json()["product_id"]
    payment_url = f"{BACKEND_URL}/pay/{product_id}"

    price = data["price"]
    fee = price * data["percent"] // 100
    total = price + fee

    await call.message.edit_text(
        f"<b>Товар:</b> {data['title']}\n"
        f"<b>Стоимость:</b> {price}₽\n"
        f"<b>Агентское вознаграждение:</b> {fee}₽\n"
        f"<b>ИТОГО:</b> {total}₽\n\n"
        f"<a href='{payment_url}'>Ссылка на оплату</a>"
    )

    await state.clear()


@dp.callback_query(SalesReportFSM.waiting_for_period)
async def report_period_handler(call: types.CallbackQuery, state: FSMContext):
    if call.data == "report_custom":
        await state.set_state(SalesReportFSM.waiting_for_custom_range)
        return await call.message.edit_text(
            "Введите период в формате:\n<b>ДД.ММ.ГГ-ДД.ММ.ГГ</b>"
        )

    period_map = {
        "report_1": 1,
        "report_7": 7,
        "report_30": 30,
        "report_all": "all"
    }

    period = period_map.get(call.data)
    if not period:
        return

    await call.message.edit_text("Формирую отчёт...")
    await send_sales_report(call.message, period=period)
    await state.clear()


@dp.message(SalesReportFSM.waiting_for_custom_range)
async def report_custom_range(msg: types.Message, state: FSMContext):
    try:
        start_str, end_str = msg.text.split("-")
        start_date = datetime.strptime(start_str.strip(), "%d.%m.%Y").date()
        end_date = datetime.strptime(end_str.strip(), "%d.%m.%Y").date()
    except ValueError:
        return await msg.answer("Неверный формат. Пример: 20.10.2025-20.12.2025")

    await msg.answer("Формирую отчёт...")

    await send_sales_report(
        msg,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat()
    )

    await state.clear()

async def send_sales_report(
    message: types.Message,
    period: int | str | None = None,
    start_date: str | None = None,
    end_date: str | None = None
):
    payload = {}

    if period is not None:
        payload["period"] = period
    else:
        payload["start_date"] = start_date
        payload["end_date"] = end_date

    resp = requests.post(
        f"{BACKEND_URL}/api/reports/sales",
        json=payload
    )

    if resp.status_code != 200:
        return await message.answer("Ошибка формирования отчёта.")

    file_path = "sales_report.pdf"
    with open(file_path, "wb") as f:
        f.write(resp.content)

    await message.answer_document(
        FSInputFile(file_path),
        caption="Отчёт по продажам"
    )

@dp.callback_query(ClientsReportFSM.waiting_for_period)
async def clients_report_period_handler(call: types.CallbackQuery, state: FSMContext):
    if call.data == "clients_custom":
        await state.set_state(ClientsReportFSM.waiting_for_custom_range)
        return await call.message.edit_text(
            "Введите период в формате:\n<b>ДД.ММ.ГГГГ-ДД.ММ.ГГГГ</b>"
        )

    period_map = {
        "clients_1": 1,
        "clients_7": 7,
        "clients_30": 30,
        "clients_all": "all"
    }

    period = period_map.get(call.data)
    if not period:
        return

    await call.message.edit_text("Формирую отчёт...")
    await send_clients_report(call.message, period=period)
    await state.clear()

@dp.message(ClientsReportFSM.waiting_for_custom_range)
async def clients_report_custom_range(msg: types.Message, state: FSMContext):
    try:
        start_str, end_str = msg.text.split("-")
        start_date = datetime.strptime(start_str.strip(), "%d.%m.%Y").date()
        end_date = datetime.strptime(end_str.strip(), "%d.%m.%Y").date()
    except ValueError:
        return await msg.answer("Неверный формат. Пример: 20.10.2025-20.12.2025")

    await msg.answer("Формирую отчёт...")
    await send_clients_report(
        msg,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat()
    )
    await state.clear()

async def send_clients_report(message: types.Message, period: int | str | None = None, start_date: str | None = None, end_date: str | None = None):
    payload = {}
    if period is not None:
        payload["period"] = period
    else:
        payload["start_date"] = start_date
        payload["end_date"] = end_date

    resp = requests.post(f"{BACKEND_URL}/api/reports/clients", json=payload)
    if resp.status_code != 200:
        return await message.answer("Ошибка формирования отчёта.")

    file_path = "clients_report.pdf"
    with open(file_path, "wb") as f:
        f.write(resp.content)

    await message.answer_document(FSInputFile(file_path), caption="Отчёт по клиентам")

@dp.message(CancelOrderFSM.waiting_for_order_id)
async def cancel_order_handler(msg: types.Message, state: FSMContext):
    order_id = msg.text.strip()

    if not re.fullmatch(r"\d{8}_\d{3}", order_id):
        return await msg.answer(
            "❌ Неверный формат ID заказа.\n"
            "Пример: <code>20251020_001</code>"
        )

    await msg.answer("⏳ Отменяю заказ...")

    resp = requests.post(
        f"{BACKEND_URL}/api/orders/cancel",
        json={"order_id": order_id}
    )

    if resp.status_code != 200:
        try:
            error = resp.json().get("detail", "Не удалось отменить заказ")
        except Exception:
            error = "Не удалось отменить заказ"

        await msg.answer(f"❌ {error}")
        await state.clear()
        return

    data = resp.json()

    await msg.answer(
        f"✅ <b>{data['message']}</b>\n\n"
        f"<b>Не забудьте вернуть средства покупателю:</b>\n"
        f"Сумма: <b>{data['refund']['amount']}₽</b>\n"
        f"Клиент: {data['refund']['client']}\n"
        f"Телефон: {data['refund']['phone']}"
    )

    await state.clear()


@dp.callback_query(DeleteSalesReportFSM.waiting_for_period)
async def delete_sales_period(call: types.CallbackQuery, state: FSMContext):
    if call.data == "del_sales_custom":
        await state.set_state(DeleteSalesReportFSM.waiting_for_custom_range)
        return await call.message.edit_text(
            "Введите период:\n<b>ДД.ММ.ГГГГ-ДД.ММ.ГГГГ</b>"
        )

    period_map = {
        "del_sales_1": 1,
        "del_sales_7": 7,
        "del_sales_30": 30,
        "del_sales_all": "all"
    }

    period = period_map.get(call.data)
    if not period:
        return

    await state.update_data(period=period)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Да", callback_data="confirm_yes"),
            InlineKeyboardButton(text="Нет", callback_data="confirm_no"),
        ]
    ])

    await state.set_state(DeleteSalesReportFSM.waiting_for_confirm)
    await call.message.edit_text(
        "⚠️ Вы уверены, что хотите удалить отчёт по продажам?\n"
        "Данные будут заархивированы на 30 дней.",
        reply_markup=kb
    )

@dp.message(DeleteSalesReportFSM.waiting_for_custom_range)
async def delete_sales_custom_range(msg: types.Message, state: FSMContext):
    try:
        start_str, end_str = msg.text.split("-")
        start_date = datetime.strptime(start_str.strip(), "%d.%m.%Y").date()
        end_date = datetime.strptime(end_str.strip(), "%d.%m.%Y").date()
    except ValueError:
        return await msg.answer(
            "❌ Неверный формат.\n"
            "Пример: <b>20.10.2025-20.12.2025</b>"
        )

    await state.update_data(
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat()
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Да", callback_data="confirm_yes"),
            InlineKeyboardButton(text="Нет", callback_data="confirm_no"),
        ]
    ])

    await state.set_state(DeleteSalesReportFSM.waiting_for_confirm)

    await msg.answer(
        "⚠️ Вы уверены, что хотите удалить отчёт по продажам?\n"
        "Данные будут заархивированы на 30 дней.",
        reply_markup=kb
    )


@dp.callback_query(DeleteSalesReportFSM.waiting_for_confirm)
async def delete_sales_confirm(call: types.CallbackQuery, state: FSMContext):
    if call.data == "confirm_no":
        await state.clear()
        return await call.message.edit_text("❌ Отменено.")

    data = await state.get_data()

    payload = {}
    if "period" in data:
        payload["period"] = data["period"]
    else:
        payload["start_date"] = data["start_date"]
        payload["end_date"] = data["end_date"]

    resp = requests.post(
        f"{BACKEND_URL}/api/reports/sales/delete",
        json=payload
    )

    if resp.status_code != 200:
        await state.clear()
        return await call.message.edit_text("Ошибка удаления отчёта.")

    result = resp.json()

    await call.message.edit_text(
        f"✅ Отчёт удалён\n"
        f"Удалено заказов: <b>{result['deleted_orders']}</b>\n\n"
        f"Архив хранится 30 дней."
    )

    await state.clear()

@dp.message(RestoreFSM.choose_type, F.text == "Восстановить заказ")
async def restore_order_start(msg: types.Message, state: FSMContext):
    await state.set_state(RestoreFSM.waiting_order_id)
    await msg.answer(
        "Введите ID заказа.\n"
        "Пример: <code>20251020_001</code>"
    )

@dp.message(RestoreFSM.waiting_order_id)
async def restore_order_preview(msg: types.Message, state: FSMContext):
    order_id = msg.text.strip()

    resp = requests.get(
        f"{BACKEND_URL}/api/orders/archive/{order_id}"
    )

    if resp.status_code != 200:
        await state.clear()
        await msg.answer("❌ Заказ не найден или срок восстановления истёк")
        return await show_start_menu(msg)

    data = resp.json()
    await state.update_data(order_id=order_id)

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="Восстановить"),
                KeyboardButton(text="Отмена")
            ]
        ],
        resize_keyboard=True
    )

    await state.set_state(RestoreFSM.confirm_restore_order)

    await msg.answer(
        "Заказ найден в архиве:\n\n"
        f"ID: {data['order_id']}\n"
        f"Товар: {data['product_title']}\n"
        f"Количество: {data['quantity']} шт\n"
        f"Сумма: {data['total_amount']} ₽\n"
        f"Дата удаления: {data['deleted_at']}\n"
        f"Клиент: {data['client']['fullname']}",
        reply_markup=kb
    )

@dp.message(RestoreFSM.confirm_restore_order, F.text == "Восстановить")
async def restore_order_confirm(msg: types.Message, state: FSMContext):
    data = await state.get_data()

    requests.post(
        f"{BACKEND_URL}/api/orders/archive/{data['order_id']}/restore"
    )

    await state.clear()
    await msg.answer("✅ Заказ успешно восстановлен")
    await show_start_menu(msg)

@dp.message(F.text == "Отмена")
async def cancel_reply_handler(msg: types.Message, state: FSMContext):
    await state.clear()
    await msg.answer("❌ Операция отменена.")
    await show_start_menu(msg)

@dp.message(RestoreFSM.choose_type, F.text == "Восстановить отчет по продажам")
async def restore_sales_list(msg: types.Message, state: FSMContext):
    resp = requests.get(f"{BACKEND_URL}/api/reports/sales/archive/list")
    archives = resp.json()

    if not archives:
        await state.clear()
        await msg.answer("Нет доступных архивов для восстановления")
        return await show_start_menu(msg)

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{a['archived_at']} | {format_date(a['period_from'])}-{format_date(a['period_to'])}",
                    callback_data=f"restore_sales_{a['id']}"
                )
            ]
            for a in archives
        ]
    )

    await state.set_state(RestoreFSM.choose_sales_archive)
    await msg.answer("Выберите архив отчёта:", reply_markup=kb)

@dp.callback_query(
    RestoreFSM.choose_sales_archive,
    F.data.startswith("restore_sales_")
)
async def restore_sales_confirm(call: types.CallbackQuery, state: FSMContext):
    archive_id = int(call.data.split("_")[-1])
    await state.update_data(archive_id=archive_id)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Да", callback_data="restore_sales_yes"),
            InlineKeyboardButton(text="Нет", callback_data="restore_sales_no"),
        ]
    ])

    await state.set_state(RestoreFSM.confirm_restore_sales)
    await call.message.edit_text(
        "Восстановить выбранный отчет по продажам?",
        reply_markup=kb
    )

@dp.callback_query(
    RestoreFSM.confirm_restore_sales,
    F.data == "restore_sales_yes"
)
async def restore_sales_execute(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()

    requests.post(
        f"{BACKEND_URL}/api/reports/sales/archive/{data['archive_id']}/restore"
    )

    await state.clear()
    await call.message.edit_text("✅ Отчёт по продажам восстановлен")
    await show_start_menu(call.message)

# ==============================
# START
# ==============================
async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
