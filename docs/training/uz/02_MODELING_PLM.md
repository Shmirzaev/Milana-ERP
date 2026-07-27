# Modellashtirish / PLM O'quv qo'llanma

Versiya: 1.0
Sana: 2026-07-02
Bo'lim kodi: MOD
Standart rol: Modellashtirish

## Maqsad

Modellashtirish / PLM mahsulot katalogini yuritadi. Rejalashtirish, sotish, inventarizatsiya, prognozlash, xarajat, qadoqlash va kuzatuvning barchasi toza model ma'lumotlariga bog'liq.

## Bosh sahifalar

- Modellar
- Model tafsilotlari
- Brendlar
- To'plamlar
- Ruxsat berilganda kuzatuv imkoniyati

## Asosiy ruxsatlar

- `modeling.models`
- `modeling.bom`
- `modeling.brands`
- `modeling.collections`
- `modeling.approve`

## Kundalik ish jarayoni

1. Model yozuvlarini yarating yoki yangilang.
2. Model kodini, nomini, toifasini, turini, tavsifini va rasmini qo'shing.
3. Model o'lchamlari va ranglarini saqlang.
4. BOM qatorlarini buyum, dona miqdori, birlik va chiqindilar foizi bilan saqlang.
5. Modellarni brendlar va kollektsiyalarga bog'lash.
6. Model tafsilotlari sahifasi ularni qo'llab-quvvatlaydigan naqsh/tasvir fayllarini yuklang.
7. Mahalliy jarayonga muvofiq tasdiqlash uchun tayyor modellarni yuboring yoki belgilang.
8. Rejalashtirish yoki moliya tomonidan bildirilgan BOM kamchiliklarini tuzating.

## Model yaratish nazorat ro'yxati

Har bir modelda quyidagilar bo'lishi kerak:

1. Noyob model kodi.
2. Mahsulot nomini tozalang.
3. Turkum/turi.
4. Mahsulot tasviri yoki ma'lumotnomasi.
5. Yaroqli oʻlcham oraligʻi.
6. Yaroqli ranglar.
7. BOM material qatorlari.
8. Xarajatlarni hisoblash va bron qilish uchun ishlatilsa, qadoqlash/aksessuarlar qatorlari.
9. Ish haqi/imkoniyati uchun foydalanilganda SAM daqiqalar.
10. Tovar ishlab chiqarishdan oldin tasdiqlash holati.

## BOM qoidalari

BOM materialga bo'lgan talablar, etishmovchilikni tekshirish, bron qilish va xarajatlar smetasi uchun ishlatiladi.

Har bir BOM qatori uchun:

1. To'g'ri inventar elementini tanlang.
2. Har bir parcha miqdorini kiriting.
3. Iloji bo'lsa, inventar sifatida bir xil qurilmadan foydalaning.
4. Chiqindilarning foizini real tarzda kiriting.
5. Uslubni o'zgartirgandan so'ng eski yoki takroriy qatorlarni qoldirmang.

Agar Rejalashtirish hisobotlari `no BOM` yoki moddiy zaxiralar bo'sh qatorlarni ko'rsatsa, avval BOM modelini tekshiring.

## Brendlar va kollektsiyalar

Brendli aktsiyalarni ishlab chiqarish yoki sotishda Brendlar va To'plamlardan foydalaning.

1. Brend yarating.
2. To'plamni mavsum/yil/status bilan yarating.
3. Tasdiqlangan modellarni to'plamga bog'lang.
4. Sotuv va prognozlash to'g'ri filtrlashi uchun nomlashni izchil davom ettiring.

## Tasdiqlash qoidalari

Tasdiqlangan modellar tovar ishlab chiqarish uchun ishlatilishi mumkin. Hajmi, rangi, tasviri va BOM tayyor bo'lmaguncha modelni tasdiqlamang.

Agar model tasdiqlangandan keyin tuzatilishi kerak bo'lsa:

1. Har qanday Savdo buyurtmalari yoki ishlab chiqarish buyurtmalarida allaqachon foydalanilganligini tekshiring.
2. Rejalashtirish va boshqaruv bilan muvofiqlashtirish.
3. BOM-ni ehtiyotkorlik bilan yangilang, chunki kelajakdagi xarajat va bandlov o'zgarishi mumkin.
4. Muhim tuzatishlarni tushuntirish uchun qaydlar yoki audit jurnallaridan foydalaning.

## Ma'lumotlar sifatini tekshirish ro'yxati

1. Model kodida xato yo'q.
2. Model nomi jismoniy mahsulotga mos keladi.
3. Rasm modelga mos keladi.
4. O'lchamlar va ranglar Savdolar sotishi mumkin bo'lgan narsalarga mos keladi.
5. BOM qatorlari faol inventar elementlaridan foydalanadi.
6. Chiqindilarning foizlari realdir.
7. Qasddan talab qilinmasa, takroriy BOM elementi yo'q.
8. Brend/to‘plam havolalari to‘g‘ri.

## Umumiy muammolar

| Muammo | Mumkin sabab | Harakat |
| --- | --- | --- |
| Rejalashtirish talablarni hisoblab chiqa olmaydi | BOM etishmayotgan yoki yaroqsiz | BOM qatorlarini qo'shing va saqlang. |
| Brendli ishlab chiqarishni yaratish mumkin emas | Model tasdiqlanmagan | To'liq model va tasdiqlashni so'rang. |
| Noto'g'ri material zaxiralangan | BOM elementi noto‘g‘ri | BOM ni to'g'rilang va Rejadan bandlovlarni yangilashni so'rang. |
| Savdolar modelni topa olmaydi | Model kodi/nomi/status muammosi | Model ro'yxatini, tasdiqlash holatini va imloni tekshiring. |
