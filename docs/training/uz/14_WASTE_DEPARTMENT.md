# Chiqindi bo'limi o'quv qo'llanma

Versiya: 1.0
Sana: 2026-07-02
Bo'lim kodi: WST
Standart rol: chiqindi

## Maqsad

Chiqindi bo'limi ishlab chiqarish chiqindilarini qayd qiladi, qabul qiladi, sotadi yoki yo'q qiladi. Chiqindilarni hisobga olish boshqaruvga yo'qotishlarni tushunishga, sotiladigan chiqindilardan qiymatni tiklashga va sotilmaydigan chiqindilarni utilizatsiya qilishga ruxsat berishga yordam beradi.

## Bosh sahifalar

- Chiqindilarni boshqarish paneli
- Chiqindilarni tanlash uchun materiallar/elementlar ro'yxati
- Manba bo'limini tanlash uchun bo'limlar ro'yxati
- Moliyaviy chiqindilar to'g'risidagi hisobot, Moliya/Menejment tomonidan o'qiladi

## Asosiy ruxsatlar

- `waste.receive`
- `waste.sell`
- `waste.disposal`

## Kundalik ish jarayoni

1. Chiqindilarni boshqarish panelini oching.
2. Sotuv mumkin bo'lgan va sotilmaydigan chiqindilarni ko'rib chiqing.
3. Agar sizning jamoangiz to'g'ridan-to'g'ri chiqindilar rekordini yaratsa, chiqindilarni yozib oling.
4. Chiqindilarni manba bo'limidan jismoniy qabul qiling.
5. Mahalliy tartib bilan tasdiqlanganda sotiladigan chiqindilarni soting.
6. Sotilmaydigan chiqindilarni utilizatsiya qilishni talab qiling.
7. Belgilanish faqat tasdiqlangandan va jismoniy utilizatsiya qilinganidan keyin utilizatsiya qilinadi.

## Yozib olish chiqindilari

Maydonlar:

1. Element.
2. Manba bo'limi.
3. Chiqindilarning turi.
4. Miqdori.
5. Birlik.
6. Sotiladigan katakcha.
7. Sabab, jarayon talab qilganda.

Jismoniy son / vazndan foydalaning. Nazoratchi ruxsat bermasa, baholamang.

## Chiqindilarni qabul qilish

1. Chiqindilarni qayd etishni jismoniy chiqindilar bilan moslang.
2. Manba bo'limi va chiqindilar turini tasdiqlang.
3. Miqdor va birlikni tasdiqlang.
4. Qabul qilish-ni tanlang.
5. Jismoniy chiqindilarni chiqindi hududida saqlang.

## Sotiladigan chiqindilarni sotish

1. Chiqindilarning holati chiqindilar bo'limi tomonidan qabul qilinganligini tasdiqlang.
2. Chiqindilarni sotish mumkin deb belgilanishini tasdiqlang.
3. Mahalliy tasdiqlash jarayoniga muvofiq xaridor va narxni tasdiqlang.
4. Sotuv-ni tanlang.
5. Moliya uchun savdo hujjatlarini saqlang.

## Sotilmaydigan chiqindilar uchun utilizatsiya

1. Chiqindilarning holati chiqindilar bo'limi tomonidan qabul qilinganligini tasdiqlang.
2. Chiqindilarni sotish mumkin emasligini tasdiqlang.
3. Utilizatsiya qilishni so'rash-ni tanlang.
4. Sababini kiriting.
5. Boshqaruv roziligini kuting.
6. Tasdiqlash va jismoniy utilizatsiya qilingandan so'ng, utilizatsiya qilingan deb belgilang.

Sotuv mumkin bo'lmagan chiqindilar ruxsat olishdan oldin utilizatsiya qilinmasligi kerak.

## Status ma'nosi

| Status | Ma'nosi |
| --- | --- |
| qayd etilgan | Chiqindilar jurnalga kiritilgan, ammo chiqindilar bo'limi tomonidan hali qabul qilinmagan. |
| chiqindi_bo'limi tomonidan qabul qilingan | Chiqindilar departamenti jismoniy chiqindilarni qabul qildi. |
| sotilgan | Sotuv mumkin bo'lgan chiqindilar sotildi. |
| kutilayotgan_tasdiqlash | Utilizatsiya so'ralgan va boshqaruv kutilmoqda. |
| disposal_tasdiqlangan | Rahbariyat tomonidan ruxsat etilgan utilizatsiya. |
| tasarruf qilingan | Chiqindilar jismonan utilizatsiya qilindi va ERP yangilandi. |

## Umumiy muammolar

| Muammo | Mumkin sabab | Harakat |
| --- | --- | --- |
| Chiqindilarning miqdori jismoniy chiqindilarga mos kelmaydi | Manba bo'limiga kirish xatosi | Qabul qilishdan oldin manba rahbaridan tasdiqlashini so'rang. |
| Sotuv mumkin emas | Chiqindi olinmaydi yoki sotilmaydi | Nazoratchi/administrator orqali birinchi yoki to'g'ri sotiladigan bayroqni oling. |
| Tashlab bo'lmaydi | Boshqaruvning ruxsati yoʻq | Tasdiqlashni so'rang va kuting. |
| Moliyaviy hisobotning mos kelmasligi | Sotuv/utilizatsiya to'g'ri qayd etilmagan | Chiqindilarning holati va sotish hujjatlarini ko'rib chiqing. |
