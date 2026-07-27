# O'quv qo'llanma sotib olish

Versiya: 1.0
Sana: 2026-07-02
Bo'lim: Ruxsatga qarab, odatda rejalashtirish, saqlash, moliya yoki boshqaruv tomonidan boshqariladigan sotib olish ish jarayoni

## Maqsad

Xarid qilish material tanqisligi yoki qo'lda zaxiraga bo'lgan ehtiyojni tasdiqlangan sotib olish so'rovlariga, xarid buyurtmalariga va olingan zaxiralarga aylantiradi.

## Bosh sahifalar

- Sotib olish
- Xaridni qabul qilish
- Rejalashtirish paneli
- Materiallar inventarizatsiyasi
- Aksessuarlar inventarizatsiyasi
- Yetkazib beruvchilar
- Inventar to'plamlari

## Asosiy ruxsatlar

- `purchasing.view`
- `purchasing.request`
- `purchasing.approve`
- `purchasing.order`
- `purchasing.receive`
- `storage.suppliers`
- `storage.receive`

## Xarid qilish sahifasi ish jarayoni

Xarid qilish sahifasida etishmovchilik qatorlari va xarid so'rovlari ko'rsatiladi.

Undan foydalaning:

1. Rejalashtirishga tayyor Sotuv Buyurtmalari uchun kamchiliklarni ko'rib chiqing.
2. Savdo buyurtmasi etishmasligidan so'rov yarating.
3. Element uchun qo'lda so'rov yarating.
4. Xarid so'rovlarini tasdiqlash yoki rad etish.
5. Tasdiqlangan so'rovlarni xarid buyurtmalariga aylantiring.
6. Xaridni qabul qilishni oching.

## Kamchilikdan so'rov yaratish

1. Ochiq xarid qilish.
2. Kamchilik qatorlarini ko'rib chiqing: buyurtma raqami, SKU, mahsulot nomi, kerakli miqdor, mavjud miqdor, etishmovchilik va birlik.
3. Kamchilik uchun so'rov yaratish-ni tanlang.
4. Yaratilgan so'rov raqamini tasdiqlang.
5. Tasdiqlash zarur bo'lsa, tasdiqlovchini xabardor qiling.

## Qo'lda so'rov yaratish

1. Ochiq xarid qilish.
2. Elementni tanlang.
3. So'ralgan miqdorni kiriting.
4. Tizim tomonidan ko'rsatilgan mavjud miqdorni ko'rib chiqing.
5. Ma'lum bo'lganda afzal ko'rgan yetkazib beruvchini tanlang.
6. Eslatmalar qo'shing.
7. So'rov yaratish.

Savdo buyurtmasi etishmasligi bilan bog'liq bo'lmagan zaxira ehtiyojlari uchun qo'lda so'rovlardan foydalaning.

## Tasdiqlash va buyurtmani konvertatsiya qilish

Tasdiqlovchilar:

1. Kamchilik yoki biznes sababini tasdiqlang.
2. Yetkazib beruvchini va miqdorini tekshiring.
3. So'rovni tasdiqlash yoki rad etish.
4. Agar xarid siyosati talab qilsa, ERP tashqari aloqani qo'shing.

Xarid qilish/buyurtma beruvchi foydalanuvchilar:

1. Tasdiqlangan so'rovlarni Xarid qilish buyurtmalariga aylantiring.
2. Yetkazib beruvchi va xarajat tafsilotlari to'g'riligini tasdiqlang.
3. Qabul qilinmaguncha ochiq xarid buyurtmalarini kuzatib boring.

## Xaridni qabul qilish ish jarayoni

1. Xaridni qabul qilishni oching.
2. Buyurtmaning kutilayotgan qatorlarini ko‘rib chiqing.
3. To'g'ri qatorda "Qabul qilish" ni tanlang.
4. Qabul qilingan miqdorni kiriting.
5. To'plam raqamini kiriting.
6. Saqlash omborini tanlang.
7. Agar o'rnatilmagan bo'lsa, yetkazib beruvchini tanlang.
8. Bir birlik narxini kiriting.
9. Qabul qilishni saqlang.

Qabul qilish inventar zaxiralarini hosil qiladi. Noto'g'ri xarajat, partiya yoki ombor inventarizatsiya va moliyaga ta'sir qiladi.

## Qabul qilish qoidalari

1. Faqat jismonan kelgan materialni oling.
2. Sotib olish siyosati ortiqcha qabul qilishga ruxsat bermaguncha va tizim uni qo'llab-quvvatlamasa, qolgan miqdordan ko'proq olmang.
3. Yordamchi bo'lsa, eslatmalarda etkazib beruvchini etkazib berish hujjati raqami yoki partiya raqamidan foydalaning.
4. Barqaror partiya raqamlaridan foydalaning.
5. Ombor amaliyotiga ko'ra, shubhali tovarlarni QC holatiga yuboring.

## Status ma'nosi

| Status | Ma'nosi |
| --- | --- |
| qoralama/tasdiqlanishni kutmoqda | So'rov tasdiqlashni kutmoqda. |
| tasdiqlangan | So'rov buyurtmaga aylantirilishi mumkin. |
| rad etilgan | So'rov buyurtma qilinmasligi kerak. |
| aylantirildi | So'rov xarid buyurtmasiga aylandi. |
| yuborilgan/tasdiqlangan | Buyurtmani xarid qilish mumkin. |
| qisman_qabul qilingan | Qabul qilingan miqdorning bir qismi hali ham ochiq. |
| olingan | Buyurtma to'liq qabul qilindi. |
| bekor qilingan | Xarid qilish buyurtmasi endi faol emas. |

## Umumiy muammolar

| Muammo | Mumkin sabab | Harakat |
| --- | --- | --- |
| Kamchiliklar ko'rsatilmagan | Rejalashtirishga tayyor tanqislik yoki talablar hisoblanmagan | Rejalashtirishdan materialga bo'lgan talablarni ko'rib chiqishni so'rang. |
| Tasdiqlash mumkin emas | Missing `purchasing.approve` | Ruxsatni tekshirish uchun administrator/boshqaruvdan so‘rang. |
| Qabul qilish mumkin emas | `purchasing.receive` yo‘q yoki ochiq PO liniyasi yo‘q | Ruxsat va Buyurtma holatini tekshiring. |
| Noto'g'ri ombor tanlangan | Inson tanlash xatosi | Zaxiradan foydalanishdan oldin darhol Saqlash/Administratorga xabar bering. |
| Takroriy so'rov | Xuddi shu etishmovchilik ikki marta so'ralgan | Tasdiqlovchi takroriy yoki muvofiqlashtiruvchi tuzatishni rad qilishi kerak. |
