# Chop etish bo'yicha o'quv qo'llanma

Versiya: 1.0
Sana: 2026-07-02
Bo'lim kodi: PRT
Standart rol: Chop etish

## Maqsad

Chop etish Bichishdan to‘plamlarni qabul qiladi, mijozning chop etish ko‘rsatmalariga amal qiladi, chop etilgan mahsulotni yozib oladi va rad etadi, so‘ngra to‘plamlarni Tikuvga yuboradi.

## Bosh sahifalar

- Bosib chiqarish uchun zamin
- Chop etish uchun buyurtma
- Skanerlash to'plami
- Jarayonni kuzatish
- Kuzatish imkoniyati

## Asosiy ruxsatlar

- `printing.records`
- `printing.bundles`
- `payroll.scan`
- `traceability.view`

## Kundalik ish jarayoni

1. Chop etish qavatini oching.
2. Kiruvchi/kutilayotgan chop etish ishlarini ko'rib chiqing.
3. Scan Bundle yordamida paketlarni qabul qiling.
4. Chop etish ishiga buyurtmani oching.
5. Agar ish buyurtmasini yig'ish kerak bo'lsa, rejani belgilangan muddatda boshlash/qabul qilish uchun "To'plash" dan foydalaning.
6. Savdo buyurtmalarini chop etish bo'yicha ko'rsatmalar va qo'shimchalarni ko'rib chiqing.
7. Kirish, chop etilgan chiqish, rad etilgan miqdor, chop etish turi, nuqson sababi va eslatmalarni yozib oling.
8. Chop etish yozuvini saqlang.
9. Scan Bundle yordamida toʻplamlarni tikuvga yuboring.

## To'plamlarni qabul qilish

1. Chop etish uchun skanerlash paketini oching.
2. To'plam shtrix kodini skanerlash.
3. Holatni tasdiqlang: `sent_to_printing`.
4. Chop etishda qabul qilish-ni tanlang.
5. Tasdiqlash holati chop etilganda qabul qilinadi.

Qabul qilish tugmasi mavjud bo'lmasa, Bichish, ehtimol, to'plamni Chop etish uchun yubormagan yoki to'plam noto'g'ri holatda.

## Chop etish ishlarini yig'ish

Ba'zi Chop etish ishlariga buyurtmalar chiqishni yozib olishdan oldin to'planishi kerak.

1. Chop etish ishiga buyurtmani oching.
2. Joriy holat va muddatni ko'rib chiqing.
3. Agar kerak bo'lsa, oxirgi muddat va eslatmalarni kiriting.
4. Yig'ish-ni tanlang.
5. Chop etishni faqat ish buyurtmasi bajarilgandan keyin yozib oling.

## Chop etish bo'yicha ko'rsatmalar

Chop etish bo'yicha ish tartibi quyidagilarni ko'rsatishi mumkin:

1. Bosib chiqarishni talab qiluvchi Savdo Buyurtma satrlari.
2. Model / rang / o'lcham / miqdor.
3. Mijoz eslatmalari.
4. Chop etish bo'yicha ko'rsatmalar.
5. Yuklangan rasm/PDF/san'at fayllari.

Ko'rsatmalar tushunarsiz bo'lsa chop qilmang. Davom etishdan oldin sotish yoki rejalashtirishdan so'rang.

## Yozib olish Chop etish chiqishi

Maydonlar:

1. Agar buyurtma bo'lsa, ishlab chiqarish partiyasi.
2. Kirish miqdori.
3. Chop etilgan/chiqish miqdori.
4. Rad etilgan miqdor.
5. Chop etish turi.
6. Kamchilik sababi.
7. Eslatmalar.

Chiqish miqdori quyi oqim tikuvi uchun o'tgan miqdor sifatida qabul qilinadi.

## Tikuvga yuborish

1. Chop etish uchun skanerlash paketini oching.
2. Har bir chop etilgan to'plamni skanerlang.
3. Holatni tasdiqlang: `received_printing`.
4. Tikuvga/zavodga yuborish-ni tanlang.
5. Joriy/keyingi bo'lim to'g'ri o'zgartirilganligini tasdiqlang.

## Sifat qoidalari

1. Yozishdan oldin chop etilgan qismlarni hisoblang.
2. Darhol rad etishni yozib oling.
3. Takroriy muammolar uchun nuqson sababidan foydalaning.
4. Chop etilgan va chop etilmagan to'plamlarni alohida saqlang.
5. Chop etilmagan yoki rad etilgan qismlarni o'tkazilgan natija sifatida yubormang.

## Ish haqini skanerlash

Agar ish haqi QR belgilaridan foydalanilsa:

1. Avval xodim QR-ni skanerlang.
2. Ishni skanerlash/QR jarayoni.
3. Ishlash va miqdorni tasdiqlang.
4. Zarur bo'lganda, ish haqi yozuvini saqlang.

## Umumiy muammolar

| Muammo | Mumkin sabab | Harakat |
| --- | --- | --- |
| Toʻplamni qabul qilib boʻlmadi | Bichish uni yubormadi | Skanerlash/yuborish uchun Cutting-dan so‘rang. |
| Chiqish shakli qulflangan | Ishga buyurtma olinmadi/davom etmayapti | Agar ruxsat berilsa, Collect-dan foydalaning. |
| Noto'g'ri chop etish fayli | Savdo noto'g'ri yoki eski fayl yuklangan | To'xtating va Savdo / Rejalashtirishni so'rang. |
| Tikuv qabul qila olmaydi | Chop etish to‘plamni tikuvchilikka yubormadi | To'plamni skanerlang va oldinga yuboring. |
