# Sotuv bo'yicha o'quv qo'llanma

Versiya: 1.0
Sana: 2026-07-02
Bo'lim kodi: SLS
Odatiy rol: Savdo

## Maqsad

Savdo ERPda mijozlar talabini yaratadi va mijozlarga qaratilgan buyurtma ma'lumotlarini aniq saqlaydi. Savdo buyurtmalari rejalashtirish, sotib olish, ishlab chiqarish, moliyalashtirish va jo'natish uchun boshlang'ich nuqtadir.

## Bosh sahifalar

- Boshqaruv paneli
- Sotuv buyurtmalari
- Yangi savdo buyurtmasi
- Savdo buyurtmasi tafsilotlari
- Buyurtma tarixi
- Mijozlar
- Jarayonni kuzatish
- Kuzatish imkoniyati
- Prognozlash, ruxsat berilganda faqat o'qish uchun

## Asosiy ruxsatlar

- `sales.orders`
- `sales.customers`
- `processes.view`
- `traceability.view`
- `traceability.export`
- `forecasting.view`

## Kundalik ish jarayoni

1. Ochiq mijozlar so'rovlarini tekshiring.
2. Mijoz yozuvini yarating yoki yangilang.
3. To'g'ri buyurtma turi bilan savdo buyurtmasini yarating.
4. Model, rang, o'lcham, miqdor, birlik narxi va chop etish talablari bilan buyurtma qatorlarini qo'shing.
5. Belgilangan muddat va eslatmalarni qo'shing.
6. Har qanday satr chop etishni talab qilganda chop etish fayllarini yuklang yoki chop etish ko'rsatmalarini qo'shing.
7. Buyurtmani saqlang va Savdo buyurtmasi tafsilotlarini ko'rib chiqing.
8. Mahalliy tasdiqlash amaliyotiga muvofiq buyurtmani tasdiqlang yoki Rejalashtirishga yo'naltiring.
9. Mijozlarning holatiga oid savollar uchun jarayonni kuzatish yoki kuzatish imkoniyatidan foydalaning.
10. Hisob-faktura/to‘lov holati bo‘yicha Moliya bilan kelishish.

## Mijoz yaratish

Xaridor yangi bo'lsa, Savdo buyurtmasini yaratishdan oldin mijozlardan foydalaning.

Majburiy odatlar:

1. Dublikatlardan qochish uchun avval qidiring.
2. Rasmiy mijoz nomidan foydalaning.
3. Agar mavjud bo'lsa, telefon, elektron pochta va manzilni qo'shing.
4. Deyarli dublikat yaratish o'rniga mavjud mijozni yangilang.

## Mijoz buyurtmasini yaratish

1. Savdo buyurtmalarini oching.
2. Yangi buyurtmani tanlang.
3. `Client order` ni tanlang.
4. Xaridor va muddatni tanlang.
5. Bir yoki bir nechta qator qo'shing.
6. Har bir satr uchun model, rang, o'lcham, miqdor, birlik narxi va chop etish talabini tanlang.
7. Xuddi shu model/rang uchun bir nechta o'lcham kerak bo'lganda o'lcham yordamchisidan foydalaning.
8. Agar chop etish kerak bo'lsa, aniq ko'rsatmalarni kiriting va rasm/spetsifikatsiya fayllarini qo'shing.
9. Umumiy miqdor va umumiy miqdorni ko'rib chiqing.
10. Yaratilgan Savdo buyurtmasi tafsilotlari sahifasini saqlang va oching.

Yo'qolgan model, noma'lum o'lcham, aniq bo'lmagan muddat yoki to'liq bo'lmagan chop etish ma'lumotlari bilan mijoz buyurtmasini yaratmang.

## Brendli aksiyalar savdosini yaratish

Brendli aktsiyalarni sotish zaxirasi allaqachon tugagan.

1. `Branded stock sale` ni tanlang.
2. Brend va mijozni tanlang.
3. Faqat xotirada mavjud bo'lgan modellarni tanlang.
4. Paketlar sonini va har bir paketdagi donalarni kiriting.
5. So'ralgan miqdor mavjud tayyor zaxiradan oshmasligini tasdiqlang.
6. Buyurtmani saqlang.
7. Zarur bo'lganda, Savdo buyurtmasi tafsilotlari sahifasidan zaxirani zaxiralang.

Agar zaxiralar etarli bo'lmasa, rejalashtirish va tayyor mahsulotni saqlash tasdiqlovisiz jo'natishni va'da qilmang.

## Chop etish tafsilotlari

Har qanday qatorni chop etish kerak bo'lganda:

1. Aniq joylashuv, rang, texnika, o'lcham va eslatma namunalarini qo'shing.
2. Chop etish jamoasi tomonidan ishlatiladigan faylni yuklang.
3. Qo'shimchalarning to'g'ri ochilishini tasdiqlang.
4. Agar kerak bo'lsa, eslatmalarda mijozning ma'qullash holatini eslatib o'ting.

Chop etish bu tafsilotlarni Chop etish bo‘yicha ish buyurtmasi sahifasida ko‘radi.

## Mijoz holatiga oid savollar

Ushbu tartibdan foydalaning:

1. Jarayonni kuzatishni oching va sotish buyurtmasi, ishlab chiqarish buyurtmasi, mijoz yoki model bo'yicha qidiring.
2. Joriy bosqichni, muddati kechiktirilgan bayroqni va bloklangan bosqichni tekshiring.
3. Agar tovarlar allaqachon qadoqlangan bo'lsa, Paket yoki ishlab chiqarish buyurtmasi bo'yicha Traceability-ni oching.
4. Yuborilgan bo'lsa, jo'natish holatini tekshiring.
5. Mijozlarga faqat faktik holatlarni bering; Rejalashtirishsiz tugatish sanalarini taxmin qilmang.

## Moliyaviy muvofiqlashtirish

Savdolar ruxsatlar ruxsat etilgan hollarda mijoz buyurtmasi/toʻlov kontekstini koʻrishi mumkin, ammo Finance hisob-faktura va toʻlov yozuvlariga egalik qiladi.

Moliyaga o'tish:

1. Hisob-fakturani yaratish.
2. To'lovni e'lon qilish.
3. Oldindan to'lovni qayta ishlash.
4. Ochiq balans savollari.
5. To'lov mos kelmasligi.

## Ma'lumotlar sifatini tekshirish ro'yxati

Saqlash yoki tasdiqlashdan oldin:

1. Xaridor to'g'ri.
2. Buyurtma turi to'g'ri.
3. Muddati realdir.
4. Model mavjud va kerak bo'lganda tasdiqlangan.
5. Rangi va o'lchami aniq.
6. Miqdor va birlik narxi to'g'ri.
7. Chop etish katakchasi mijozning haqiqiy talabiga mos keladi.
8. Zarur bo'lganda chop etish fayllari va ko'rsatmalari ilova qilinadi.
9. Eslatmalar istisnolarni tushuntiradi.

## Umumiy xatolar

| Xato | Natija | Tuzatish |
| --- | --- | --- |
| Buyurtma turi noto'g'ri | Rejalashtirish/aksiyalarni bron qilish noto'g'ri oqimga to'g'ri keladi | Pastki oqim yozuvlarini o'zgartirishdan oldin nazoratchi/administratordan so'rang. |
| Chop etish tafsilotlari yetishmayapti | Chop etish jamoasi kutmoqda yoki noto‘g‘ri chop etmoqda | Ishlab chiqarish chop etishdan oldin ko'rsatmalar/fayllarni qo'shing. |
| Takroriy mijoz | To'lov tarixi yozuvlar bo'yicha bo'linadi | Administrator yoki rahbardan qanday qilib birlashtirish/to'g'rilashni so'rang. |
| Ishlab chiqarish boshlanganidan keyin miqdori o'zgardi | Ishlab chiqarish va tannarx bir-biriga mos kelmasligi mumkin | Tahrirlashdan oldin rejalashtirish va boshqaruv bilan muvofiqlashtiring. |
