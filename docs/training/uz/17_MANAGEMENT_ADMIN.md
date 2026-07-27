# Rahbariyat / Administrator uchun o'quv qo'llanma

Versiya: 1.0
Sana: 2026-07-02
Bo'lim kodi: ADM
Birlamchi rollar: Boshqaruv, Administrator

## Maqsad

Rahbariyat biznes jarayonini kuzatib boradi va istisnolarni tasdiqlaydi. Administrator foydalanuvchilar, bo'limlar, audit tekshiruvi, sozlamalar va operatsion tuzatishlar kabi oddiy ilovalar boshqaruvini boshqaradi. Super Admin alohida hujjatlashtirilgan qo'shimcha boshqaruvga ega.

## Bosh sahifalar

- Boshqaruv paneli
- Jarayonni kuzatish
- Kuzatish imkoniyati
- Prognozlash
- Ish haqi to'g'risidagi xulosa
- Foydalanuvchilar
- Bo'limlar
- Xodimlar
- Audit jurnallari
- Sozlamalar
- Chiqindilarni boshqarish paneli
- Modellar
- Ishlab chiqarish buyurtmalari
- Vazifalar va bildirishnomalar

## Boshqaruv kalitiga ruxsatlar

- `management.view`
- `management.approve`
- `finance.view`
- `admin.audit`
- `tasks.manage`
- `processes.view`
- `sewing.flows`
- `traceability.view`
- `traceability.export`
- `forecasting.view`
- `forecasting.manage`
- `payroll.view`
- `payroll.manage`
- `payroll.approve`
- `purchasing.approve`
- `production.override_deadline`

## Administrator kaliti ruxsati

- `*`

Administrator roli ilovaga toʻliq kirish huquqiga ega. Administrator foydalanuvchilari sonini kam tuting.

## Kundalik boshqaruv ish jarayoni

1. Boshqaruv panelidagi KPIlarni ko'rib chiqing.
2. Muddati o'tgan yoki bloklangan buyurtmalar uchun jarayonni kuzatishni ko'rib chiqing.
3. Ishlab chiqarishdagi qiyinchiliklarni bosqichma-bosqich ko'rib chiqing.
4. Chiqindilarni, moliya va ish haqi signallarini ko'rib chiqing.
5. Chiqindilarni yo'q qilish bo'yicha so'rovlarni tasdiqlash yoki rad etish.
6. Tayyor bo'lgach, ish haqi muddatlarini tasdiqlang.
7. Prognoz bo'yicha tavsiyalarni ko'rib chiqing.
8. Vazifalarni tayinlang va kuzatib boring.
9. Noodatiy faoliyat haqida xabar berilganda audit jurnallarini ko'rib chiqing.

## Foydalanuvchi boshqaruvi

Foydalanuvchilar sahifasidan foydalanish:

1. Foydalanuvchi yaratish.
2. Rol tayinlash.
3. Bo'limni tayinlash.
4. Foydalanuvchini faollashtirish/o‘chirish.
5. Faoliyatni ko'rib chiqish: yaqinda onlayn, bu hafta faol, foydalanilmayapti.
6. Siyosat ruxsat bergan joyda foydalanuvchini tahrirlash orqali parolni tiklang.
7. Qo'shimcha ruxsatlarni faqat rol etarli bo'lmaganda qo'shing.

Qoidalar:

1. Ish uchun zarur bo'lgan eng kam ruxsat bering.
2. Administrator yoki Super Adminga tasodifiy ruxsat bermang.
3. Kompaniyani tark etgan foydalanuvchilarni o'chirib qo'ying.
4. Oxirgi faol administratorni o'chirmang.
5. HR xodimlarining yozuvlarini foydalanuvchi kirishiga mos holda saqlang.

## Qo'shimcha ruxsatnomalar

Qo'shimcha ruxsatlar istisnolar uchundir. Avval rolga asoslangan kirishni afzal ko'ring.

Misollar:

1. `purchasing.request` ham kerak rejalashtiruvchi.
2. `payroll.scan` kerak bo'lgan nazoratchi.
3. `traceability.export` kerak bo'lgan menejer.

Agar u haqiqatan ham administrator bo‘lmasa, `*` berishdan saqlaning.

## Kafedra boshqaruvi

Bo'lim nomi/kodni qo'shish yoki yangilash uchun bo'limlar sahifasidan foydalaning.

Qoidalar:

1. Bo'lim kodi qisqa va barqaror bo'lishi kerak.
2. Foydalanuvchilarga, xodimlarga yoki ish buyruqlariga tayinlangan bo'limni o'chirmang.
3. Qavat sahifalarida ishlatiladigan kodlarni tahrirlashdan oldin bo'lim o'zgarishlarini Administrator va Rejalashtirish bilan muvofiqlashtiring.

## Audit jurnallari

Audit jurnallari kim nimani va qachon o'zgartirganligini ko'rsatadi.

Filtrlardan foydalaning:

1. Matnni qidirish.
2. Foydalanuvchi IDsi.
3. Harakat.
4. Shaxs.
5. Shaxs identifikatori.
6. Sana oralig'i.

Qiymatlardan oldingi/keyin taqqoslash uchun tafsilotlarni oching. Audit jurnallaridan ayblash uchun emas, balki tekshirish uchun foydalaning. Maqsad sababni topish va jarayonni tuzatishdir.

## Sozlamalar

Sozlamalarga quyidagilar kiradi:

1. Kompaniya nomi, logotipi, manzili, telefoni, elektron pochtasi.
2. Standart valyuta va moliyaviy yil boshlanish oyi.
3. Standart til va vaqt mintaqasi.
4. Model turi variantlari.
5. Bichishdan oldin materialni bron qilishni talab qiling.

Sozlamalarni ehtiyotkorlik bilan o'zgartiring, chunki ular barcha bo'limlarga ta'sir qiladi.

## Tasdiqlash va istisnolar

Boshqaruv/Admin quyidagilarni tasdiqlashi mumkin:

1. Modelni tasdiqlash.
2. Chiqindilarni utilizatsiya qilish.
3. Ish haqi muddatini tasdiqlash.
4. Paket o'zgarishi yoki sig'imdan istisnolar.
5. Belgilangan muddatni bekor qilish yoki ishlab chiqarishni blokdan chiqarish.

Tasdiqlash qoidasi: faqat tegishli yozuvni, jismoniy haqiqatni va biznes sababini tekshirgandan so'ng tasdiqlang.

## Jarayonni kuzatish nazorati

1. Ishlab chiqarish buyurtmasi, sotish buyurtmasi, mijoz yoki model bo'yicha qidirish.
2. Joriy bosqichni tekshiring.
3. Sahna tafsilotlarini oching.
4. Bloklangan bosqich va sababni tekshiring.
5. Ochiq ishlab chiqarish buyurtmasi.
6. Agar kerak bo'lsa, tikuv ishlarini tayinlang yoki ajrating.
7. Zarur bo'lganda jarayon hisobotini chop etish/saqlash.

## Vazifalar va bildirishnomalar

Bo'limlararo kuzatish uchun vazifalardan foydalaning.

Yaxshi topshiriq misollari:

1. Savdo buyurtmasi uchun etishmovchilikni tekshiring.
2. Yo'qolgan paket yorliqlarini qayta chop eting.
3. Yo'q qilish so'rovini tasdiqlash.
4. Ishlab chiqarishni davom ettirishdan oldin noto'g'ri partiyani tasdiqlang.

Ogohlantirishlar smenaning boshida va oxirida tekshirilishi kerak.

## Umumiy muammolar

| Muammo | Mumkin sabab | Harakat |
| --- | --- | --- |
| Xodim sahifani ko'ra olmaydi | Rol/ruxsat etishmayapti | Foydalanuvchi roli va qo'shimcha ruxsatlarni ko'rib chiqing. |
| Foydalanuvchi juda ko'p ruxsatga ega | Qo'shimcha ruxsat yoki Administrator roli | Qo'shimcha ruxsatni olib tashlang va to'g'ri rolni tayinlang. |
| Bo'limni o'chirib bo'lmaydi | U foydalanuvchilar/xodimlar/ish buyurtmalari tomonidan qo'llaniladi | Yozuvlarni qayta tayinlang yoki bo'limni faol holda saqlang. |
| Noto'g'ri ishlab chiqarish ma'lumotlari | Foydalanuvchi noto'g'ri yozuvni saqladi | Audit jurnalini ko'rib chiqing va vakolatli ish oqimi orqali to'g'rilang. |
| Bichish bandlov bilan bloklangan | Sozlash toʻliq bandlovni talab qiladi | Bandlovlarni yoki boshqaruv istisnolarini hal qiling. |
