import os
import logging
import asyncio
import requests
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, StateFilter
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))
BACKEND_URL = "http://127.0.0.1:8000"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN, parse_mode="HTML")
dp = Dispatcher()


# ==============================
# FSM
# ==============================
class CreateLinkFSM(StatesGroup):
    waiting_for_title = State()
    waiting_for_price = State()
    waiting_for_percent = State()
    waiting_for_confirmation = State()


# ==============================
# /start
# ==============================
@dp.message(Command("start"))
async def start_cmd(msg: types.Message):
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="Создать ссылку на оплату"),
                KeyboardButton(text="Отчёт по продажам")
            ],
            [
                KeyboardButton(text="Отчёт по клиентам"),
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
# Меню
# ==============================
@dp.message(StateFilter(None))
async def menu_handler(msg: types.Message, state: FSMContext):
    text = msg.text.lower()

    if text == "создать ссылку на оплату":
        await state.set_state(CreateLinkFSM.waiting_for_title)
        await msg.answer("Введите название товара:")
        return

    await msg.answer("Команда не распознана.")


# ==============================
# Название
# ==============================
@dp.message(CreateLinkFSM.waiting_for_title)
async def step_title(msg: types.Message, state: FSMContext):
    await state.update_data(title=msg.text)
    await state.set_state(CreateLinkFSM.waiting_for_price)
    await msg.answer("Введите стоимость товара (₽):")


# ==============================
# Цена
# ==============================
@dp.message(CreateLinkFSM.waiting_for_price)
async def step_price(msg: types.Message, state: FSMContext):
    if not msg.text.isdigit():
        return await msg.answer("Введите число, например 8000")

    await state.update_data(price=int(msg.text))
    await state.set_state(CreateLinkFSM.waiting_for_percent)
    await msg.answer("Введите процент агентского вознаграждения (например 10):")


# ==============================
# Процент
# ==============================
@dp.message(CreateLinkFSM.waiting_for_percent)
async def step_percent(msg: types.Message, state: FSMContext):
    if not msg.text.isdigit():
        return await msg.answer("Введите число, например 10")

    await state.update_data(percent=int(msg.text))
    data = await state.get_data()

    price = data["price"]
    percent = data["percent"]
    fee = price * percent // 100
    total = price + fee

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Подтвердить", callback_data="confirm")],
        [InlineKeyboardButton(text="Отменить", callback_data="cancel")],
    ])

    await state.set_state(CreateLinkFSM.waiting_for_confirmation)
    await msg.answer(
        f"<b>Проверьте данные перед созданием ссылки:</b>\n\n"
        f"Товар: {data['title']}\n"
        f"Стоимость: {price}₽\n"
        f"Агентское вознаграждение: {percent}% ({fee}₽)\n\n"
        f"<b>ИТОГО: {total}₽</b>",
        reply_markup=kb
    )


# ==============================
# Подтверждение
# ==============================
@dp.callback_query(CreateLinkFSM.waiting_for_confirmation)
async def step_confirm(call: types.CallbackQuery, state: FSMContext):
    if call.data == "cancel":
        await state.clear()
        return await call.message.edit_text("❌ Отменено.")

    data = await state.get_data()

    # === создаём товар в backend ===
    resp = requests.post(
        f"{BACKEND_URL}/api/products/create",
        json={
            "title": data["title"],
            "base_price": data["price"],
            "percent": data["percent"]
        }
    )

    product_id = resp.json()["product_id"]

    payment_url = f"{BACKEND_URL}/pay/{product_id}"

    price = data["price"]
    percent = data["percent"]
    fee = price * percent // 100
    total = price + fee

    await call.message.edit_text(
        f"<b>Товар:</b> {data['title']}\n"
        f"<b>Стоимость:</b> {price}₽\n"
        f"<b>Агентское вознаграждение:</b> {fee}₽\n"
        f"<b>ИТОГО:</b> {total}₽\n\n"
        f"<a href='{payment_url}'>Ссылка на оплату</a>"
    )

    await state.clear()


# ==============================
# START
# ==============================
async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
