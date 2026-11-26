"""Bot texts in Russian and Ukrainian. HTML parse mode."""
from __future__ import annotations

TEXTS: dict[str, dict[str, str]] = {
    "ru": {
        "welcome": "<b>finplan Business</b> — учёт, отчёты и налоги для малого бизнеса прямо в Telegram.\n\n"
                   "Давай настроим за минуту. <b>Как называется бизнес?</b>\nНапример: <i>Торты Оли</i> или <i>ФОП Иваненко</i>.",
        "ask_kind": "Кто вы по форме?",
        "kind_fop": "ФОП", "kind_company": "Компания (ТОВ)", "kind_freelance": "Фрилансер",
        "ask_group": "Какая группа единого налога?",
        "group": "{n} группа", "no_group": "Не ФОП / общая система",
        "ask_vat": "Вы плательщик НДС?",
        "vat_no": "Нет — ставка 5%", "vat_yes": "Да — ставка 3%",
        "ready": "Готово! <b>{name}</b> создан. Включил <b>14 дней Pro</b> бесплатно — все функции открыты.\n\n"
                 "Записывайте операции прямо сюда:\n"
                 "<code>4500 продажа торт</code> — доход\n<code>-1200 мука</code> — расход\n"
                 "<code>+15000 Иванов предоплата</code> — доход от клиента\n\n"
                 "Итоги: /today /week /month · Налог: /tax · Приложение: /app",
        "hello_back": "<b>{name}</b> — с возвращением.\nЗапишите операцию сообщением (<code>4500 продажа</code>) или откройте приложение.",
        "open_app": "Открыть finplan Business",
        "no_url": "Mini App пока не получил публичный HTTPS-адрес. Проверьте переменную PUBLIC_APP_URL.",
        "tap_open": "Нажмите, чтобы открыть приложение:",
        "need_business": "Сначала создадим бизнес: /start",
        "saved_income": "Записал доход <b>{amount}</b>",
        "saved_expense": "Записал расход <b>{amount}</b>",
        "undo": "Отменить", "change_cat": "Категория", "link_client": "Клиент",
        "undone": "Отменено", "gone": "Уже удалено", "not_allowed": "Недостаточно прав",
        "pick_cat": "Выберите категорию:", "pick_client": "К какому клиенту привязать?",
        "new_client": "+ Новый клиент", "type_client": "Напишите имя клиента:",
        "cat_set": "Категория: {name}", "client_set": "Клиент: {name}",
        "today": "Сегодня", "week": "Неделя", "month": "Месяц",
        "summary": "<b>{title}</b> · {range}\nВыручка: <b>{revenue}</b>{rev_change}\nРасходы: <b>{expenses}</b>{exp_change}\n"
                   "Прибыль: <b>{profit}</b>{margin}",
        "vs_prev": " ({pct} к прошлому)",
        "sales_line": "\nПродаж: {count} · средний чек {avg}",
        "empty_period": "За этот период операций пока нет.",
        "tax_title": "<b>Налоги</b> · {group} группа{rate}",
        "tax_none": "Налоги считаются для ФОП 1–3 группы. Укажите группу в приложении: Ещё → Бизнес.",
        "tax_item_single_tax": "Единый налог", "tax_item_esv": "ЕСВ", "tax_item_military_levy": "Военный сбор",
        "tax_line": "• {what} за {period}: <b>{amount}</b> до {due}{accruing}",
        "tax_accruing": " (квартал ещё идёт)",
        "tax_declaration": "Декларация за {period} — до {date}.",
        "tax_limit": "Лимит дохода {year}: {used} из {limit} ({percent}%)",
        "tax_nothing": "Ближайших платежей нет.",
        "daily": "<b>Сегодня</b>: {revenue} выручка, {expenses} расходы.",
        "tax_reminder": "Напоминание: {what} за {period} — <b>{amount}</b> до {due} ({days}).",
        "days_left_7": "через 7 дней", "days_left_1": "завтра",
        "limit_warn": "Доход с начала года — <b>{percent}%</b> лимита {group} группы ({used} из {limit}).",
        "limit_over": "Доход превысил лимит {group} группы: {used} при лимите {limit}. Проверьте с бухгалтером переход на другую группу.",
        "help": "<b>Как записывать</b>\n<code>4500 продажа торт</code> — доход\n<code>-1200 мука</code> — расход\n"
                "<code>+15000 Иванов предоплата</code> — доход от клиента\n<code>продал 3 торта по 450</code> — 1 350\n\n"
                "/today /week /month — итоги · /tax — налоги · /app — приложение",
    },
    "uk": {
        "welcome": "<b>finplan Business</b> — облік, звіти й податки для малого бізнесу просто в Telegram.\n\n"
                   "Налаштуймо за хвилину. <b>Як називається бізнес?</b>\nНаприклад: <i>Торти Олі</i> або <i>ФОП Іваненко</i>.",
        "ask_kind": "Хто ви за формою?",
        "kind_fop": "ФОП", "kind_company": "Компанія (ТОВ)", "kind_freelance": "Фрилансер",
        "ask_group": "Яка група єдиного податку?",
        "group": "{n} група", "no_group": "Не ФОП / загальна система",
        "ask_vat": "Ви платник ПДВ?",
        "vat_no": "Ні — ставка 5%", "vat_yes": "Так — ставка 3%",
        "ready": "Готово! <b>{name}</b> створено. Увімкнув <b>14 днів Pro</b> безкоштовно — усі функції відкриті.\n\n"
                 "Записуйте операції просто сюди:\n"
                 "<code>4500 продаж торт</code> — дохід\n<code>-1200 борошно</code> — витрата\n"
                 "<code>+15000 Іваненко передоплата</code> — дохід від клієнта\n\n"
                 "Підсумки: /today /week /month · Податок: /tax · Застосунок: /app",
        "hello_back": "<b>{name}</b> — з поверненням.\nЗапишіть операцію повідомленням (<code>4500 продаж</code>) або відкрийте застосунок.",
        "open_app": "Відкрити finplan Business",
        "no_url": "Mini App ще не отримав публічну HTTPS-адресу. Перевірте змінну PUBLIC_APP_URL.",
        "tap_open": "Натисніть, щоб відкрити застосунок:",
        "need_business": "Спершу створимо бізнес: /start",
        "saved_income": "Записав дохід <b>{amount}</b>",
        "saved_expense": "Записав витрату <b>{amount}</b>",
        "undo": "Скасувати", "change_cat": "Категорія", "link_client": "Клієнт",
        "undone": "Скасовано", "gone": "Вже видалено", "not_allowed": "Недостатньо прав",
        "pick_cat": "Оберіть категорію:", "pick_client": "До якого клієнта прив'язати?",
        "new_client": "+ Новий клієнт", "type_client": "Напишіть ім'я клієнта:",
        "cat_set": "Категорія: {name}", "client_set": "Клієнт: {name}",
        "today": "Сьогодні", "week": "Тиждень", "month": "Місяць",
        "summary": "<b>{title}</b> · {range}\nВиручка: <b>{revenue}</b>{rev_change}\nВитрати: <b>{expenses}</b>{exp_change}\n"
                   "Прибуток: <b>{profit}</b>{margin}",
        "vs_prev": " ({pct} до минулого)",
        "sales_line": "\nПродажів: {count} · середній чек {avg}",
        "empty_period": "За цей період операцій ще немає.",
        "tax_title": "<b>Податки</b> · {group} група{rate}",
        "tax_none": "Податки рахуються для ФОП 1–3 групи. Вкажіть групу в застосунку: Ще → Бізнес.",
        "tax_item_single_tax": "Єдиний податок", "tax_item_esv": "ЄСВ", "tax_item_military_levy": "Військовий збір",
        "tax_line": "• {what} за {period}: <b>{amount}</b> до {due}{accruing}",
        "tax_accruing": " (квартал ще триває)",
        "tax_declaration": "Декларація за {period} — до {date}.",
        "tax_limit": "Ліміт доходу {year}: {used} з {limit} ({percent}%)",
        "tax_nothing": "Найближчих платежів немає.",
        "daily": "<b>Сьогодні</b>: {revenue} виручка, {expenses} витрати.",
        "tax_reminder": "Нагадування: {what} за {period} — <b>{amount}</b> до {due} ({days}).",
        "days_left_7": "за 7 днів", "days_left_1": "завтра",
        "limit_warn": "Дохід з початку року — <b>{percent}%</b> ліміту {group} групи ({used} з {limit}).",
        "limit_over": "Дохід перевищив ліміт {group} групи: {used} при ліміті {limit}. Перевірте з бухгалтером перехід на іншу групу.",
        "help": "<b>Як записувати</b>\n<code>4500 продаж торт</code> — дохід\n<code>-1200 борошно</code> — витрата\n"
                "<code>+15000 Іваненко передоплата</code> — дохід від клієнта\n<code>продав 3 торти по 450</code> — 1 350\n\n"
                "/today /week /month — підсумки · /tax — податки · /app — застосунок",
    },
}


def bot_lang(language: str | None) -> str:
    return "ru" if language == "ru" else "uk"


def T(language: str | None, key: str, **kwargs) -> str:
    lang = bot_lang(language)
    text = TEXTS[lang].get(key) or TEXTS["ru"].get(key) or key
    return text.format(**kwargs) if kwargs else text
