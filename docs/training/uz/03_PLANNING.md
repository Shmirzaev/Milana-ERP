# Rejalashtirish bo'yicha o'quv qo'llanma

Versiya: 1.0
Sana: 2026-07-02
Bo'lim kodi: PLN
Standart rol: Rejalashtirish

## Maqsad

Rejalashtirish talabni boshqariladigan ishlab chiqarishga aylantiradi. Rejalashtirish guruhi materiallarga bo'lgan talablarni tekshiradi, ishlab chiqarish buyurtmalarini yaratadi, partiyalarni yaratadi yoki boshqaradi, tikuv oqimlarini tayinlaydi, muddatlarni nazorat qiladi va ish erga etib borgunga qadar etishmovchilik xavfini hal qiladi.

## Bosh sahifalar

- Rejalashtirish paneli
- Prognozlash
- Ishlab chiqarish buyurtmalari
- Ishlab chiqarish buyurtmasi tafsilotlari
- Jarayonni kuzatish
- Tikuv oqimlari
- Sotib olish bo'yicha so'rovlar
- Inventar zahiralari
- Kuzatish imkoniyati

## Asosiy ruxsatlar

- `planning.view`
- `planning.requirements`
- `planning.production`
- `planning.reserve_materials`
- `inventory.reservations.view`
- `inventory.reservations.create`
- `purchasing.view`
- `purchasing.request`
- `purchasing.order`
- `processes.view`
- `sewing.flows`
- `forecasting.view`
- `forecasting.manage`

## Kundalik ish jarayoni

1. Rejalashtirish panelini oching.
2. Tasdiqlangan yoki rejalashtirishga tayyor Sotuv Buyurtmalarini ko'rib chiqing.
3. Materiallarga bo'lgan talab va kamchiliklarni tekshiring.
4. Ishlab chiqarishni yaratishdan oldin taxminiy material kodini, miqdori va birligini qo'shing.
5. Buyurtmani to'plamni rejalashtirish kerakligini hal qiling.
6. Ishlab chiqarish buyurtmasini yaratish.
7. Ishga buyurtma berish muddatlarini yarating/kaskad.
8. Ishlab chiqarish buyurtmasi uchun zaxira materiallar.
9. Kamchiliklar haqida ogohlantirishlarni ko'rib chiqing va agar kerak bo'lsa, sotib olish so'rovlarini yarating.
10. Tikuv oqimini belgilash yoki tikuv ishlarini chiziqlar bo'ylab ajratish.
11. Muddati o'tgan va bloklangan ishni kuzatish uchun jarayonni kuzatishdan foydalaning.

## Savdo buyurtmasidan ishlab chiqarishni yaratish

1. Rejalashtirish panelini oching.
2. Tasdiqlangan savdo buyurtmasini toping.
3. Ishlab chiqarish buyurtmasini yaratish-ni tanlang.
4. Materiallar smetasini kiriting: material kodi, miqdori va birligi.
5. Model, miqdor, mijozning oxirgi muddati va bosib chiqarish talabini tasdiqlang.
6. Ishlab chiqarishni yaratish.
7. Ishlab chiqarish buyurtmasi tafsilotlari sahifasini oching.
8. Bichish, ixtiyoriy chop etish, tikish, qadoqlash va saqlash uchun yaratilgan ish buyurtmalarini ko'rib chiqing.

## To'plamlar bilan rejalashtirish

Buyurtma kichikroq partiyalarda ishlab chiqarilganda partiyalardan foydalaning.

1. To'plamlarni rejalashtirish-ni tanlang.
2. To'plam uchun maksimal qismlarni kiriting.
3. Avtomatik ajratishdan foydalaning yoki qatorlarni qo'lda qo'shing.
4. Har bir partiya uchun ism, rejalashtirilgan miqdor, boshlanish sanasi, oxirgi sana va eslatmalarni kiriting.
5. Jami partiya miqdori buyurtma miqdoriga teng ekanligini tasdiqlang.
6. Materiallar bahosini kiriting.
7. Partiyalar bilan ishlab chiqarishni yarating.

To'plamdan so'ng, har bir qavat sahifasi operatordan chiqishni saqlashdan oldin to'g'ri partiyani tanlashni talab qiladi.

## Brendli aktsiyalarni ishlab chiqarish

1. Rejalashtirish panelini oching.
2. Brendli ishlab chiqarish bo'limidan foydalaning.
3. Tasdiqlangan modelni tanlang.
4. Belgilangan muddatni kiriting.
5. Rang/o‘lcham/miqdor qatorlarini qo‘shing yoki o‘lchamni taqsimlash yordamchisidan foydalaning.
6. Brendli reja yarating.
7. Oddiy bosqichlar orqali ishlab chiqarishni kuzatib boring.
8. Tayyor paketlar keyinchalik Savdo Buyurtmalari uchun mavjud bo'lgan markali zaxiraga aylanadi.

## Moddiy zahiralar

Rezervasyonlar bichishdan oldin asosiy nazorat hisoblanadi.

1. Ishlab chiqarish buyurtmasi tafsilotlarini oching.
2. Rezervasyonning qisqacha mazmuni: zarur, zaxiralangan, qolgan, etishmovchilik.
3. Ruxsat berilganda Avtomatik zahiradan foydalaning.
4. Zaxiralangan to'plamlarni ko'rib chiqing.
5. Agar etishmovchilik saqlanib qolsa, sotib olish so'rovini yarating yoki Saqlash bilan muvofiqlashtiring.
6. Rezervasyonlarni faqat ishlab chiqarish rejasi o'zgarganda yoki material bo'shatilganda qoldiring.

Agar kompaniya sozlamalari bichishdan oldin to'liq zaxiralashni talab qilsa, kerakli BOM materiallari zahiraga olinmaguncha bichish bloklanadi.

## Prognozlash

Prognozlash quyidagilarni ta'minlaydi:

1. Brendli aktsiyalarni ishlab chiqarish bo'yicha takliflar.
2. Buyumni qayta tartiblash boʻyicha takliflar.
3. Kam miqdordagi tayyor mahsulot ko'rsatkichlari.
4. Talab tendentsiyalari miqdori.
5. Qabul qilinishi yoki rad etilishi mumkin bo'lgan saqlangan tavsiyalar.

Rejalashtirish prognozlashni avtomatik majburiyat sifatida emas, balki rejalashtirish yordami sifatida ko'rib chiqishi kerak. Ishlab chiqarishni yaratishdan oldin imkoniyatlar, modelni tasdiqlash, BOM va haqiqiy talabni tasdiqlang.

## Tikuv oqimini belgilash

Tikuv ishlarini tayinlash uchun ishlab chiqarish buyurtmasi detali yoki tikuv oqimlaridan foydalaning.

1. Tikuv ishlari tartibini oching.
2. Tikuv oqimini/chiziqini belgilang.
3. Agar buyurtma katta bo'lsa, miqdorni topshiriqlar bo'yicha taqsimlang.
4. Belgilashdan oldin chiziqdan foydalanishni tekshiring.
5. To'liq qatorga tayinlashdan saqlaning.
6. Ma'lum bo'lganda, rejalashtirilgan boshlanish/tugashni yangilang.

## Bloklash va blokdan chiqarish ishi

Rejalashtirish/boshqaruv, agar ish davom etmasa, Ishga buyurtmani bloklashi mumkin.

Quyidagilar uchun blokirovkadan foydalaning:

1. Materiallar etishmasligi.
2. Noto'g'ri spetsifikatsiya.
3. Mijoz ushlab turish.
4. Sifat muammosi.
5. Belgilangan muddat yoki imkoniyatlar muammosi.

Har doim aniq blok sababini kiriting. Faqat sabab bartaraf etilgandan keyin blokdan chiqaring.

## Kundalik rejalashtirish nazorat ro'yxati

1. Yangi Savdo Buyurtmalari rejalashtirilgan yoki ataylab kutilayotganligini tasdiqlang.
2. Materiallar etishmasligini ko'rib chiqing.
3. Shartlanmagan ishlab chiqarish buyurtmalarini ko'rib chiqing.
4. Jarayonni kuzatishda muddati o'tgan buyurtmalarni ko'rib chiqing.
5. Bloklangan Ish buyurtmalarini ko‘rib chiqing.
6. Tikuv chizig'idan foydalanishni ko'rib chiqing.
7. Xarid so'rovlari va qabul qilish holatini ko'rib chiqing.
8. Savdo, saqlash, ishlab chiqarish va boshqaruvdagi o'zgarishlar haqida xabar bering.

## Umumiy muammolar

| Muammo | Mumkin sabab | Harakat |
| --- | --- | --- |
| Brendli reja tuzib bo‘lmadi | Model tasdiqlanmagan | Ma'lumotlar tugallangandan keyin Modellashtirish/Boshqaruvdan tasdiqlashni so'rang. |
| Bandlov boʻsh | BOM yo'q | BOM to'ldirish uchun Modellashtirishdan so'rang. |
| Bichishni boshlash mumkin emas | Kerakli materiallar bandi toʻliq emas | Materiallarni zaxiralang yoki taqchillik siyosatini hal qiling. |
| Tikuv liniyasi to'la | Belgilangan quvvat oshib ketdi | Boshqa chiziqni tanlang yoki oqimlar bo'ylab ajrating. |
| Jarayonni kuzatish ko‘rsatuvlari bloklandi | Ish tartibi bloki mavjud | Ishlab chiqarish buyurtmasini oching va bloklangan bosqichni hal qiling. |
