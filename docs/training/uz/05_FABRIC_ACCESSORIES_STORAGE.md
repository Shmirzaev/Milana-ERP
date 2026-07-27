# Mato va furnitura ombori bo'yicha o'quv qo'llanma

Versiya: 1.0
Sana: 2026-07-02
Bo'lim kodi: STR
Birlamchi rol: Saqlash

## Maqsad

Mato va furnitura ombori xomashyo, aksessuarlar, qadoqlash materiallari, etkazib beruvchilar, inventar partiyalari, harakatlar va materiallarni bron qilishni qo'llab-quvvatlashga ega.

## Bosh sahifalar

- Materiallar inventarizatsiyasi
- Aksessuarlar inventarizatsiyasi
- Asosiy ma'lumotlar
- Birjani qabul qilish
- Partiyalar
- Xaridni qabul qilish
- Ishlab chiqarish buyurtmasi tafsilotlari bo'yicha rezervasyonlarni rejalashtirish
- Kuzatish imkoniyati

## Asosiy ruxsatlar

- `storage.receive`
- `storage.transfer`
- `storage.items`
- `storage.suppliers`
- `inventory.reservations.view`
- `inventory.reservations.create`
- `inventory.reservations.release`
- `inventory.reservations.consume`
- `purchasing.view`
- `purchasing.receive`
- `traceability.view`
- `traceability.export`

## Kundalik ish jarayoni

1. Kutilayotgan xaridlarni tekshiring va Xaridlarni qabul qilish liniyalarini oching.
2. To'g'ri omborga jismoniy zaxiralarni qabul qiling.
3. Inventarizatsiya ob'ekti asosiy ma'lumotlarini va yetkazib beruvchi ma'lumotlarini saqlang.
4. Birja partiyalari va QC holatini ko'rib chiqing.
5. Rezervasyon etishmovchiligi bilan rejalashtirishni qo'llab-quvvatlash.
6. Materiallar omborlar yoki qavatlar o'rtasida harakatlanayotganda zaxiralarni o'tkazing.
7. To'plamlar va kuzatuvlar orqali birja savollarini o'rganing.

## Stokni qo'lda qabul qilish

Buyurtmani qabul qilish oqimi orqali materiallar kelib tushmasa, "Qabul qilish zaxirasi" dan foydalaning.

1. Elementni tanlang.
2. Yetkazib beruvchini tanlang.
3. Omborni tanlang.
4. To'plam raqamini kiriting.
5. Miqdor va birlikni kiriting.
6. Bir birlik narxini kiriting.
7. Agar kerak bo'lsa, rang, kenglik, GSM yoki boshqa to'plam tafsilotlarini kiriting.
8. QC holatini o'rnating.
9. Qabul qilishni saqlang.

## Xaridni qabul qilish

Xarid buyurtmasi mavjud bo'lganda:

1. Xaridni qabul qilishni oching.
2. To'g'ri Buyurtma liniyasini tanlang.
3. Faqat kelgan jismoniy miqdorni oling.
4. Partiya raqamini, omborni, yetkazib beruvchini va narxini kiriting.
5. Saqlash.
6. Yangi partiyaning To'plamlar/Inventarda paydo bo'lishini tasdiqlang.

## Asosiy ma'lumotlar

Master Data inventar ob'ektlari va etkazib beruvchilarni nazorat qiladi.

Inventarizatsiya ro'yxati:

1. SKU noyobdir.
2. Ism aniq.
3. Turkum toʻgʻri: mato, aksessuar, qadoqlash, chiqindi yoki boshqa sozlangan toifa.
4. Birlik to'g'ri.
5. Standart narx o'rtacha.
6. Kuzatilishi kerak bo'lgan elementlar uchun to'plamni kuzatish yoqilgan.

Yetkazib beruvchining nazorat ro'yxati:

1. Yetkazib beruvchining nomi rasmiy.
2. Aloqa ma'lumotlari dolzarb.
3. Takroriy etkazib beruvchilardan qoching.

## Rezervasyonni qo'llab-quvvatlash

Saqlash zaxirani rejalashtirish va zaxiralarni chiqarishga yordam beradi.

1. Ishlab chiqarish buyurtmasi tafsilotlari bo'yicha bron rejasini ko'rib chiqing.
2. Kerakli, zahiradagi, qolgan, mavjud va etishmayotgan miqdorlarni tekshiring.
3. Haqiqiy zaxira joylashuvi va QCni tasdiqlang.
4. Agar zaxira mavjud bo'lsa, lekin zahiraga qo'yilmasa, birliklarni, SKU elementini yoki partiya holatini tekshiring.
5. Rejalashtirish kerak emasligini tasdiqlagandagina bandlovlarni chiqaring.

## To'plam sifati

To'plam ma'lumotlari ishlab chiqarish narxiga va kuzatilishiga ta'sir qiladi. Har doim tasdiqlang:

1. Partiya raqami.
2. Element/SKU.
3. Miqdori va birligi.
4. Rang/kenglik/GSM mavjud bo'lganda.
5. Ombor.
6. Yetkazib beruvchi.
7. Narxi.
8. QC holati.

## Umumiy muammolar

| Muammo | Mumkin sabab | Harakat |
| --- | --- | --- |
| Rejalashtirish kamchilikni ko'radi, ammo zaxira mavjud | Noto'g'ri mahsulot, birlik, ombor, zaxiralangan miqdor yoki QC | Rezervasyon elementini aksiyalar partiyasi tafsilotlari bilan solishtiring. |
| Xarajat hisoboti noto'g'ri | Qabul qilish narxi noto'g'ri kiritilgan | Hisobotlar yakunlanishidan oldin moliya/administratorga xabar bering. |
| Partiya bichish uchun mavjud emas | Rezervasyon mavjud emas yoki zaxira holati noto‘g‘ri | Rezervasyon va aktsiyalarning harakatini ko'rib chiqing. |
| SKU nusxasi | Asosiy ma'lumotlar xatosi | Takroriy nusxadan foydalanishni to'xtating va Administrator/Saqlash boshqaruvchisini tuzatishni so'rang. |
