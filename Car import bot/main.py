"""
Telegram-бот для розрахунку вартості авто з США
Підтримувані країни розмитнення: Україна, Польща, Литва, Грузія
Встановлення: pip install pyTelegramBotAPI
Запуск: python car_import_bot.py
"""

import os
import logging
import datetime
import telebot
from telebot import types

# ===== НАЛАШТУВАННЯ =====
import os

BOT_TOKEN     = os.environ.get("BOT_TOKEN")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")

if not BOT_TOKEN:
    raise RuntimeError("❌ Змінна середовища BOT_TOKEN не задана!")
if not ADMIN_CHAT_ID:
    raise RuntimeError("❌ Змінна середовища ADMIN_CHAT_ID не задана!")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
bot = telebot.TeleBot(BOT_TOKEN)

# ===== КУРСИ ВАЛЮТ (оновлювати вручну або підключити API) =====
RATES = {
    "UAH": {"usd": 41.5,  "eur": 44.5,  "symbol": "грн", "code": "UAH"},
    "PLN": {"usd": 4.05,  "eur": 4.28,  "symbol": "злот.", "code": "PLN"},
    "EUR": {"usd": 0.93,  "eur": 1.0,   "symbol": "EUR",  "code": "EUR"},  # Литва — євро
    "GEL": {"usd": 2.68,  "eur": 2.88,  "symbol": "ларі", "code": "GEL"},
}

# ===== КНОПКИ =====
BTN_CANCEL  = "❌ Скасувати"
BTN_CONTACT = "📞 Надіслати мій номер"

BTN_COUNTRY = {
    "🇺🇦 Україна": "ukraine",
    "🇵🇱 Польща":  "poland",
    "🇱🇹 Литва":   "lithuania",
    "🇬🇪 Грузія":  "georgia",
}
COUNTRY_NAMES = {v: k for k, v in BTN_COUNTRY.items()}

BTN_FUEL = {
    "⛽️ Бензин": "gasoline",
    "🛢 Дизель":  "diesel",
    "🔋 Гібрид":  "hybrid",
    "⚡️ Електро": "electric",
}
FUEL_NAMES = {
    "gasoline": "Бензин ⛽️",
    "diesel":   "Дизель 🛢",
    "hybrid":   "Гібрид 🔋",
    "electric": "Електро ⚡️",
}


# ===== ТАБЛИЦЯ АУКЦІОННИХ ЗБОРІВ (Copart / IAAI) =====
def get_auction_fee(price_usd: float) -> float:
    table = [
        (100, 1), (499, 89), (999, 129), (1499, 179), (1999, 229),
        (2999, 279), (3999, 329), (4999, 379), (5999, 429), (6999, 479),
        (7999, 529), (8999, 579), (9999, 629), (14999, 729), (19999, 829),
        (29999, 979), (49999, 1279), (74999, 1579), (99999, 1879),
    ]
    for limit, fee in table:
        if price_usd <= limit:
            return fee
    return 2179


# ============================================================
#  РОЗРАХУНКИ ПО КРАЇНАХ
# ============================================================

def calc_ukraine(customs_usd, engine_cc, fuel_type, car_age):
    """Україна: мито + акциз + ПДВ"""
    r = RATES["UAH"]
    usd2uah = r["usd"]
    usd2eur = r["usd"] / r["eur"]
    customs_eur = customs_usd * usd2eur

    if fuel_type == "electric":
        vat = customs_usd * usd2uah * 0.20
        return {
            "duty_local": 0, "duty_note": "0% — пільга для електро",
            "excise_local": 0, "excise_note": "пільга для електро",
            "vat_local": vat, "vat_note": "20% від митної вартості",
            "total_customs": vat,
            "currency": r["symbol"],
        }

    # Мито
    rate_map = [(3, 0.10, "10% до 3 р."), (5, 0.15, "15% 3–5 р."),
                (8, 0.20, "20% 5–8 р."), (999, 0.25, "25% понад 8 р.")]
    duty_rate, duty_note = next((rt, nt) for ag, rt, nt in rate_map if car_age <= ag)
    duty_eur = customs_eur * duty_rate
    duty_uah = duty_eur * r["eur"]

    # Акциз (EUR/см³)
    exc_tbl = [
        (1500,  (0.012, 0.024, 0.048, 0.072)),
        (2000,  (0.024, 0.048, 0.096, 0.144)),
        (2500,  (0.048, 0.096, 0.144, 0.216)),
        (3000,  (0.072, 0.144, 0.216, 0.288)),
        (3500,  (0.096, 0.192, 0.288, 0.384)),
        (4500,  (0.144, 0.288, 0.432, 0.576)),
        (99999, (0.192, 0.384, 0.576, 0.768)),
    ]
    ai = 0 if car_age <= 3 else (1 if car_age <= 5 else (2 if car_age <= 8 else 3))
    fc = 1.2 if fuel_type == "diesel" else (0.5 if fuel_type == "hybrid" else 1.0)
    er = 0.192
    for lim, rates in exc_tbl:
        if engine_cc <= lim:
            er = rates[ai]; break
    er *= fc
    excise_eur = er * engine_cc
    excise_uah = excise_eur * r["eur"]

    vat_base = customs_usd * usd2uah + duty_uah + excise_uah
    vat = vat_base * 0.20

    total = duty_uah + excise_uah + vat
    return {
        "duty_local": duty_uah, "duty_note": duty_note,
        "duty_eur": duty_eur,
        "excise_local": excise_uah, "excise_note": f"{er:.4f} EUR × {engine_cc} см³",
        "excise_eur": excise_eur,
        "vat_local": vat, "vat_note": "20% від (вартість + мито + акциз)",
        "total_customs": total,
        "currency": r["symbol"],
    }


def calc_poland(customs_usd, engine_cc, fuel_type, car_age):
    """Польща (ЄС): мито 6.5% + акциз + ПДВ 23%"""
    r = RATES["PLN"]
    usd2pln = r["usd"]
    usd2eur = r["usd"] / r["eur"]
    customs_eur = customs_usd * usd2eur

    # Мито ЄС — 6.5% від митної вартості в EUR
    duty_eur = customs_eur * 0.065
    duty_pln = duty_eur * r["eur"]
    duty_note = "6.5% (ставка ЄС)"

    # Акциз (тільки для авто старше 2 років і об'єм > 2000 см³)
    excise_eur = 0.0
    excise_note = "0"
    if car_age > 2 and engine_cc > 2000:
        excise_eur = customs_eur * 0.184  # 18.4% для великих авто
        excise_note = f"18.4% (об'єм > 2000 см³, вік > 2 р.)"
    elif fuel_type == "electric":
        excise_note = "0 — електромобіль"
    excise_pln = excise_eur * r["eur"]

    # ПДВ 23% від (митна вартість + мито + акциз)
    vat_base_pln = customs_usd * usd2pln + duty_pln + excise_pln
    vat = vat_base_pln * 0.23
    vat_note = "23% від (вартість + мито + акциз)"

    total = duty_pln + excise_pln + vat
    return {
        "duty_local": duty_pln, "duty_note": duty_note, "duty_eur": duty_eur,
        "excise_local": excise_pln, "excise_note": excise_note, "excise_eur": excise_eur,
        "vat_local": vat, "vat_note": vat_note,
        "total_customs": total,
        "currency": r["symbol"],
    }


def calc_lithuania(customs_usd, engine_cc, fuel_type, car_age):
    """Литва (ЄС): мито 6.5% + ПДВ 21%, розрахунок в EUR"""
    r = RATES["EUR"]
    usd2eur = r["usd"]
    customs_eur = customs_usd * usd2eur

    duty_eur = customs_eur * 0.065
    duty_note = "6.5% (ставка ЄС)"

    excise_eur = 0.0
    excise_note = "0"
    if fuel_type not in ("electric",) and engine_cc > 2000 and car_age > 2:
        excise_eur = customs_eur * 0.15
        excise_note = f"15% (об'єм > 2000 см³)"

    vat_base = customs_eur + duty_eur + excise_eur
    vat = vat_base * 0.21
    vat_note = "21% від (вартість + мито + акциз)"

    total = duty_eur + excise_eur + vat
    return {
        "duty_local": duty_eur, "duty_note": duty_note, "duty_eur": duty_eur,
        "excise_local": excise_eur, "excise_note": excise_note, "excise_eur": excise_eur,
        "vat_local": vat, "vat_note": vat_note,
        "total_customs": total,
        "currency": r["symbol"],
    }


def calc_georgia(customs_usd, engine_cc, fuel_type, car_age):
    """Грузія: мито 0% + акциз залежно від об'єму + ПДВ 18%"""
    r = RATES["GEL"]
    usd2gel = r["usd"]
    customs_gel = customs_usd * usd2gel

    # Мито 0% (Грузія має дуже низькі ставки)
    duty_gel = 0.0
    duty_note = "0% (пільгова ставка Грузії)"

    # Акциз: фіксована ставка в USD залежно від об'єму і віку
    excise_usd_map = [
        (1000,  0.05), (1500,  0.10), (2000,  0.20),
        (2500,  0.35), (3000,  0.50), (3500,  0.75), (99999, 1.00),
    ]
    if fuel_type == "electric":
        excise_gel = 0.0
        excise_note = "0 — електромобіль"
    else:
        age_coef = 1.0 if car_age <= 3 else (1.5 if car_age <= 7 else 2.0)
        base_rate = 0.20
        for lim, rate in excise_usd_map:
            if engine_cc <= lim:
                base_rate = rate; break
        excise_usd_val = base_rate * engine_cc * age_coef / 100
        excise_gel = excise_usd_val * usd2gel
        excise_note = f"{base_rate} USD/см³ × {engine_cc} × к-т {age_coef}"

    vat_base_gel = customs_gel + duty_gel + excise_gel
    vat = vat_base_gel * 0.18
    vat_note = "18% від (вартість + акциз)"

    total = duty_gel + excise_gel + vat
    return {
        "duty_local": duty_gel, "duty_note": duty_note,
        "excise_local": excise_gel, "excise_note": excise_note,
        "vat_local": vat, "vat_note": vat_note,
        "total_customs": total,
        "currency": r["symbol"],
    }


COUNTRY_CALCULATORS = {
    "ukraine":   (calc_ukraine,   RATES["UAH"]),
    "poland":    (calc_poland,    RATES["PLN"]),
    "lithuania": (calc_lithuania, RATES["EUR"]),
    "georgia":   (calc_georgia,   RATES["GEL"]),
}


# ===== СТАН КОРИСТУВАЧІВ =====
user_data = {}

STEP_QUESTIONS = {
    "country":      "🌍 *Крок 1 з 8*\n\nОберіть *країну розмитнення*:",
    "car_price":    "💵 *Крок 2 з 8*\n\nВведіть *ціну автомобіля* на аукціоні (у USD):\n_Приклад: 8500_",
    "auction_fee":  "🏷 *Крок 3 з 8*\n\nАукціонний збір:\nВведіть *0* — і я розрахую автоматично за таблицею Copart/IAAI\nАбо введіть суму вручну (USD):",
    "delivery_usa": "🚚 *Крок 4 з 8*\n\nВведіть вартість *доставки по США* до порту (USD):\n_Приклад: 400_",
    "sea_delivery": "🚢 *Крок 5 з 8*\n\nВведіть вартість *морської доставки* до вашої країни (USD):\n_Орієнтовно 900–1500 USD_",
    "engine_cc":    "⚙️ *Крок 6 з 8*\n\nВведіть *об'єм двигуна* у куб. см (см³):\n_Приклад: 1998_\n_Для електромобіля введіть 0_",
    "fuel_type":    "⛽️ *Крок 7 з 8*\n\nОберіть *тип пального*:",
    "car_age":      "📅 *Крок 8 з 8*\n\nВведіть *рік випуску* автомобіля (наприклад: 2019)\nабо кількість *повних років* (наприклад: 5):",
}


# ===== КЛАВІАТУРИ =====
def remove_keyboard():
    return types.ReplyKeyboardRemove()

def cancel_keyboard():
    m = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
    m.add(BTN_CANCEL)
    return m

def country_keyboard():
    m = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    m.add("🇺🇦 Україна", "🇵🇱 Польща")
    m.add("🇱🇹 Литва",   "🇬🇪 Грузія")
    m.add(BTN_CANCEL)
    return m

def fuel_keyboard():
    m = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    m.add("⛽️ Бензин", "🛢 Дизель")
    m.add("🔋 Гібрид",  "⚡️ Електро")
    m.add(BTN_CANCEL)
    return m

def contact_keyboard():
    m = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    m.add(types.KeyboardButton(BTN_CONTACT, request_contact=True))
    m.add(BTN_CANCEL)
    return m


# ===== /start =====
@bot.message_handler(commands=["start"])
def cmd_start(message):
    uid = message.chat.id
    user_data[uid] = {"step": "country"}
    bot.send_message(
        uid,
        "🚗 *Калькулятор вартості авто з США*\n\n"
        "Розрахую повну вартість під ключ з урахуванням:\n"
        "• Аукціонних зборів\n"
        "• Доставки\n"
        "• Митних платежів\n\n"
        "Починаємо!\n\n" + STEP_QUESTIONS["country"],
        parse_mode="Markdown",
        reply_markup=country_keyboard()
    )


# ===== ГОЛОВНИЙ ОБРОБНИК =====
@bot.message_handler(content_types=["text"])
def handle_text(message):
    uid  = message.chat.id
    text = message.text.strip()

    # Скасувати — завжди
    if text == BTN_CANCEL:
        user_data.pop(uid, None)
        bot.send_message(uid, "❌ Розрахунок скасовано.\n\nНатисніть /start щоб почати знову.",
                         reply_markup=remove_keyboard())
        return

    if uid not in user_data:
        bot.send_message(uid, "Натисніть /start щоб почати розрахунок.")
        return

    step = user_data[uid].get("step")

    # --- Вибір країни ---
    if step == "country":
        if text not in BTN_COUNTRY:
            bot.send_message(uid, "Будь ласка, оберіть країну з кнопок нижче 👇",
                             reply_markup=country_keyboard())
            return
        user_data[uid]["country"] = BTN_COUNTRY[text]
        user_data[uid]["step"] = "car_price"
        bot.send_message(uid, STEP_QUESTIONS["car_price"],
                         parse_mode="Markdown", reply_markup=cancel_keyboard())
        return

    # --- Вибір пального ---
    if step == "fuel_type":
        if text not in BTN_FUEL:
            bot.send_message(uid, "Будь ласка, оберіть тип пального з кнопок нижче 👇",
                             reply_markup=fuel_keyboard())
            return
        user_data[uid]["fuel_type"] = BTN_FUEL[text]
        user_data[uid]["step"] = "car_age"
        bot.send_message(uid, STEP_QUESTIONS["car_age"],
                         parse_mode="Markdown", reply_markup=cancel_keyboard())
        return

    # --- Очікування контакту ---
    if step == "waiting_contact":
        bot.send_message(uid,
            "Натисніть кнопку *«📞 Надіслати мій номер»* нижче\n"
            "або *«❌ Скасувати»* для відміни.",
            parse_mode="Markdown", reply_markup=contact_keyboard())
        return

    # --- Завершено ---
    if step in ("done", "finished"):
        bot.send_message(uid, "Натисніть /start для нового розрахунку.",
                         reply_markup=remove_keyboard())
        return

    # --- Числові кроки ---
    try:
        value = float(text.replace(",", ".").replace(" ", "").replace("\u202f", ""))
    except ValueError:
        bot.send_message(uid, "❌ Введіть число, наприклад: *8500*",
                         parse_mode="Markdown", reply_markup=cancel_keyboard())
        return

    if step == "car_price":
        if value <= 0:
            bot.send_message(uid, "❌ Ціна має бути більше 0", reply_markup=cancel_keyboard())
            return
        user_data[uid]["car_price"] = value
        user_data[uid]["step"] = "auction_fee"
        bot.send_message(uid, STEP_QUESTIONS["auction_fee"],
                         parse_mode="Markdown", reply_markup=cancel_keyboard())

    elif step == "auction_fee":
        if value == 0:
            auto_fee = get_auction_fee(user_data[uid]["car_price"])
            user_data[uid]["auction_fee"] = auto_fee
            bot.send_message(uid,
                f"✅ Аукціонний збір: *{auto_fee} USD* (за таблицею Copart/IAAI)",
                parse_mode="Markdown")
        else:
            user_data[uid]["auction_fee"] = value
        user_data[uid]["step"] = "delivery_usa"
        bot.send_message(uid, STEP_QUESTIONS["delivery_usa"],
                         parse_mode="Markdown", reply_markup=cancel_keyboard())

    elif step == "delivery_usa":
        user_data[uid]["delivery_usa"] = value
        user_data[uid]["step"] = "sea_delivery"
        bot.send_message(uid, STEP_QUESTIONS["sea_delivery"],
                         parse_mode="Markdown", reply_markup=cancel_keyboard())

    elif step == "sea_delivery":
        user_data[uid]["sea_delivery"] = value
        user_data[uid]["step"] = "engine_cc"
        bot.send_message(uid, STEP_QUESTIONS["engine_cc"],
                         parse_mode="Markdown", reply_markup=cancel_keyboard())

    elif step == "engine_cc":
        user_data[uid]["engine_cc"] = int(value)
        user_data[uid]["step"] = "fuel_type"
        bot.send_message(uid, STEP_QUESTIONS["fuel_type"],
                         parse_mode="Markdown", reply_markup=fuel_keyboard())

    elif step == "car_age":
        age = (datetime.datetime.now().year - int(value)) if value > 1900 else int(value)
        if age < 0:
            bot.send_message(uid, "❌ Некоректний рік. Спробуйте ще раз.",
                             reply_markup=cancel_keyboard())
            return
        user_data[uid]["car_age"] = age
        user_data[uid]["step"] = "done"
        send_result(uid)


# ===== ОБРОБНИК КОНТАКТУ =====
@bot.message_handler(content_types=["contact"])
def handle_contact(message):
    uid = message.chat.id
    if user_data.get(uid, {}).get("step") != "waiting_contact":
        return

    d = user_data.get(uid, {})
    age = d.get("car_age", "?")
    year = datetime.datetime.now().year - age if isinstance(age, int) else "?"
    country_name = COUNTRY_NAMES.get(d.get("country", ""), "?")

    admin_msg = (
        f"🔔 *НОВА ЗАЯВКА*\n\n"
        f"👤 {message.from_user.first_name} {message.from_user.last_name or ''}\n"
        f"📱 Телефон: `{message.contact.phone_number}`\n"
        f"🆔 Telegram ID: `{uid}`\n\n"
        f"🚗 *Параметри авто:*\n"
        f"  Країна розмитнення: {country_name}\n"
        f"  Ціна: {d.get('car_price', '?')} USD\n"
        f"  Аукціонний збір: {d.get('auction_fee', '?')} USD\n"
        f"  Доставка США: {d.get('delivery_usa', '?')} USD\n"
        f"  Морська доставка: {d.get('sea_delivery', '?')} USD\n"
        f"  Об'єм: {d.get('engine_cc', '?')} см³\n"
        f"  Пальне: {FUEL_NAMES.get(d.get('fuel_type',''), '?')}\n"
        f"  Рік: {year} (~{age} р.)"
    )

    try:
        bot.send_message(ADMIN_CHAT_ID, admin_msg, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Помилка надсилання адміністратору: {e}")

    user_data[uid]["step"] = "finished"
    bot.send_message(uid,
        "✅ *Заявку надіслано!*\n\nМенеджер зв'яжеться з вами найближчим часом. 🤝\n\n"
        "Натисніть /start для нового розрахунку.",
        parse_mode="Markdown", reply_markup=remove_keyboard())


# ===== ВИВІД РЕЗУЛЬТАТУ =====
def send_result(uid):
    d = user_data[uid]
    country      = d["country"]
    car_price    = d["car_price"]
    auction_fee  = d["auction_fee"]
    delivery_usa = d["delivery_usa"]
    sea_delivery = d["sea_delivery"]
    engine_cc    = d["engine_cc"]
    fuel_type    = d["fuel_type"]
    car_age      = d["car_age"]

    customs_usd = car_price + auction_fee + delivery_usa + sea_delivery
    calc_fn, rate = COUNTRY_CALCULATORS[country]
    c = calc_fn(customs_usd, engine_cc, fuel_type, car_age)

    usd2local     = rate["usd"]
    sym           = rate["symbol"]
    logistics_usd = customs_usd
    logistics_loc = logistics_usd * usd2local
    customs_total = c["total_customs"]
    total_loc     = logistics_loc + customs_total
    total_usd     = total_loc / usd2local

    year = datetime.datetime.now().year - car_age
    age_word = "рік" if car_age == 1 else ("роки" if 2 <= car_age <= 4 else "років")
    age_note = f"{year} р. ({car_age} {age_word})"
    country_name = COUNTRY_NAMES.get(country, country)

    msg = (
        f"✅ *РОЗРАХУНОК ЗАВЕРШЕНО*\n"
        f"{'─' * 32}\n\n"
        f"🌍 Країна розмитнення: *{country_name}*\n\n"
        f"📋 *Вихідні дані:*\n"
        f"  Ціна авто:            *{car_price:,.0f} USD*\n"
        f"  Аукціонний збір:      *{auction_fee:,.0f} USD*\n"
        f"  Доставка по США:      *{delivery_usa:,.0f} USD*\n"
        f"  Морська доставка:     *{sea_delivery:,.0f} USD*\n"
        f"  Об'єм двигуна:        *{engine_cc} см³*\n"
        f"  Тип пального:         *{FUEL_NAMES[fuel_type]}*\n"
        f"  Рік випуску:          *{age_note}*\n\n"
        f"{'─' * 32}\n"
        f"💰 *Розрахунок вартості:*\n\n"
        f"*1. Логістика:*\n"
        f"  Ціна авто:        {car_price:,.0f} USD\n"
        f"  Аукціон:          {auction_fee:,.0f} USD\n"
        f"  Доставка США:     {delivery_usa:,.0f} USD\n"
        f"  Морська доставка: {sea_delivery:,.0f} USD\n"
        f"  ➡️ *Разом: {logistics_usd:,.0f} USD / {logistics_loc:,.0f} {sym}*\n\n"
        f"*2. Митні платежі ({country_name}):*\n"
        f"  Мито:    {c['duty_local']:,.0f} {sym} — {c['duty_note']}\n"
        f"  Акциз:   {c['excise_local']:,.0f} {sym} — {c['excise_note']}\n"
        f"  ПДВ:     {c['vat_local']:,.0f} {sym} — {c['vat_note']}\n"
        f"  ➡️ *Разом мито: {customs_total:,.0f} {sym}*\n\n"
        f"{'─' * 32}\n"
        f"🔑 *ПІДСУМКОВА ВАРТІСТЬ ПІД КЛЮЧ:*\n"
        f"  *≈ {total_loc:,.0f} {sym}*\n"
        f"  *≈ {total_usd:,.0f} USD*\n\n"
        f"{'─' * 32}\n"
        f"📌 _1 USD = {usd2local} {sym}_\n"
        f"_Розрахунок орієнтовний. Уточнюйте у менеджера._"
    )

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📩 Залишити заявку",   callback_data="request"))
    markup.add(types.InlineKeyboardButton("🔄 Новий розрахунок", callback_data="restart"))

    bot.send_message(uid, msg, parse_mode="Markdown", reply_markup=remove_keyboard())
    bot.send_message(uid, "Оберіть дію:", reply_markup=markup)


# ===== INLINE КНОПКИ =====
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    uid = call.message.chat.id
    bot.answer_callback_query(call.id)

    if call.data == "restart":
        user_data[uid] = {"step": "country"}
        bot.send_message(uid,
            "🔄 *Новий розрахунок*\n\n" + STEP_QUESTIONS["country"],
            parse_mode="Markdown", reply_markup=country_keyboard())

    elif call.data == "request":
        if user_data.get(uid, {}).get("step") == "finished":
            bot.send_message(uid, "✅ Ви вже залишили заявку. Менеджер зв'яжеться з вами.",
                             reply_markup=remove_keyboard())
            return
        user_data.setdefault(uid, {})["step"] = "waiting_contact"
        bot.send_message(uid,
            "📞 Надішліть ваш *номер телефону* для зв'язку.\nНатисніть кнопку нижче 👇",
            parse_mode="Markdown", reply_markup=contact_keyboard())


# ===== ЗАПУСК =====
if __name__ == "__main__":
    logging.info("✅ Бот запущено...")
    while True:
        try:
            bot.infinity_polling(timeout=30, long_polling_timeout=20)
        except Exception as e:
            logging.error(f"Polling впав: {e}. Перезапуск через 5 сек...")
            import time
            time.sleep(5)
