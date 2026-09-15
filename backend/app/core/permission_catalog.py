"""Supported access controls shared by administration and authorization.

Keep feature keys here when adding a permission to a route. The catalog coverage
test rejects new authorization keys that administrators cannot configure.
"""

_ROWS = """
Sales|sales.orders|Sales orders: view, create, edit and delete|Заказы: просмотр, создание, изменение и удаление|Buyurtmalar: ko‘rish, yaratish, tahrirlash va o‘chirish
Sales|sales.customers|Manage customers|Управление клиентами|Mijozlarni boshqarish
Planning|planning.view|Planning dashboard|Панель планирования|Rejalashtirish paneli
Planning|planning.requirements|Material requirements|Потребность в материалах|Material talabi
Planning|planning.production|Manage production orders|Управление производственными заказами|Ishlab chiqarish buyurtmalarini boshqarish
Planning|planning.reserve_materials|Reserve materials|Резервирование материалов|Materiallarni band qilish
Planning|processes.view|Process tracking|Отслеживание процессов|Jarayonlarni kuzatish
Planning|forecasting.view|View forecasts|Просмотр прогнозов|Prognozlarni ko‘rish
Planning|forecasting.manage|Manage forecasts|Управление прогнозами|Prognozlarni boshqarish
Models|modeling.models|Manage models|Управление моделями|Modellarni boshqarish
Models|modeling.bom|Bill of materials|Спецификация материалов|Materiallar spetsifikatsiyasi
Models|modeling.brands|Brands|Бренды|Brendlar
Models|modeling.collections|Collections|Коллекции|Kolleksiyalar
Models|modeling.approve|Approve models|Утверждение моделей|Modellarni tasdiqlash
Cutting|cutting.records|Cutting records and passports|Раскрой и паспорта|Bichish va pasportlar
Cutting|cutting.bundles|Cutting bundles and scanning|Пачки раскроя и сканирование|Bichish to‘plamlari va skanerlash
Printing|printing.records|Printing records|Записи печати|Bosma yozuvlari
Printing|printing.bundles|Printing bundles and scanning|Пачки печати и сканирование|Bosma to‘plamlari va skanerlash
Sewing|sewing.workspace|Full sewing workspace and report editing|Рабочее место шитья и изменение отчётов|Tikuv ish maydoni va hisobotlarni tahrirlash
Sewing|sewing.flows|Sewing lines|Швейные линии|Tikuv qatorlari
Sewing|sewing.records|Sewing records|Записи шитья|Tikuv yozuvlari
Sewing|sewing.bundles|Sewing bundles and scanning|Швейные пачки и сканирование|Tikuv to‘plamlari va skanerlash
Sewing|sewing.daily_reports.view|Daily sewing reports: view and export|Ежедневные отчёты шитья: просмотр и экспорт|Kunlik tikuv hisobotlari: ko‘rish va eksport
Packaging|packaging.records|Packaging records and receiving|Упаковка и приёмка|Qadoqlash va qabul qilish
Packaging|packaging.packages|Manage packages and labels|Упаковки и этикетки|Qadoqlar va yorliqlar
Production|production.override_deadline|Override production deadline|Изменение срока производства|Ishlab chiqarish muddatini o‘zgartirish
Production|traceability.view|View traceability|Просмотр прослеживаемости|Kuzatuvni ko‘rish
Production|traceability.export|Export traceability|Экспорт прослеживаемости|Kuzatuvni eksport qilish
Inventory|storage.items|Manage material inventory|Управление запасами материалов|Material zaxiralarini boshqarish
Inventory|storage.suppliers|Manage suppliers|Управление поставщиками|Yetkazib beruvchilarni boshqarish
Inventory|storage.receive|Receive materials|Приёмка материалов|Materiallarni qabul qilish
Inventory|storage.transfer|Transfer materials|Перемещение материалов|Materiallarni ko‘chirish
Inventory|inventory.receive|Inventory receiving|Приёмка запасов|Zaxiralarni qabul qilish
Inventory|inventory.transfer|Inventory transfers|Перемещение запасов|Zaxiralarni ko‘chirish
Inventory|inventory.batches.delete|Delete unused inventory batches|Удаление неиспользованных партий|Ishlatilmagan partiyalarni o‘chirish
Inventory|inventory.force_override|Override allocated material restrictions|Обход ограничений выделенных материалов|Ajratilgan material cheklovlarini o‘zgartirish
Inventory|inventory.materials_only|Restriction: materials only, no accessories|Ограничение: только материалы, без фурнитуры|Cheklov: faqat materiallar, furniturasiz
Reservations|inventory.reservations.view|View reservations|Просмотр резервов|Band qilingan zaxiralarni ko‘rish
Reservations|inventory.reservations.create|Create reservations|Создание резервов|Zaxiralarni band qilish
Reservations|inventory.reservations.release|Release reservations|Снятие резервов|Band qilingan zaxiralarni bo‘shatish
Reservations|inventory.reservations.consume|Consume reservations|Использование резервов|Band qilingan zaxiralarni ishlatish
Warehouse|storage.packages|Finished goods and warehouse packages|Готовая продукция и складские упаковки|Tayyor mahsulotlar va ombor qadoqlari
Warehouse|storage.shipment|Shipments and dispatch|Отгрузки и отправка|Jo‘natmalar va yuborish
Purchasing|purchasing.view|View purchases|Просмотр закупок|Xaridlarni ko‘rish
Purchasing|purchasing.request|Create purchase requests|Создание заявок на закупку|Xarid so‘rovlarini yaratish
Purchasing|purchasing.approve|Approve purchases|Утверждение закупок|Xaridlarni tasdiqlash
Purchasing|purchasing.order|Manage purchase orders|Управление заказами закупок|Xarid buyurtmalarini boshqarish
Purchasing|purchasing.receive|Receive purchases|Приёмка закупок|Xaridlarni qabul qilish
Pricing|price_calculation.purchasing|Purchasing price calculation|Расчёт закупочной цены|Xarid narxini hisoblash
Pricing|price_calculation.cutting|Cutting price calculation|Расчёт стоимости раскроя|Bichish narxini hisoblash
Pricing|price_calculation.accessories|Accessory price calculation|Расчёт стоимости фурнитуры|Furnitura narxini hisoblash
Finance|finance.view|View finance|Просмотр финансов|Moliyani ko‘rish
Finance|finance.invoice|Manage invoices|Управление счетами|Hisob-fakturalarni boshqarish
Finance|finance.payment|Manage payments|Управление платежами|To‘lovlarni boshqarish
Finance|finance.payments|Finance payment access|Доступ к финансовым платежам|Moliyaviy to‘lovlarga kirish
Payroll|payroll.view|View payroll and reports|Просмотр зарплаты и отчётов|Ish haqi va hisobotlarni ko‘rish
Payroll|payroll.scan|Payroll scanning and Process QR|Сканирование зарплаты и QR операций|Ish haqi skanerlash va jarayon QR
Payroll|payroll.manage|Manage payroll|Управление зарплатой|Ish haqini boshqarish
Payroll|payroll.approve|Approve payroll|Утверждение зарплаты|Ish haqini tasdiqlash
Payroll|payroll.pay|Pay payroll|Выплата зарплаты|Ish haqini to‘lash
People|hr.employees|Manage employees and HR|Управление сотрудниками и кадрами|Xodimlar va kadrlarni boshqarish
People|attendance.view|View attendance|Просмотр посещаемости|Davomatni ko‘rish
People|attendance.manage|Manage attendance devices|Управление устройствами посещаемости|Davomat qurilmalarini boshqarish
Management|management.view|Management dashboard|Панель руководства|Rahbariyat paneli
Management|management.approve|Management approvals|Утверждения руководства|Rahbariyat tasdiqlari
Management|tasks.manage|Manage tasks|Управление задачами|Vazifalarni boshqarish
Waste|waste.receive|Receive waste|Приёмка отходов|Chiqindilarni qabul qilish
Waste|waste.sell|Sell waste|Продажа отходов|Chiqindilarni sotish
Waste|waste.disposal|Dispose of waste|Утилизация отходов|Chiqindilarni utilizatsiya qilish
Usluga|usluga.view|View Usluga|Просмотр услуг|Uslugani ko‘rish
Usluga|usluga.manage|Manage Usluga models and orders|Модели и заказы услуг|Usluga modellari va buyurtmalarini boshqarish
Usluga|usluga.handover|Usluga handover|Передача услуг|Uslugani topshirish
Usluga|usluga.cutting.approve|Approve Usluga cutting|Утверждение раскроя услуг|Usluga bichishni tasdiqlash
Administration|admin.users|Manage users and access|Управление пользователями и доступом|Foydalanuvchilar va ruxsatlarni boshqarish
Administration|admin.audit|View audit history|Просмотр истории аудита|Audit tarixini ko‘rish
Administration|admin.warehouses|Manage warehouses|Управление складами|Omborlarni boshqarish
Administration|admin.super|Super administrator controls|Управление суперадминистратора|Super administrator boshqaruvi
Administration|*|Full administrator access|Полный доступ администратора|To‘liq administrator ruxsati
"""

PERMISSION_CATALOG = [
    {"group": group, "key": key, "label": {"en": en, "ru": ru, "uz": uz}}
    for group, key, en, ru, uz in (row.split("|") for row in _ROWS.strip().splitlines())
]
PERMISSION_KEYS = frozenset(row["key"] for row in PERMISSION_CATALOG)
