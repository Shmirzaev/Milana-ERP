# Bichish bo'yicha o'quv qo'llanma

Versiya: 1.0
Sana: 2026-07-02
Bo'lim kodi: CUT
Standart rol: Bichish

## Maqsad

Bichish ajratilgan matoni kesilgan qismlarga va kuzatilishi mumkin bo'lgan to'plamlarga aylantiradi. Bichish aniqligi ishlab chiqarishning qolgan qismini nazorat qiladi, chunki Chop etish va tikish to'g'ri yaratilmagan va yuborilmagan to'plamlarni qabul qila olmaydi.

## Bosh sahifalar

- Qavatni bichish
- Ishni bichish tartibi
- Pasportlarni bichish
- Inventar to'plami
- To'plamlar
- Skanerlash to'plami
- Jarayonni kuzatish
- Kuzatish imkoniyati

## Asosiy ruxsatlar

- `cutting.records`
- `cutting.bundles`
- `inventory.reservations.view`
- `payroll.scan`
- `traceability.view`

## Kundalik ish jarayoni

1. Ochiq bichish pol.
2. Kiruvchi / kutilayotgan ishni ko'rib chiqing.
3. To'g'ri bichish ish tartibini oching.
4. Mahsulot ma'lumotlarini, modeli, tartibi, rangi, o'lchami, rejalashtirilgan miqdori va bron holatini tekshiring.
5. Buyurtma paketli bo'lsa, to'g'ri ishlab chiqarish partiyasini tanlang.
6. Mato partiyasini tanlang.
7. Kirish mato miqdori va birligini kiriting.
8. Kesilgan qismlarni kiriting.
9. Chiqindilarning miqdori va birligini kiriting.
10. To'plam rejasini ko'rib chiqing yoki tahrirlang.
11. Saqlash va to'plamlarni yaratish.
12. To'plam teglarini chop eting.
13. Scan Bundle yordamida toʻplamlarni Chop etish yoki Tikuvga yuboring.

## Bichishni boshlashdan oldin

Tasdiqlash:

1. Ish tartibi to'g'ri ishlab chiqarish buyurtmasiga tegishli.
2. Model va o'lchamdagi taqsimot jismoniy marker/bichish rejasiga mos keladi.
3. Materialni band qilish tayyor yoki davom etish uchun tasdiqlangan.
4. Mato partiyasi jismoniy ishlatiladigan materialga mos keladi.
5. Bichish stoli miqdori rejalashtirilgan partiya/buyurtma miqdoriga mos keladi.
6. Chop etish talabi ma'lum.
7. Tikuv fabrikasining manzili to'g'ri: Milana yoki Besttex.

## Bichish ichidagi partiyani rejalashtirish

Agar Rejalashtirish buyurtmani oldindan ajratmagan bo'lsa, Bichish ruxsat berilganda ish tartibi ichida partiyalarni belgilashi mumkin.

1. To'plam uchun maksimal qismlardan foydalaning.
2. Avtomatik ajratish yoki ommaviy qatorlarni qo'lda qo'shish.
3. Partiya nomini, miqdorini, boshlanish sanasini, oxirgi sanani va eslatmalarni kiriting.
4. Paket rejasini saqlang.
5. Partiyalar mavjud bo'lgandan so'ng, chiqib ketish chiqishini saqlashdan oldin to'g'ri partiyani tanlang.

Kamchilikni yashirish yoki qayta ishlash uchun partiyani bo'lishdan foydalanmang. Bu ishlab chiqarishni rejalashtirish va kuzatish uchun mo'ljallangan.

## Chiqib ketishni yozish

Majburiy maydonlar:

1. Ishlab chiqarish partiyasi, agar buyurtma partiyali bo'lsa.
2. Mato to'plami.
3. Kirish miqdori va birligi.
4. Bo'laklarni kesib oling.
5. Chiqindilarning miqdori va birligi.
6. To'plam rejasi.
7. Noodatiy narsa sodir bo'lganda qayd etiladi.

Tizim kesilgan qismlarni quyi oqim to'plamini yaratish uchun uzatilgan qismlar sifatida ko'rib chiqadi.

## To'plam rejasi

To'plam rejasi qatorlariga quyidagilar kiradi:

1. Rang.
2. Hajmi.
3. Bir to'plam uchun dona.
4. To'plamlar soni.
5. Tikuv fabrikasi.
6. Keyingi bo'lim: Chop etish yoki tikuvchilik.

To'plam miqdori va soni haqiqiy kesilgan qismlarga mos kelishi kerak. Agar buyurtma chop etishni o'z ichiga olsa, Chop etish xizmatiga yuboring. Agar chop etish kerak bo'lmasa, to'g'ri tikuv fabrikasiga yuboring.

## Yorliqlarni chop etish

Saqlagandan keyin:

1. Yaratilgan to'plamlar ro'yxatini ko'rib chiqing.
2. Barcha teglarni chop eting yoki alohida teglarni chop eting.
3. Har bir yorliqni darhol to'g'ri jismoniy to'plamga biriktiring.
4. To'plam yorliqlarini ko'rinadigan va himoyalangan holda saqlang.

Agar yorliq shikastlangan bo'lsa, uni yaratilgan to'plamlar ro'yxatidan yoki To'plamlar sahifasidan qayta chop eting. Yorliqni almashtirish uchun dublikat to'plam yaratmang.

## Bundle Scan Handoff

Harakat qilish uchun Scan Bundle-dan foydalaning.

1. To'plam shtrix kodini skanerlang yoki kiriting.
2. To'plam raqami, modeli, rangi, o'lchami, miqdori, joriy bo'lim, keyingi bo'lim va tikuv fabrikasini tasdiqlang.
3. Agar holat `created` bo‘lsa va keyingisi Pechat bo‘lsa, Chop etish uchun yuborish-ni tanlang.
4. Agar holat `created` bo‘lsa va keyingisi tikuv fabrikasi bo‘lsa, mavjud amal bo‘yicha Zavodga yuborish/qabul qilish ni tanlang.
5. O'zgartirilgan holatni tasdiqlang.

## Chiqindilarni yozib olish

Chiqindilarni bichish halol va o'z vaqtida bo'lishi kerak.

1. Bichish paytida chiqindilar miqdorini kiriting.
2. Noodatiy chiqindilar uchun eslatmalardan foydalaning.
3. Chiqindi bo'limi tartibiga muvofiq jismoniy chiqindilarni yuboring.
4. Ishlab chiqarishni yaxshilash uchun chiqindilarni kamaytirmang.

## Ish haqini skanerlash

Agar bichish operatsiyalari ish haqi QR belgilaridan foydalansa:

1. Avval xodim QR-ni skanerlang.
2. QR ish/jarayonini skanerlang.
3. Xodimni, operatsiyani, miqdorni va stavkani tekshiring.
4. Zarur bo'lganda ish haqi yozuvlarini saqlang.

## Shift oxiri nazorat ro'yxati

1. Barcha kesilgan ishlar saqlanadi.
2. Barcha yaratilgan to'plamlarda teglar mavjud.
3. Jismoniy toʻplamlar ERP toʻplamlar soniga mos keladi.
4. Oldinga yuborilgan paketlar skanerdan oʻtkazildi.
5. Chiqindilar qayd etiladi.
6. Bloklangan yoki etishmayotgan ish haqida xabar berilgan.

## Umumiy muammolar

| Muammo | Mumkin sabab | Harakat |
| --- | --- | --- |
| Bichish yozuvini saqlab bo'lmadi | Kerakli partiya/mato/miqdor yoki bandlov bloki yetishmayapti | Kerakli maydonlarni va bron holatini tekshiring. |
| To'plam noto'g'ri | To'plam rejasi kesilgan qismlarga mos kelmaydi | Saqlashdan oldin rejani toʻgʻrilang yoki agar saqlangan boʻlsa, rahbardan soʻrang. |
| Chop etish to‘plamni qabul qila olmaydi | Bichish to‘plamni Chop etish xizmatiga yubormadi | To'plamni skanerlang va Chop etish xizmatiga yuboring. |
| Tikuv to'plamni qabul qila olmaydi | Keyingi bo'lim/zavod to'plami noto'g'ri yoki yuborilmagan | Toʻplam tafsilotlarini tekshiring va boradigan joy notoʻgʻri ekanligini nazoratchidan soʻrang. |
