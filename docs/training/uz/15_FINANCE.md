# Moliya bo'yicha o'quv qo'llanma

Versiya: 1.0
Sana: 2026-07-02
Bo'lim kodi: FIN
Standart rol: Moliya

## Maqsad

Moliya daromadlarni, hisob-fakturalarni, to'lovlarni, mijozlar balanslarini, markali aktsiyalarning qiymatini, chiqindi daromadlari/xarajatlarini, COGS, to'lanadigan ish haqi, sotib olish ko'rinishi va rentabellikni ko'rib chiqadi.

## Bosh sahifalar

- Moliya boshqaruv paneli
- Savdo buyurtmasi tafsilotlari, mavjud bo'lganda hisob-faktura harakati
- Mijoz tafsilotlari
- Ish haqi to'g'risidagi xulosa
- Sotib olish, o'qish ko'rinishi
- Inventar zahiralari, o'qish ko'rinishi
- Prognozlash, o'qish ko'rinishi

## Asosiy ruxsatlar

- `finance.view`
- `finance.invoice`
- `finance.payment`
- `inventory.reservations.view`
- `purchasing.view`
- `payroll.view`
- `payroll.pay`
- `forecasting.view`

## Kundalik ish jarayoni

1. Moliyaviy boshqaruv panelini oching.
2. Jami daromadni, olingan to'lovlarni, markali aktsiya qiymatini va chiqindi xarajatlarini/daromadlarini ko'rib chiqing.
3. Oxirgi hisob-fakturalarni ko'rib chiqing.
4. To'lanmagan yoki qisman to'langan schyot-fakturalar uchun to'lovlarni yozib oling.
5. Davrlar bo'yicha daromadlarni ko'rib chiqing.
6. Xarajatlarni taqsimlashni ko'rib chiqing: mato, mehnat, aksessuarlar va umumiy COGS.
7. Zarur bo'lganda mijozlar balanslarini ko'rib chiqing.
8. To'lovni kutayotgan ish haqi davrlarini ko'rib chiqing.
9. Mos kelishmovchiliklar uchun Sotuv, Saqlash, Rejalashtirish va HR bilan muvofiqlashtiring.

## Hisob-fakturani yaratish

Hisob-fakturalar hisob-faktura harakati mavjud bo'lgan Sotuv buyurtmasi kontekstidan yaratilishi mumkin.

Qoidalar:

1. Hisob-fakturani faqat to'g'ri Sotuv Buyurtmasi uchun yarating.
2. Buyurtma miqdori va mijozni tasdiqlang.
3. Takroriy hisob-fakturalarni yaratmang. Backend mavjud bo'lganda bir xil Savdo Buyurtmasi uchun mavjud hisob-fakturani qaytaradi.
4. Yaratilgandan keyin hisob-faktura holatini tekshiring.

## To'lovni yozib olish

1. Moliyaviy boshqaruv panelini oching.
2. Oxirgi hisob-fakturani toping.
3. Toʻlanmagan hisob-fakturada toʻlovni yozib olish-ni tanlang.
4. Hisob-faktura raqami/buyurtma raqami/mijoz/summani tasdiqlang.
5. Qabul qilingan miqdorni kiriting.
6. To'lov sanasini kiriting.
7. Usulni tanlang: bank o'tkazmasi, naqd pul yoki karta.
8. Tasdiqlang va saqlang.

Toʻlovlar toʻlangan summaga qarab hisob-faktura holatini avtomatik ravishda yangilaydi.

## Mijoz to'lovlari tarixi

Mijoz maʼlumotlaridan quyidagilar uchun foydalaning:

1. Buyurtma tarixi.
2. To'langan/ochiq qoldiqlar.
3. Oldindan kredit.
4. To'lov tarixi.
5. Ruxsat berilganda mijoz to'lovini qo'shish.

Agar to'lov hisob-faktura miqdoridan oshib ketgan bo'lsa, tizim joriy oqimga qarab ortiqcha kreditni avans sifatida ko'rib chiqishi mumkin.

## Xarajat va foyda sharhi

Moliyaviy boshqaruv paneli quyidagilarni o'z ichiga oladi:

1. Brendli aksiya qiymati.
2. Chiqindilar hisoboti.
3. Davr bo'yicha daromad.
4. Xarajatlarni taqsimlash.
5. Foydalanish nuqtasini buyurtma qiling.

Xarajat BOM, stok partiyalari, oxirgi partiya narxi, qadoqlash, ish haqi va ishlab chiqarish hajmiga bog'liq. Agar xarajat noto'g'ri ko'rinsa, bo'limlardan tarixni o'zgartirishni so'rashdan oldin manba ma'lumotlarini tekshiring.

## Ish haqini to'lash

Moliyaviy ish haqi to'lash jadvali tasdiqlangandan keyingina to'lanadi.

1. Ish haqi hisobotini oching.
2. Ish haqi davrini filtrlang.
3. Jami va tuzatishlarni tasdiqlang.
4. Holat tasdiqlanganligini tasdiqlang.
5. Haqiqiy to'lov amalga oshirilganda to'langan deb belgilang.

To'lovni amalga oshirishdan oldin to'langan ish haqini belgilamang.

## Sotib olish va inventarni ko'rish

Moliya kutilayotgan xarajatlar va moddiy majburiyatlarni tushunish uchun Xarid qilish va inventar zahiralarini ko'rib chiqishi mumkin. Xarid qilish operatsiyalari xarid qilish ruxsatiga ega foydalanuvchilarga tegishli.

## 1C integratsiyasi

Backend `POST /api/finance/integrations/1c/sync`-ni `X-1C-Token` bilan qo'llab-quvvatlaydi. Bu oddiy foydalanuvchi ish oqimi emas, balki tizim integratsiyasi oqimi.

Moliya/Administrator qoidalari:

1. 1C tokenini maxfiy saqlang.
2. Tokenni chat yoki skrinshotlar orqali yubormang.
3. Konfiguratsiya o'zgarishlaridan keyin sinxronlangan yozuvlarni tasdiqlang.
4. Integratsiyadagi nosozliklar haqida IT/Super Adminga xabar bering.

## Umumiy muammolar

| Muammo | Mumkin sabab | Harakat |
| --- | --- | --- |
| Hisob-faktura yetishmayapti | Hali Savdo buyurtmasidan yaratilmagan | Buyurtma tayyor bo'lsa, hisob-fakturani yarating. |
| Toʻlov holati yangilanmaydi | Miqdor/sana/usul masalasi yoki dublikat topshirish | Hisob-faktura va to'lovlar tarixini ko'rib chiqing. |
| COGS noto'g'ri ko'rinadi | BOM yoki aksiya narxi muammosi | Manba maʼlumotlarini tekshirish uchun Modellashtirish/Saqlash xizmatidan soʻrang. |
| Ish haqini to'lash mumkin emas | Davr tasdiqlanmagan | Tasdiqlashni yakunlash uchun HR/Menejmentdan so'rang. |
| Chiqindidan tushgan daromad yo'q | Chiqindilarni sotish qayd etilmagan | Chiqindilarni chiqarish bo'limidan holatni tekshirishni so'rang. |
