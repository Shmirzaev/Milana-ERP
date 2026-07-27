# Super Admin To'liq Tafsilotlar O'quv Qo'llanma

Versiya: 1.0
Sana: 2026-07-02
Bo'lim kodi: ADM
Rol: Super Admin

## Maqsad

Super Admin eng yuqori darajadagi ERP ruxsatiga ega. Super Admin Administrator qila oladigan hamma narsani qila oladi, shuningdek, MCP Access va raw Data Console kabi faqat Super Admin funksiyalari.

Bu roldan faqat ishonchli tizim egalari uchun foydalaning. Oddiy kundalik bo'lim ishi uchun Super Admindan foydalanmang.

## Super Adminga kirish

Super Admin quyidagilardan biri tomonidan aniqlanadi:

1. Rol nomi `Super Admin`.
2. Ruxsat `admin.super`.

Super Admin ruxsatnomalari:

1. `*`
2. `admin.super`

`*` ruxsati ERP ilovasiga toʻliq kirish imkonini beradi. `admin.super` ruxsati faqat Super Admin bo'limlarini ochadi.

## Super Admin sahifalari

- MCP Access
- Data Console

Super Admin shuningdek, barcha oddiy ilova sahifalariga, jumladan foydalanuvchilar, bo'limlar, audit jurnallari, sozlamalar, asboblar paneli, ishlab chiqarish, moliya, ish haqi, xaridlar, inventarizatsiya, kuzatuv va barcha bo'lim sahifalariga kirish huquqiga ega.

## Birinchi administrator bootstrap

Urug'lik jarayoni konfiguratsiya qilinganida Super Admin bootstrap foydalanuvchisini yaratadi.

Muhim qoidalar:

1. Birinchi administratorni faollashtirish uchun `INITIAL_ADMIN_PASSWORD` o'rnatilishi kerak.
2. Haqiqiy administrator hisobi uchun standart umumiy demo/administrator parollari bloklangan.
3. `INITIAL_ADMIN_EMAIL` birinchi administrator elektron pochta manzilini o'rnatishi mumkin.
4. Demo foydalanuvchilari faqat `SEED_DEMO_USERS=true`da yaratiladi.
5. Namuna mijozlar/materiallar/modellar/buyurtmalar faqat `SEED_SAMPLE_DATA=true`da yaratiladi.

## Foydalanuvchi ma'muriyati

Super Admin Administrator va Super Admin hisoblarini yaratishi va boshqarishi mumkin. Oddiy administratorlarga Super Admin boshqaruvini tayinlash taqiqlangan.

Foydalanuvchi yaratish:

1. Foydalanuvchilarni oching.
2. Ism va elektron pochta manzilini kiriting.
3. Rolni tanlang.
4. Bo'limni tanlang.
5. Foydalanuvchi yaratish.
6. Joylashtirish siyosatiga muvofiq elektron pochta/parolni sozlash jarayonini tasdiqlang.

Foydalanuvchi tahriri:

1. Foydalanuvchi tahririni oching.
2. Ism/elektron pochta manzilini yangilang.
3. Yangi parolni faqat siyosat ruxsat berganda oʻrnating.
4. Rolni o'zgartirish.
5. Bo'limni o'zgartirish.
6. Qo'shimcha ruxsatlarni qo'shish yoki olib tashlash.
7. Faollashtirish/o‘chirish.
8. Saqlash.

Super Admin qoidalari:

1. Kamida bitta faol Super Admin/Administrator hisobini saqlang.
2. Vaqtinchalik foydalanuvchilarga `*` yoki `admin.super` ni tayinlamang.
3. Biror kishi chiqib ketganda darhol hisoblarni o'chirib qo'ying.
4. Eski imtiyozli hisoblar uchun oxirgi marta koʻrilgan/soʻnggi kirishni koʻrib chiqing.
5. Bitta Super Admin hisobini baham ko'rishdan saqlaning.

## Ruxsat modeli

Rollarda ruxsatlar mavjud. Foydalanuvchilar qo'shimcha ruxsatlarga ham ega bo'lishi mumkin.

Asosiy ruxsat toifalari:

1. Sotuv: `sales.orders`, `sales.customers`.
2. Rejalashtirish: `planning.view`, `planning.requirements`, `planning.production`, `planning.reserve_materials`, `processes.view`, `sewing.flows`.
3. Modellashtirish: `modeling.models`, `modeling.bom`, `modeling.brands`, `modeling.collections`, `modeling.approve`.
4. Ishlab chiqarish maydoni: `cutting.records`, `cutting.bundles`, `printing.records`, `printing.bundles`, `sewing.records`, `sewing.bundles`, `packaging.records`, `packaging.packages`, `production.override_deadline`.
5. Saqlash va jo'natish: `storage.receive`, `storage.transfer`, `storage.items`, `storage.suppliers`, `storage.packages`, `storage.shipment`.
6. Moliya: `finance.view`, `finance.invoice`, `finance.payment`.
7. Kadrlar va ish haqi: `hr.employees`, `payroll.view`, `payroll.manage`, `payroll.approve`, `payroll.pay`, `payroll.scan`.
8. Sotib olish: `purchasing.view`, `purchasing.request`, `purchasing.approve`, `purchasing.order`, `purchasing.receive`.
9. Chiqindilar: `waste.receive`, `waste.sell`, `waste.disposal`.
10. Boshqaruv/Admin: `management.view`, `management.approve`, `admin.users`, `admin.audit`, `admin.super`, `tasks.manage`.
11. Kuzatilish/prognozlash: `traceability.view`, `traceability.export`, `forecasting.view`, `forecasting.manage`.
12. Inventar zahiralari: `inventory.reservations.view`, `inventory.reservations.create`, `inventory.reservations.release`, `inventory.reservations.consume`.

Avval rollardan foydalaning. Qo'shimcha ruxsatlardan faqat ataylab istisnolar uchun foydalaning.

## Urug'li bo'limlar

| Kod | Kafedra |
| --- | --- |
| SLS | Sotuv |
| PLN | Rejalashtirish |
| STR | Mato va furnitura ombori |
| CUT | Bichish |
| PRT | Chop etish |
| SEW | Tikuv |
| MIL | Milana tikuv fabrikasi |
| BST | Besttex tikuvchilik fabrikasi |
| PKG | Qadoqlash |
| BPK | Besttex Textile Packaging |
| FGS | Tayyor mahsulotni saqlash |
| FIN | Moliya |
| MOD | Modellashtirish / PLM |
| HR | HR |
| WST | Chiqindilarni chiqarish bo'limi |
| ADM | Rahbariyat / Admin |

## O'rnatilgan rollar

| Rol | Asosiy maqsad |
| --- | --- |
| Super Admin | Toʻliq tizim egasi va faqat Super Admin vositalari. |
| Admin | Faqat Super Admin imtiyozlarisiz ilovaga toʻliq kirish. |
| Boshqaruv | Boshqaruv paneli, tasdiqlash, kuzatish, ish haqi/sotib olish/prognoz nazorati, favqulodda qavatga kirish. |
| Sotuv | Savdo Buyurtmalari, mijozlar, kuzatish, kuzatish, prognozlash o'qiladi. |
| Rejalashtirish | Ishlab chiqarishni rejalashtirish, bron qilish, sotib olish so'rovlari/buyurtmalari, prognozlash. |
| Modellashtirish | Modellar, BOM, brendlar, kolleksiyalar, tasdiqlar. |
| Saqlash | Inventarizatsiya, etkazib beruvchilar, qabul qilish, bron qilish, xaridni qabul qilish, kuzatish. |
| Bichish | Yozuvlarni bichish, to'plamlar, ish haqini skanerlash, kuzatish. |
| Chop etish | Yozuvlarni, paketlarni chop etish, ish haqini skanerlash, kuzatish. |
| Tikuv | Tikuv yozuvlari, to'plamlar, ish haqini skanerlash, kuzatish. |
| Qadoqlash | Qadoqlash yozuvlari, paketlar, ish haqini skanerlash, kuzatish. |
| ReadyStorage | Saqlash paketlari, jo'natish, kuzatuv eksporti. |
| Chiqindi | Chiqindilarni qabul qilish / sotish / yo'q qilish. |
| Moliya | Moliyaviy ko'rinish, hisob-fakturalar, to'lovlar, sotib olish/ish haqi/prognoz ko'rinishi. |
| HR | Xodimlar, ish haqini ko'rish / boshqarish. |

## Data Console

Data Console faqat Super Admin uchun moʻljallangan va maʼlumotlar bazasi jadvallarini `/api/admin/super-data` orqali ochib beradi.

Imkoniyatlar:

1. Barcha jadvallarni sanab o'ting.
2. Qatorlar sonini ko'rish.
3. Qatorlarni qidirish.
4. Tahrirlanadigan ustunlarni tahrirlash.
5. Qatorlarni o'chirish.
6. Ustun turini, asosiy kalitni, tashqi kalitni, null boʻladigan, tahrirlanadigan metamaʼlumotlarni koʻrish.

Cheklovlar:

1. Birlamchi kalitlar faqat o'qish uchun mo'ljallangan.
2. Ikkilik ustunlar faqat o'qish uchun mo'ljallangan.
3. Bitta ustunli asosiy kalitsiz jadvallarni ushbu konsol orqali tahrirlash/oʻchirish mumkin emas.
4. Ma'lumotlar bazasi cheklovlari yangilanishlarni/o'chirishni bloklashi mumkin.
5. Super Data yangilanishlari va o'chirishlar audit jurnaliga olinadi.

Data Console xavfsizlik qoidalari:

1. Tuzatishlar uchun oddiy ERP sahifalariga ustunlik bering.
2. Data Console’dan faqat oddiy ish jarayoni mavjud bo‘lmaganda foydalaning.
3. Chet el kalitini tahrirlashdan oldin tegishli yozuvlarni tekshiring.
4. Hech qachon ishlab chiqarish yozuvlarini tasodifan o'chirmang.
5. Yozma ruxsatisiz moliyaviy, ish haqi yoki audit yozuvlarini tahrirlamang.
6. Xavfli ommaviy tuzatishdan oldin zaxira nusxasini oling yoki eksport qiling.
7. Bitta qatorni o'zgartiring, tasdiqlang va davom eting.
8. Sababini tashqi o'zgarishlar jurnalida yoki topshiriqda yozib oling.

## MCP Access

MCP Access faqat Super Admin uchun mo‘ljallangan va Milana ERP AI GM Assistant uchun sozlash tafsilotlarini ko‘rsatadi.

Sahifada ko'rsatilgan:

1. Server nomi.
2. Ko'rsatilgan nom.
3. ERP API bazasi URL.
4. Transport.
5. Python moduli.
6. Paket nomi.
7. Ish vaqti kirish qaydlari.
8. Atrof-muhit to'ldiruvchilari.
9. Klod ish stoli konfiguratsiyasi.
10. Asboblarni o'qing.
11. Yozish vositalari.
12. Xavfsizlik eslatmalari.
13. Bloklangan harakatlar.

MCP token qoidalari:

1. GM/Super Admin hisobi uchun haqiqiy ERP tokenidan faqat kerak bo'lganda foydalaning.
2. Skrinshotlar, chiptalar yoki chatga jonli hisobga olish ma'lumotlarini joylashtirmang.
3. Agar ochiq bo'lsa, token/parolni aylantiring.
4. MCP vositalari hali ham ERP API ruxsatlariga bo‘ysunadi.
5. Agar mahsulot egasi siyosatni aniq o‘zgartirmasa, bloklangan harakatlar bloklangan bo‘lishi kerak.

## Tizim sozlamalari

Super Admin sozlamalarni yangilashi mumkin:

1. Kompaniya nomi.
2. Kompaniya logotipi.
3. Manzil.
4. Telefon.
5. Elektron pochta.
6. Standart valyuta.
7. Moliyaviy yil boshlanish oyi.
8. Standart til.
9. Vaqt mintaqasi.
10. Model turi variantlari.
11. Bichishdan oldin materialni bron qilishni talab qiling.

Yuqori ta'sirli sozlash: bichishdan oldin materialni bron qilishni talab qiladi. Yoqilganda, BOM materiallari zahiraga olinmaguncha bichish bloklanishi mumkin. Uni faqat Saqlash, Rejalashtirish va Bichish o'rgatilgandan keyin yoqing.

## Audit va tergov

Audit jurnallarini qo'llab-quvvatlash:

1. Qidiruv.
2. Foydalanuvchi bo'yicha filtrlash.
3. Harakat bo'yicha filtrlash.
4. Ob'ekt turi bo'yicha filtrlash.
5. Ob'ekt identifikatori bo'yicha filtrlash.
6. Sana oralig‘i bo‘yicha filtrlash.
7. Tafsilotlarni oldingi/keyin qiymatlari bilan ko'rsatish.
8. Audit yaxlitligi ish oqimlari uchun xesh zanjiri eksporti/tasdiqlash yakuniy nuqtalari mavjud.

Tekshiruv jarayoni:

1. Ta'sir qilingan shaxs va identifikatorni aniqlang.
2. Ob'ekt va ID bo'yicha filtrlangan audit jurnallarini oching.
3. Xronologiyani ko‘rib chiqish.
4. Oldin/keyin qiymatlarni solishtiring.
5. Foydalanuvchi, harakat va asosiy sababni aniqlang.
6. Iloji bo'lsa, oddiy sahifadan foydalanib to'g'rilang.
7. Data Console’dan faqat oddiy sahifa uni tuzata olmasagina foydalaning.
8. Tuzatishni hujjatlashtiring.

## Muhim biznes jarayonlarini nazorat qilish

Super Admin to'liq zanjirni bilishi kerak:

1. Sotuv buyurtmasi.
2. Model/BOM tasdiqlash.
3. Rejalashtirish va ishlab chiqarish tartibi.
4. Moddiy zahiralar.
5. Xarid qilish so'rovlari/buyurtmalari/qabul qilish.
6. Yozuvlar va to'plamlarni bichish.
7. Chop etish/tikuv orqali skanerlash.
8. Tikuv yozuvlari va topshiriqlari.
9. Qadoqlash yozuvlari va paketlar.
10. Paket xotiraga skanerlanadi.
11. Yuk tashish paketini skanerlash.
12. Moliyaviy hisob-fakturalar/to'lovlar.
13. Ish haqini skanerlash/davrlar/tasdiqlash/to'lash.
14. Chiqindilarni qabul qilish / sotish / yo'q qilish.
15. Kuzatuv va audit tekshiruvi.

## Zaxiralash va qayta tiklash haqida xabardorlik

Super Admin ishlab chiqarishga tayyorlik, falokatdan qutqarish, xavfsizlikni taʼminlash kitobi, maxfiylik/saqlash va arxitektura hujjatlari qayerda joylashganligini bilishi kerak:

1. `docs/PRODUCTION_READINESS.md`
2. `docs/DISASTER_RECOVERY.md`
3. `docs/SECURITY_RUNBOOK.md`
4. `docs/PRIVACY_RETENTION.md`
5. `docs/ARCHITECTURE.md`

Xavfli ma'lumotlarga texnik xizmat ko'rsatishdan oldin, zaxira mavjudligi va qayta tiklash rejasini tasdiqlang.

## Xavfsizlik qoidalari

1. Kuchli parollardan foydalaning.
2. Imtiyozli hisoblarni baham ko'rmang.
3. Super Adminlar sonini minimal darajada saqlang.
4. Faol imtiyozli hisoblarni muntazam tekshirib turing.
5. Faol bo'lmagan imtiyozli hisoblarni o'chirib qo'ying.
6. Integratsiya tokenlarini himoya qiling.
7. Audit jurnallarini chetlab o'tmang.
8. Internetga kirishda HTTPS/ommaviy tarqatish xavfsizlik sozlamalaridan foydalaning.
9. Demo foydalanuvchilarini ishlab chiqarishga qo'ymang.
10. Ishlab chiqarishda namuna ma'lumotlarini yoqmang.

## Super Admindan qachon foydalanish kerak

Quyidagilar uchun Super Admindan foydalaning:

1. Admin/Super Admin ruxsatini yaratish yoki tuzatish.
2. MCP sozlamalari ko‘rilmoqda.
3. Favqulodda ma'lumotlar konsolini tuzatish.
4. Muhim audit yoki ma'lumotlar yaxlitligi muammolarini tekshirish.
5. Tizim darajasidagi sozlamalar.
6. Qayta tiklashni muvofiqlashtirish.

Super Admindan quyidagilar uchun foydalanmang:

1. Oddiy sotuvga kirish.
2. Oddiy ishlab chiqarish chiqishi.
3. Oddiy ish haqini skanerlash.
4. Muntazam qabul qilish.
5. Departament roli xavfsiz bajarishi mumkin bo'lgan har qanday harakat.

## Super Admin Kundalik/Haftalik nazorat ro'yxati

Kundalik:

1. Tizimning sog'lig'ini va kirish mavjudligini tekshiring.
2. Shoshilinch kirish so'rovlarini ko'rib chiqing.
3. Muvaffaqiyatsiz yoki bloklangan muhim jarayonlarni ko'rib chiqing.
4. Imtiyozli hisob o'zgarishlarini tekshiring.
5. Yechilmagan ustuvor vazifalarni ko'rib chiqing.

Haftalik:

1. Admin/Super Admin foydalanuvchilarini ko'rib chiqing.
2. Tizimdan foydalanmayotgan foydalanuvchilarni ko'rib chiqing.
3. O'chirish va imtiyozli o'zgarishlar uchun audit jurnallarini ko'rib chiqing.
4. Zaxira holatini tekshiring.
5. Sozlamalardagi o'zgarishlarni ko'rib chiqing.
6. Integratsiya holatini ko'rib chiqing.
7. Bo'lim rahbarlari bilan o'quv bo'shliqlarini tasdiqlang.

## Favqulodda vaziyatni tuzatish ro'yxati

1. Agar kerak bo'lsa, ta'sirlangan jismoniy jarayonni to'xtating.
2. Aniq yozuvlar va identifikatorlarni aniqlang.
3. Audit jurnallarini ko'rib chiqing.
4. Bo'lim egasi bilan kerakli tuzatishni tasdiqlang.
5. Oddiy sahifani tuzatishni afzal ko'ring.
6. Agar Data Console kerak bo'lsa, bir vaqtning o'zida bir qatorni tahrirlang.
7. Pastki oqim yozuvlarini tekshiring.
8. Tuzatishni tavsiflovchi vazifa/eslatma qo'shing.
9. Ta'sir qilingan bo'limlarni xabardor qiling.

## Umumiy Super Admin Xatarlari

| Xavf | Oldini olish |
| --- | --- |
| Bog'langan ishlab chiqarish ma'lumotlarini tasodifan o'chirish | Oddiy sahifalarni afzal ko'ring; avval chet el kalitlari va zaxira nusxalarini tekshiring. |
| Haddan tashqari ruxsat berish | Eng kam imtiyoz va rolga asoslangan kirishdan foydalaning. |
| Ishlab chiqarishda demo hisob ma'lumotlari | `SEED_DEMO_USERS=false`-ni saqlang va kuchli boshlang'ich administrator parolini o'rnating. |
| Ochiq MCP/API tokeni | Hisob ma'lumotlarini darhol aylantiring. |
| Bichish kutilmaganda bloklandi | Materialni bron qilish sozlamalari va bron holatini tekshiring. |
| Tasdiqlashdan oldin to'langan ish haqi | Davr holati oqimini joriy qilish: ochiq -> qulflangan -> tasdiqlangan -> to'langan. |
| Moliyaviy qadriyatlar noto'g'ri | BOM, zaxira xarajatlari, ishlab chiqarish ishlab chiqarish, paket xarajatlari va ish haqi manbasi ma'lumotlarini tasdiqlang. |
