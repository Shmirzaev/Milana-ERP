from __future__ import annotations

import html
import re
import textwrap
from pathlib import Path

from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = ROOT / "docs" / "training"
OUTPUT_ROOT = ROOT / "output" / "pdf" / "training"

DOC_ORDER = [
    "README.md",
    "00_FULL_PROCESS_OVERVIEW.md",
    "01_SALES.md",
    "02_MODELING_PLM.md",
    "03_PLANNING.md",
    "04_PURCHASING.md",
    "05_FABRIC_ACCESSORIES_STORAGE.md",
    "06_CUTTING.md",
    "07_PRINTING.md",
    "08_SEWING.md",
    "09_MILANA_SEWING_FACTORY.md",
    "10_BESTTEX_SEWING_FACTORY.md",
    "11_PACKAGING.md",
    "12_BESTTEX_TEXTILE_PACKAGING.md",
    "13_READY_PRODUCT_STORAGE.md",
    "14_WASTE_DEPARTMENT.md",
    "15_FINANCE.md",
    "16_HR.md",
    "17_MANAGEMENT_ADMIN.md",
    "18_SUPERADMIN_FULL_DETAILS.md",
]


def register_fonts() -> tuple[str, str, str]:
    regular = "Helvetica"
    bold = "Helvetica-Bold"
    mono = "Courier"

    font_candidates = {
        "TrainingRegular": Path("C:/Windows/Fonts/arial.ttf"),
        "TrainingBold": Path("C:/Windows/Fonts/arialbd.ttf"),
        "TrainingMono": Path("C:/Windows/Fonts/consola.ttf"),
    }
    if all(path.exists() for path in font_candidates.values()):
        pdfmetrics.registerFont(TTFont("TrainingRegular", str(font_candidates["TrainingRegular"])))
        pdfmetrics.registerFont(TTFont("TrainingBold", str(font_candidates["TrainingBold"])))
        pdfmetrics.registerFont(TTFont("TrainingMono", str(font_candidates["TrainingMono"])))
        pdfmetrics.registerFontFamily(
            "Training",
            normal="TrainingRegular",
            bold="TrainingBold",
            italic="TrainingRegular",
            boldItalic="TrainingBold",
        )
        regular = "TrainingRegular"
        bold = "TrainingBold"
        mono = "TrainingMono"

    return regular, bold, mono


FONT_REGULAR, FONT_BOLD, FONT_MONO = register_fonts()


def make_styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "TrainingTitle",
            parent=base["Title"],
            fontName=FONT_BOLD,
            fontSize=22,
            leading=27,
            textColor=colors.HexColor("#14110b"),
            spaceAfter=10,
        ),
        "h2": ParagraphStyle(
            "TrainingH2",
            parent=base["Heading2"],
            fontName=FONT_BOLD,
            fontSize=13,
            leading=16,
            textColor=colors.HexColor("#2c2920"),
            spaceBefore=10,
            spaceAfter=5,
        ),
        "h3": ParagraphStyle(
            "TrainingH3",
            parent=base["Heading3"],
            fontName=FONT_BOLD,
            fontSize=11.5,
            leading=14,
            textColor=colors.HexColor("#3b3528"),
            spaceBefore=8,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "TrainingBody",
            parent=base["BodyText"],
            fontName=FONT_REGULAR,
            fontSize=9.5,
            leading=13.2,
            textColor=colors.HexColor("#2c2920"),
            spaceAfter=5,
        ),
        "list": ParagraphStyle(
            "TrainingList",
            parent=base["BodyText"],
            fontName=FONT_REGULAR,
            fontSize=9.3,
            leading=12.5,
            leftIndent=8,
            firstLineIndent=0,
            textColor=colors.HexColor("#2c2920"),
        ),
        "code": ParagraphStyle(
            "TrainingCode",
            parent=base["Code"],
            fontName=FONT_MONO,
            fontSize=8.2,
            leading=10.5,
            leftIndent=6,
            rightIndent=6,
            borderPadding=5,
            backColor=colors.HexColor("#f1efe8"),
            textColor=colors.HexColor("#14110b"),
            spaceBefore=4,
            spaceAfter=6,
        ),
        "table_header": ParagraphStyle(
            "TrainingTableHeader",
            parent=base["BodyText"],
            fontName=FONT_BOLD,
            fontSize=7.8,
            leading=9.4,
            textColor=colors.HexColor("#14110b"),
        ),
        "table_cell": ParagraphStyle(
            "TrainingTableCell",
            parent=base["BodyText"],
            fontName=FONT_REGULAR,
            fontSize=7.8,
            leading=9.4,
            textColor=colors.HexColor("#2c2920"),
        ),
        "cover": ParagraphStyle(
            "TrainingCover",
            parent=base["Title"],
            fontName=FONT_BOLD,
            fontSize=24,
            leading=29,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#14110b"),
            spaceAfter=12,
        ),
        "cover_sub": ParagraphStyle(
            "TrainingCoverSub",
            parent=base["BodyText"],
            fontName=FONT_REGULAR,
            fontSize=11,
            leading=15,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#56503f"),
            spaceAfter=8,
        ),
    }


STYLES = make_styles()


def clean(content: str) -> str:
    return textwrap.dedent(content).strip() + "\n"


LOCALIZED = {
    "uz": {
        "folder": "uz",
        "header_left": "Milana ERP o'quv qo'llanmasi",
        "combined_title": "Milana ERP o'quv to'plami",
        "combined_subtitle": "Bo'lim qo'llanmalari va Super Admin uchun to'liq ma'lumot",
        "combined_filename": "Milana_ERP_Oquv_Toplami_Barcha_Bolimlar.pdf",
        "cover_source": "Manba: docs/training/uz",
        "docs": {
            "README.md": clean(
                """
                # Milana ERP bo'limlar bo'yicha o'quv kutubxonasi

                Versiya: 1.0
                Sana: 2026-07-02
                Auditoriya: bo'lim xodimlari, supervisorlar, trenerlar, rahbariyat, adminlar va superadminlar

                Bu papka ERP bo'yicha o'quv materialini bo'limlarga ajratadi. Har bir jamoa faqat o'zi ishlatadigan ekranlar, vazifalar va javobgarliklar bo'yicha o'qiydi.

                Avval umumiy jarayon sharhini o'qing, keyin xodimning bo'limiga mos qo'llanmani oching.

                ## Asosiy jarayon

                - [To'liq jarayon sharhi](00_FULL_PROCESS_OVERVIEW.md)

                ## Bo'lim qo'llanmalari

                - [Sotuv](01_SALES.md)
                - [Modeling / PLM](02_MODELING_PLM.md)
                - [Rejalashtirish](03_PLANNING.md)
                - [Xarid](04_PURCHASING.md)
                - [Mato va furnitura ombori](05_FABRIC_ACCESSORIES_STORAGE.md)
                - [Bichish](06_CUTTING.md)
                - [Pechat](07_PRINTING.md)
                - [Tikuv](08_SEWING.md)
                - [Milana tikuv fabrikasi](09_MILANA_SEWING_FACTORY.md)
                - [Besttex tikuv fabrikasi](10_BESTTEX_SEWING_FACTORY.md)
                - [Qadoqlash](11_PACKAGING.md)
                - [Besttex Textile qadoqlash](12_BESTTEX_TEXTILE_PACKAGING.md)
                - [Tayyor mahsulot ombori](13_READY_PRODUCT_STORAGE.md)
                - [Chiqindi bo'limi](14_WASTE_DEPARTMENT.md)
                - [Moliya](15_FINANCE.md)
                - [HR](16_HR.md)
                - [Rahbariyat / Admin](17_MANAGEMENT_ADMIN.md)

                ## To'liq huquqli qo'llanma

                - [Super Admin to'liq ma'lumot](18_SUPERADMIN_FULL_DETAILS.md)

                ## Ko'rib chiqilgan manbalar

                Qo'llanmalar joriy ERP kodi va hujjatlari asosida tayyorlangan: asosiy README, mavjud xodim qo'llanmasi, seed qilingan bo'limlar va rollar, frontend sidebar/page oqimlari, backend route'lar va joriy permissionlar.
                """
            ),
            "00_FULL_PROCESS_OVERVIEW.md": clean(
                """
                # Milana ERP to'liq jarayon sharhi

                Versiya: 1.0
                Sana: 2026-07-02
                Auditoriya: barcha bo'limlar

                Milana ERP mijoz talabidan tayyor mahsulot yetkazilishigacha bo'lgan tikuv ishlab chiqarish jarayonini boshqaradi. Tizim Sotuv, Modeling / PLM, Rejalashtirish, Xarid, Mato va furnitura ombori, Bichish, Pechat, Tikuv, Qadoqlash, Tayyor mahsulot ombori, Chiqindi, Moliya, HR, Rahbariyat, Admin va Super Admin ishlarini bog'laydi.

                Eng muhim qoida oddiy: jismoniy ish bajarilgan paytning o'zida ERP ham yangilanishi kerak.

                ## Asosiy yozuvlar

                | Yozuv | Ma'nosi |
                | --- | --- |
                | Sales Order | Sotuv yaratadigan mijoz buyurtmasi yoki brend ombor sotuvi. |
                | Model | Kod, nom, razmerlar, ranglar, rasmlar, BOM va tasdiq holati bor mahsulot ta'rifi. |
                | BOM | Rejalashtirish va ombor material ehtiyoji, rezerv va kamomadni hisoblashda ishlatadigan materiallar ro'yxati. |
                | Production Order | Mijoz buyurtmasi yoki brend ombor uchun Rejalashtirish yaratadigan ishlab chiqarish rejasi. |
                | Work Order | Bichish, pechat, tikuv, qadoqlash yoki omborga o'tkazish bo'yicha bo'lim vazifasi. |
                | Production Batch | Katta buyurtma kichik partiyalar bilan ishlab chiqarilganda ichki bo'linma. |
                | Bundle | Bichilgan detallar barcode yoki QR yorliq bilan bog'langan to'plam; Bichish, Pechat va Tikuvdan o'tadi. |
                | Package | Tayyor mahsulot qutisi/paketi; package barcode yoki QR bilan omborga va jo'natmaga o'tadi. |
                | Stock Batch | Mato, furnitura, qadoqlash materiali yoki xarid qilingan mahsulot inventar partiyasi. |
                | Material Reservation | Bichishdan oldin Production Order uchun rejalashtirilgan material band qilish. |
                | Shipment | Tayyor package'larga bog'langan jo'natma yozuvi. |
                | Payroll Record | Xodim QR va ish/jarayon QR skani asosida yaratiladigan ishbay haqi yozuvi. |
                | Audit Log | Muhim o'zgarishlar, tasdiqlar, o'chirishlar va status o'tishlarining tizim tarixi. |

                ## Hamma uchun qoidalar

                1. Faqat o'z akkauntingizdan foydalaning.
                2. Parol yoki QR yorliqlarni ulashmang.
                3. Eski browser tabidan emas, o'z bo'lim sahifangizdan boshlang.
                4. Saqlashdan oldin order raqami, model, rang, razmer, miqdor, partiya va statusni tekshiring.
                5. Imkon bo'lsa qo'lda yozish o'rniga QR/barcode skan qiling.
                6. Status yoki topshirish skanini o'tkazib yubormang.
                7. Failed, rejected, rework, damaged va waste miqdorlarini halol kiriting.
                8. Izohni faqat istisno holatlar uchun qo'shing.
                9. Xato saqlangan bo'lsa supervisorni tez xabardor qiling.
                10. Umumiy kompyuterdan chiqqanda log out qiling.

                ## Asosiy mijoz buyurtmasi oqimi

                1. Sotuv mijoz va Sales Order yaratadi.
                2. Sotuv order turi, mijoz, model, rang, razmer, miqdor, narx, deadline va pechat ma'lumotlarini kiritadi.
                3. Modeling / PLM tasdiqlangan model, razmer, rang, rasm va BOMni yuritadi.
                4. Rejalashtirish tasdiqlangan Sales Order'larni ko'rib chiqadi, materialni hisoblaydi, kerak bo'lsa partiyaga bo'ladi va Production Order yaratadi.
                5. Rejalashtirish materialni rezerv qiladi va kamomadni tekshiradi.
                6. Material yetishmasa Xarid purchase request yoki purchase order yaratadi.
                7. Ombor xarid qilingan materialni supplier, warehouse, miqdor, unit, cost va QC status bilan batchga qabul qiladi.
                8. Bichish material kirimi, fabric batch, cut pieces, waste va bundle plan yozadi.
                9. Bichish bundle yorliqlarini yaratadi va bundle'larni Pechatga yoki to'g'ridan-to'g'ri Tikuvga yuboradi.
                10. Pechat bundle'larni qabul qiladi, print instruction/file'larni tekshiradi, output/reject yozadi va Tikuvga yuboradi.
                11. Tikuv bundle'larni qabul qiladi, output/failed/rework/rejected miqdorlarini yozadi va line/factory bo'yicha kuzatadi.
                12. Qadoqlash packed/damaged miqdorlarni yozadi, package label yaratadi va label chop etadi.
                13. Tayyor mahsulot ombori package'larni skan qiladi, cell/shelfga qabul qiladi, shipment tayyorlaydi, jo'natishdan oldin skan qiladi, keyin shipped va delivered statuslarini belgilaydi.
                14. Moliya invoice yaratadi, payment yozadi, profit, waste income, inventory value va payroll payable'ni ko'rib chiqadi.
                15. Chiqindi bo'limi ishlab chiqarish chiqindisini qabul qiladi, sotiladigan chiqindini sotadi yoki sotilmaydigan chiqindi uchun disposal approval so'raydi.
                16. Rahbariyat dashboard, process tracking, approval, exception va audit log'larni nazorat qiladi.

                ## Brend ombor oqimi

                1. Modeling model yaratadi yoki yangilaydi.
                2. Rahbariyat modelni tasdiqlaydi.
                3. Rejalashtirish tasdiqlangan modeldan brend ombor ishlab chiqarishini yaratadi.
                4. Ishlab chiqarish Bichish -> kerak bo'lsa Pechat -> Tikuv -> Qadoqlash oqimidan o'tadi.
                5. Tayyor package'lar Warehouse Stockda mavjud bo'ladi.
                6. Sotuv branded-stock sale yaratadi va mavjud finished goodsni rezerv qiladi.
                7. Tayyor mahsulot ombori rezerv qilingan stockni jo'natadi.

                ## Xarid oqimi

                1. Rejalashtirish yoki Xarid confirmed/planning orderlardan material kamomadini ko'radi.
                2. Xarid Sales Order shortage'dan yoki qo'lda request yaratadi.
                3. Approver requestni approve yoki reject qiladi.
                4. Xarid approved requestni Purchase Orderga aylantiradi.
                5. Storage/Purchasing Receiving Purchase Order line'larini inventory stock batchga qabul qiladi.
                6. Rejalashtirish rezervlarni yangilaydi va material tayyor bo'lganda yoki kamomad rahbariyat tomonidan qabul qilinganda ishlab chiqarishni qo'yib yuboradi.

                ## Payroll oqimi

                1. HR xodimlarni active va to'g'ri bo'limga biriktirilgan holda saqlaydi.
                2. Supervisorlar xodim payroll QR badge va ish/jarayon QR yorliqlarini yaratadi yoki chop etadi.
                3. Payroll scanner avval xodimni, keyin process/work QRni skan qiladi.
                4. Scan page quantity va rate bo'yicha ishbay haqni hisoblaydi.
                5. Payroll yozuvlari backendga saqlanadi.
                6. HR/Payroll payroll period yaratadi, record'larni tekshiradi, bonus/deduction qo'shadi, periodni lock qiladi va approval/paymentga yuboradi.
                7. Rahbariyat payroll periodni tasdiqlaydi.
                8. Moliya tasdiqlangan payrollni paid deb belgilaydi.

                ## Traceability oqimi

                Traceability package barcode, package number, bundle, production order yoki shipment bo'yicha qidiradi. U mahsulot identifikatsiyasi, bog'langan order, warehouse/shipment, timeline, material manbasi, package'lar, gaplar va export permission bo'lsa product passportni ko'rsatadi.

                Traceabilitydan quyidagi holatlarda foydalaning:

                1. Mijoz order qayerdaligini so'rasa.
                2. Hujjatsiz package topilsa.
                3. Defect investigation uchun material batch yoki ishlab chiqarish tarixi kerak bo'lsa.
                4. Shipment, package yoki bundle skanlari kutilgan statusga mos kelmasa.

                ## Process Tracking oqimi

                Process Tracking production order progressini stage'lar bo'yicha real vaqtda ko'rsatadi. Search, status filter, sort, stage detail, batch tracking, blocked-stage warning, audit link va print/save-as-PDF export mavjud.

                Supervisorning kunlik ishlatishi:

                1. Active orderlarni filter qiling.
                2. Current stage, assigned sewing flow, deadline, overdue flag va blocked stage'larni tekshiring.
                3. Stage action talab qilsa Production Orderni oching.
                4. Keyingi bo'lim davom etishidan oldin blocked previous stepni hal qiling.

                ## Topshirish qoidalari

                | Topshirish | ERPda kerakli action |
                | --- | --- |
                | Sales -> Planning | Sales Order to'liq va confirmed/planning-ready bo'lishi kerak. |
                | Planning -> Storage/Purchasing | Material requirement va shortage ko'rib chiqilgan bo'lishi kerak. |
                | Storage -> Cutting | Kerakli material batch yoki reservation tayyor bo'lishi kerak. |
                | Cutting -> Printing | Bundle scan bundle'ni Printingga yuboradi. |
                | Cutting -> Sewing | Printing kerak bo'lmasa bundle scan bundle'ni sewing factoryga yuboradi yoki qabul qildiradi. |
                | Printing -> Sewing | Printing outputni yozadi, keyin bundle scan bilan Sewingga yuboradi. |
                | Sewing -> Packaging | Sewing passed/rework/failed quantity yozadi. |
                | Packaging -> Ready Storage | Package label yaratiladi va package storagega skan qilinadi. |
                | Storage -> Shipment | Package storagega qabul qilinadi, shipmentga qo'shiladi, jo'natishdan oldin skan qilinadi, keyin shipped/delivered qilinadi. |

                ## Smena boshidagi checklist

                1. Log in qiling.
                2. Notification va tasklarni tekshiring.
                3. Department inbox yoki asosiy bo'lim sahifasini oching.
                4. Incoming, pending, in-progress, blocked va overdue ishlarni ko'ring.
                5. Scanner va label printer ishlashini tekshiring.
                6. Bugungi active ishlarni ko'rayotganingizni tasdiqlang.

                ## Smena oxiridagi checklist

                1. Smena davomida bajarilgan barcha jismoniy ishlarni ERPga saqlang.
                2. Skan qilingan bundle/package local queue'da qolmaganini tekshiring.
                3. Failed, rework, rejected, damaged va waste yozuvlarini ko'rib chiqing.
                4. Blocked record'larni supervisor'ga xabar qiling.
                5. Shared scanner inputni tozalang va log out qiling.

                ## Tez-tez uchraydigan muammolar

                | Muammo | Ehtimoliy sabab | Amal |
                | --- | --- | --- |
                | Sahifa ko'rinmayapti | Permission yetishmaydi | Supervisor/Admin role va extra permissionni tekshirsin. |
                | Button disabled | Noto'g'ri status yoki permission yo'q | Oldingi step va rolingizni tekshiring. |
                | Bundle qabul qilinmayapti | Oldingi bo'lim yubormagan | Oldingi bo'limdan scan/send qilishni so'rang. |
                | Package qabul qilinmayapti | Package packed emas yoki allaqachon moved/shipped | Package status va tarixni tekshiring. |
                | Material reservation shortage ko'rsatadi | Stock yo'q yoki BOM talabi stockdan ko'p | Planning, Storage va Purchasing ko'rib chiqishi kerak. |
                | Cutting blocked | Kerakli material reservation to'liq emas | Production Orderda reservation statusni tekshiring. |
                | Payroll scan duplicate | Shu work QR oldin skan qilingan | Qayta skan qilishdan oldin saved/duplicate statusni tekshiring. |
                | Audit tarixi noto'g'ri ko'rinadi | Foydalanuvchi action yozuvni o'zgartirgan | Management/Admin audit log'larni ko'rib chiqsin. |
                """
            ),
            "01_SALES.md": clean(
                """
                # Sotuv bo'limi o'quv qo'llanmasi

                Versiya: 1.0
                Sana: 2026-07-02
                Bo'lim kodi: SLS
                Standart rol: Sales

                ## Maqsad

                Sotuv ERPda mijoz talabini yaratadi va mijozga ko'rinadigan buyurtma ma'lumotlarini aniq saqlaydi. Sales Order Rejalashtirish, Xarid, Ishlab chiqarish, Moliya va Shipment uchun boshlang'ich nuqtadir.

                ## Asosiy sahifalar

                - Dashboard
                - Sales Orders
                - New Sales Order
                - Sales Order Detail
                - Order History
                - Customers
                - Process Tracking
                - Traceability
                - Forecasting, permission berilganda read-only

                ## Asosiy permissionlar

                - `sales.orders`
                - `sales.customers`
                - `processes.view`
                - `traceability.view`
                - `traceability.export`
                - `forecasting.view`

                ## Kunlik ish jarayoni

                1. Ochiq mijoz so'rovlarini tekshiring.
                2. Customer record yarating yoki yangilang.
                3. To'g'ri order turi bilan Sales Order yarating.
                4. Model, rang, razmer, miqdor, unit price va printing requirement bilan order line qo'shing.
                5. Deadline va note qo'shing.
                6. Printing kerak bo'lsa file yuklang yoki instruction yozing.
                7. Orderni saqlang va Sales Order Detailni tekshiring.
                8. Local approval amaliyotiga ko'ra orderni confirm qiling yoki Planningga yuboring.
                9. Mijoz status so'rasa Process Tracking yoki Traceabilitydan foydalaning.
                10. Invoice/payment holati bo'yicha Finance bilan kelishing.

                ## Mijoz yaratish

                Xaridor yangi bo'lsa Sales Orderdan oldin Customersdan foydalaning.

                1. Duplicate bo'lmasligi uchun avval qidiring.
                2. Rasmiy customer nomidan foydalaning.
                3. Telefon, email va address mavjud bo'lsa kiriting.
                4. Yangi duplicate yaratish o'rniga mavjud customer'ni yangilang.

                ## Client order yaratish

                1. Sales Ordersni oching.
                2. New Orderni tanlang.
                3. `Client order`ni tanlang.
                4. Customer va deadlineni tanlang.
                5. Bir yoki bir nechta line qo'shing.
                6. Har line uchun model, color, size, quantity, unit price va printing requirementni tanlang.
                7. Bir model/rangda ko'p razmer bo'lsa size helperdan foydalaning.
                8. Printing kerak bo'lsa aniq instruction yozing va artwork/specification file biriktiring.
                9. Total quantity va total amountni tekshiring.
                10. Saqlang va yaratilgan Sales Order detail sahifasini oching.

                Model, razmer, deadline yoki printing ma'lumoti noaniq bo'lsa client order yaratmang.

                ## Branded stock sale yaratish

                1. `Branded stock sale`ni tanlang.
                2. Brand va customer tanlang.
                3. Faqat storage'da available bo'lgan modellardan tanlang.
                4. Pack soni va pieces-per-pack kiriting.
                5. So'ralgan quantity finished stockdan ko'p emasligini tekshiring.
                6. Orderni saqlang.
                7. Kerak bo'lsa Sales Order detaildan stockni rezerv qiling.

                Stock yetarli bo'lmasa Planning va Ready Product Storage tasdig'isiz shipment va'da qilmang.

                ## Printing ma'lumotlari

                1. Joylashuv, rang, texnika, o'lcham va sample note'larni aniq kiriting.
                2. Print jamoasi ishlatadigan fileni yuklang.
                3. Attachmentlar ochilishini tekshiring.
                4. Customer approval status bo'lsa note'ga yozing.

                ## Mijoz status savollari

                1. Process Trackingni ochib Sales Order, Production Order, customer yoki model bo'yicha qidiring.
                2. Current stage, overdue flag va blocked stage'ni tekshiring.
                3. Tovar packed bo'lsa package yoki production order orqali Traceabilityni oching.
                4. Shipped bo'lsa Shipment statusni tekshiring.
                5. Mijozga faqat fakt status ayting; Planning bilan kelishmasdan finish date taxmin qilmang.

                ## Finance bilan koordinatsiya

                Finance invoice va payment yozuvlarining egasi. Quyidagilarni Finance'ga eskalatsiya qiling:

                1. Invoice creation.
                2. Payment posting.
                3. Advance payment.
                4. Open balance savollari.
                5. Payment mismatch.

                ## Data quality checklist

                1. Customer to'g'ri.
                2. Order type to'g'ri.
                3. Deadline real.
                4. Model mavjud va kerak bo'lsa approved.
                5. Color va size aniq.
                6. Quantity va unit price to'g'ri.
                7. Printing checkbox actual talabga mos.
                8. Kerakli printing file va instruction biriktirilgan.
                9. Note faqat exceptionni tushuntiradi.

                ## Tez-tez xatolar

                | Xato | Natija | Tuzatish |
                | --- | --- | --- |
                | Order type noto'g'ri | Planning/stock reservation noto'g'ri flowga ketadi | Downstream record o'zgarishidan oldin supervisor/Admin bilan kelishing. |
                | Printing details yo'q | Printing kutadi yoki noto'g'ri chop etadi | Production printingga yetmasidan oldin instruction/file qo'shing. |
                | Duplicate customer | Payment history bo'linadi | Merge/correction bo'yicha Admin yoki supervisor'dan so'rang. |
                | Production boshlanganidan keyin quantity o'zgardi | Production va costing mismatch bo'lishi mumkin | Planning va Management bilan kelishib edit qiling. |
                """
            ),
            "02_MODELING_PLM.md": clean(
                """
                # Modeling / PLM o'quv qo'llanmasi

                Versiya: 1.0
                Sana: 2026-07-02
                Bo'lim kodi: MOD
                Standart rol: Modeling

                ## Maqsad

                Modeling / PLM mahsulot katalogini yuritadi. Rejalashtirish, Sotuv, Inventory, Forecasting, Costing, Packaging va Traceability toza model ma'lumotiga tayanadi.

                ## Asosiy sahifalar

                - Models
                - Model Detail
                - Brands
                - Collections
                - Traceability, permission berilganda

                ## Asosiy permissionlar

                - `modeling.models`
                - `modeling.bom`
                - `modeling.brands`
                - `modeling.collections`
                - `modeling.approve`

                ## Kunlik ish jarayoni

                1. Model record yaratish yoki yangilash.
                2. Model code, name, category, type, description va image kiritish.
                3. Model sizes va colorsni yuritish.
                4. BOM row'larda item, quantity per piece, unit va waste percentni saqlash.
                5. Modellarni brand va collectionlarga bog'lash.
                6. Model detail qo'llasa pattern/image file yuklash.
                7. Local processga ko'ra modelni approvalga yuborish yoki ready qilish.
                8. Planning yoki Finance aytgan BOM gaplarni tuzatish.

                ## Model yaratish checklist

                1. Unique model code.
                2. Aniq product name.
                3. Category/type.
                4. Product image yoki reference.
                5. Valid size range.
                6. Valid colors.
                7. BOM material rows.
                8. Costing/reservation uchun packaging/accessory rows.
                9. Payroll/capacity uchun SAM minutes.
                10. Branded productiondan oldin approval status.

                ## BOM qoidalari

                BOM material requirement, shortage check, reservation va cost estimate uchun ishlatiladi.

                1. To'g'ri inventory item tanlang.
                2. Quantity per piece kiriting.
                3. Imkon bo'lsa inventorydagi unit bilan bir xil unit ishlating.
                4. Waste percentni real kiriting.
                5. Style o'zgargach eski yoki duplicate row qoldirmang.

                Planning `no BOM` desa yoki reservation bo'sh chiqsa, avval model BOMni tekshiring.

                ## Brand va collection

                1. Brand yarating.
                2. Season/year/status bilan collection yarating.
                3. Approved modellarga collection bog'lang.
                4. Sales va Forecasting to'g'ri filter qilishi uchun nomlashni consistent tuting.

                ## Approval qoidalari

                Approved model branded-stock productionda ishlatiladi. Size, color, image va BOM tayyor bo'lmaguncha modelni approve qilmang.

                Approvaldan keyin tuzatish kerak bo'lsa:

                1. Sales Order yoki Production Order allaqachon modeldan foydalanganini tekshiring.
                2. Planning va Management bilan kelishing.
                3. BOMni ehtiyotkor yangilang, chunki future costing va reservation o'zgaradi.
                4. Katta tuzatishlarni note yoki audit log bilan tushuntiring.

                ## Data quality checklist

                1. Model code'da typo yo'q.
                2. Model name physical productga mos.
                3. Image modelga mos.
                4. Size va colors Sales sotadigan narsaga mos.
                5. BOM rows active inventory items ishlatadi.
                6. Waste percent real.
                7. Kerak bo'lmasa duplicate BOM item yo'q.
                8. Brand/collection linklar to'g'ri.

                ## Muammolar

                | Muammo | Sabab | Amal |
                | --- | --- | --- |
                | Planning requirement hisoblay olmaydi | BOM yo'q yoki invalid | BOM rows qo'shib saqlang. |
                | Branded production yaratilmaydi | Model approved emas | Modelni to'ldirib approval so'rang. |
                | Noto'g'ri material rezerv qilindi | BOM item noto'g'ri | BOMni tuzating va Planningdan reservation refresh so'rang. |
                | Sales modelni topmayapti | Code/name/status muammosi | Model list, approval status va spellingni tekshiring. |
                """
            ),
            "03_PLANNING.md": clean(
                """
                # Rejalashtirish bo'limi o'quv qo'llanmasi

                Versiya: 1.0
                Sana: 2026-07-02
                Bo'lim kodi: PLN
                Standart rol: Planning

                ## Maqsad

                Planning talabni nazoratli ishlab chiqarishga aylantiradi. Jamoa material ehtiyojini tekshiradi, Production Order yaratadi, batchlarni boshqaradi, sewing flow biriktiradi, deadline'larni kuzatadi va ish sexga tushmasidan oldin shortage riskini hal qiladi.

                ## Asosiy sahifalar

                - Planning Dashboard
                - Forecasting
                - Production Orders
                - Production Order Detail
                - Process Tracking
                - Sewing Flows
                - Purchase Requests
                - Inventory Reservations
                - Traceability

                ## Asosiy permissionlar

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

                ## Kunlik ish jarayoni

                1. Planning Dashboardni oching.
                2. Confirmed yoki planning-ready Sales Order'larni ko'ring.
                3. Material requirements va shortagesni tekshiring.
                4. Production yaratishdan oldin material code, amount va unit estimate kiriting.
                5. Order batch planning talab qiladimi, hal qiling.
                6. Production Order yarating.
                7. Work-order deadline'larini yarating yoki cascade qiling.
                8. Production Order uchun material rezerv qiling.
                9. Shortage warninglarni ko'rib, kerak bo'lsa purchase request yarating.
                10. Sewing flow biriktiring yoki ishni line'lar bo'yicha bo'ling.
                11. Process Tracking orqali overdue va blocked ishni kuzating.

                ## Sales Orderdan production yaratish

                1. Planning Dashboardni oching.
                2. Confirmed Sales Orderni toping.
                3. Create Production Orderni tanlang.
                4. Material estimate: material code, amount va unit kiriting.
                5. Model, quantity, customer deadline va printing requirementni tasdiqlang.
                6. Production yarating.
                7. Production Order detail sahifasini oching.
                8. Cutting, optional printing, sewing, packaging va storage work orderlarini tekshiring.

                ## Batch bilan rejalashtirish

                1. Plan Batchesni tanlang.
                2. Maximum pieces per batch kiriting.
                3. Auto Split ishlating yoki batch row'larni qo'lda qo'shing.
                4. Har batch uchun name, planned quantity, start date, deadline va notes kiriting.
                5. Total batch quantity order quantity bilan teng bo'lishini tekshiring.
                6. Material estimate kiriting.
                7. Batchlar bilan production yarating.

                Batch yaratilgandan keyin floor sahifalari output saqlashdan oldin to'g'ri batch tanlashni talab qiladi.

                ## Branded stock production

                1. Planning Dashboarddagi branded production bo'limini oching.
                2. Approved model tanlang.
                3. Deadline kiriting.
                4. Color/size/quantity line qo'shing yoki size distribution helper ishlating.
                5. Branded plan yarating.
                6. Oddiy stage'lar orqali kuzating.
                7. Finished package'lar keyingi Sales Orderlar uchun branded stock bo'ladi.

                ## Material reservation

                1. Production Order Detailni oching.
                2. Required, reserved, remaining va shortage summaryni tekshiring.
                3. Permission bo'lsa Auto Reserve ishlating.
                4. Reserved batchlarni ko'rib chiqing.
                5. Shortage qolsa purchase request yarating yoki Storage bilan kelishing.
                6. Reservationni faqat production plan o'zgarsa yoki material bo'shatilishi kerak bo'lsa release qiling.

                Company setting full reservation talab qilsa, BOM materiallar rezerv qilinmaguncha Cutting blocked bo'ladi.

                ## Forecasting

                Forecasting quyidagilarni beradi:

                1. Branded stock production suggestions.
                2. Item reorder suggestions.
                3. Low-stock finished goods indicators.
                4. Demand trend quantities.
                5. Accept yoki dismiss qilinadigan saved recommendations.

                Forecasting avtomatik majburiyat emas. Production yaratishdan oldin capacity, model approval, BOM va real demandni tasdiqlang.

                ## Sewing flow assignment

                1. Sewing Work Orderni oching.
                2. Sewing flow/line biriktiring.
                3. Order katta bo'lsa quantityni assignmentlar bo'yicha bo'ling.
                4. Assign qilishdan oldin line utilizationni tekshiring.
                5. Full line'ga assign qilmang.
                6. Planned start/end ma'lum bo'lsa yangilang.

                ## Ishni block va unblock qilish

                Planning/Management ish davom etmasligi kerak bo'lsa Work Orderni block qilishi mumkin.

                Block sabablari:

                1. Material shortage.
                2. Specification noto'g'ri.
                3. Customer hold.
                4. Quality issue.
                5. Deadline yoki capacity issue.

                Block reason aniq yozilsin. Sabab hal bo'lgandan keyingina unblock qiling.

                ## Kunlik checklist

                1. Yangi Sales Orderlar planned yoki intentionally waiting ekanini tekshiring.
                2. Material shortage'larni ko'ring.
                3. Unreserved Production Orderlarni tekshiring.
                4. Process Trackingda overdue orderlarni ko'ring.
                5. Blocked Work Orderlarni ko'ring.
                6. Sewing line utilizationni tekshiring.
                7. Purchasing request va receiving statusni kuzating.
                8. O'zgarishlarni Sales, Storage, Production va Managementga xabar qiling.

                ## Muammolar

                | Muammo | Sabab | Amal |
                | --- | --- | --- |
                | Branded plan yaratilmaydi | Model approved emas | Modeling/Managementdan data to'liq bo'lgach approve so'rang. |
                | Reservation bo'sh | BOM yo'q | Modelingdan BOMni to'ldirishni so'rang. |
                | Cutting boshlanmaydi | Required reservation incomplete | Materialni rezerv qiling yoki shortage policy hal qiling. |
                | Sewing line full | Capacity oshib ketgan | Boshqa line tanlang yoki flowlarga bo'ling. |
                | Process Tracking blocked ko'rsatadi | Work Order block mavjud | Production Orderni ochib blocked stage'ni hal qiling. |
                """
            ),
            "04_PURCHASING.md": clean(
                """
                # Xarid jarayoni o'quv qo'llanmasi

                Versiya: 1.0
                Sana: 2026-07-02
                Bo'lim: Purchasing workflow, odatda permissionga qarab Planning, Storage, Finance yoki Management bajaradi

                ## Maqsad

                Purchasing material shortage yoki qo'lda stock ehtiyojini approved purchase request, purchase order va received stockga aylantiradi.

                ## Asosiy sahifalar

                - Purchasing
                - Purchase Receiving
                - Planning Dashboard
                - Material Inventory
                - Accessory Inventory
                - Suppliers
                - Inventory Batches

                ## Asosiy permissionlar

                - `purchasing.view`
                - `purchasing.request`
                - `purchasing.approve`
                - `purchasing.order`
                - `purchasing.receive`
                - `storage.suppliers`
                - `storage.receive`

                ## Purchasing sahifasi workflow

                1. Planning-ready Sales Order shortage'larini ko'ring.
                2. Sales Order shortagedan request yarating.
                3. Item uchun manual request yarating.
                4. Purchase requestlarni approve yoki reject qiling.
                5. Approved requestlarni purchase orderga aylantiring.
                6. Purchase Receivingni oching.

                ## Shortagedan request yaratish

                1. Purchasingni oching.
                2. Order number, SKU, item name, required quantity, available quantity, shortage va unitni ko'ring.
                3. Shortage uchun Create Requestni tanlang.
                4. Generated request numberni tasdiqlang.
                5. Approval kerak bo'lsa approverni xabardor qiling.

                ## Manual request yaratish

                1. Item tanlang.
                2. Requested quantity kiriting.
                3. System ko'rsatgan available quantityni tekshiring.
                4. Known bo'lsa preferred supplier tanlang.
                5. Notes qo'shing.
                6. Request yarating.

                Manual request Sales Order shortagega bog'lanmagan stock ehtiyojlari uchun ishlatiladi.

                ## Approval va order conversion

                Approverlar:

                1. Shortage yoki biznes sababni tasdiqlaydi.
                2. Supplier va quantityni tekshiradi.
                3. Requestni approve yoki reject qiladi.
                4. Purchasing policy talab qilsa ERPdan tashqarida communication qo'shadi.

                Purchasing/order users:

                1. Approved requestlarni Purchase Orderga convert qiladi.
                2. Supplier va cost detail to'g'riligini tekshiradi.
                3. Open Purchase Orderlarni receivinggacha kuzatadi.

                ## Purchase receiving workflow

                1. Purchase Receivingni oching.
                2. Pending Purchase Order line'larni ko'ring.
                3. To'g'ri line'da Receiveni tanlang.
                4. Received quantity kiriting.
                5. Batch number kiriting.
                6. Storage warehouse tanlang.
                7. Supplier set qilinmagan bo'lsa tanlang.
                8. Cost per unit kiriting.
                9. Receivingni saqlang.

                Receiving inventory stock batch yaratadi. Noto'g'ri cost, batch yoki warehouse Inventory va Financega ta'sir qiladi.

                ## Receiving qoidalari

                1. Faqat jismonan kelgan materialni receive qiling.
                2. Policy ruxsat bermasa va system support qilmasa remaining quantitydan ortiq receive qilmang.
                3. Supplier delivery document numberni note yoki batch numberda ishlating.
                4. Batch numberni consistent saqlang.
                5. Shubhali goodsni warehouse practice bo'yicha QC statusga yuboring.

                ## Status ma'nolari

                | Status | Ma'nosi |
                | --- | --- |
                | draft/pending_approval | Request approval kutmoqda. |
                | approved | Request orderga convert qilinishi mumkin. |
                | rejected | Request buyurtma qilinmaydi. |
                | converted | Request Purchase Orderga aylandi. |
                | sent/approved | Purchase Order receive qilinishi mumkin. |
                | partially_received | Qisman qabul qilindi, qolgani open. |
                | received | Purchase Order to'liq qabul qilindi. |
                | cancelled | Purchase Order active emas. |

                ## Muammolar

                | Muammo | Sabab | Amal |
                | --- | --- | --- |
                | Shortage ko'rinmayapti | Planning-ready shortage yo'q yoki requirement hisoblanmagan | Planning material requirementni ko'rsin. |
                | Approve qilib bo'lmayapti | `purchasing.approve` yo'q | Admin/Management accessni tekshirsin. |
                | Receive qilib bo'lmayapti | `purchasing.receive` yo'q yoki open PO line yo'q | Permission va Purchase Order statusni tekshiring. |
                | Warehouse noto'g'ri tanlangan | Human selection error | Stock ishlatilmasidan oldin Storage/Adminni darhol xabardor qiling. |
                | Duplicate request | Bir shortage ikki marta request qilingan | Approver duplicate'ni reject qilsin yoki correction kelishilsin. |
                """
            ),
            "05_FABRIC_ACCESSORIES_STORAGE.md": clean(
                """
                # Mato va furnitura ombori o'quv qo'llanmasi

                Versiya: 1.0
                Sana: 2026-07-02
                Bo'lim kodi: STR
                Standart rol: Storage

                ## Maqsad

                Mato va furnitura ombori raw material, accessories, packaging material, suppliers, inventory batches, movement va material reservation support uchun javobgar.

                ## Asosiy sahifalar

                - Material Inventory
                - Accessory Inventory
                - Master Data
                - Receive Stock
                - Batches
                - Purchase Receiving
                - Production Order Detaildagi Planning reservations
                - Traceability

                ## Asosiy permissionlar

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

                ## Kunlik ish jarayoni

                1. Expected purchases va open Purchase Receiving line'larni tekshiring.
                2. Physical stockni to'g'ri warehousega receive qiling.
                3. Inventory item master data va supplier datani yuriting.
                4. Stock batches va QC statusni ko'ring.
                5. Planningga reservation shortage bo'yicha yordam bering.
                6. Material warehouse yoki floorlar orasida ko'chsa transfer qiling.
                7. Batches va Traceability orqali stock savollarini tekshiring.

                ## Stockni qo'lda receive qilish

                1. Item tanlang.
                2. Supplier tanlang.
                3. Warehouse tanlang.
                4. Batch number kiriting.
                5. Quantity va unit kiriting.
                6. Cost per unit kiriting.
                7. Rang, width, GSM yoki boshqa batch detail kiritilishi kerak bo'lsa kiriting.
                8. QC status set qiling.
                9. Receivingni saqlang.

                ## Purchase receiving

                1. Purchase Receivingni oching.
                2. To'g'ri Purchase Order line tanlang.
                3. Faqat jismonan kelgan quantityni receive qiling.
                4. Batch number, warehouse, supplier va cost kiriting.
                5. Saqlang.
                6. Yangi batch Batches/Inventoryda chiqqanini tekshiring.

                ## Master Data

                Inventory item checklist:

                1. SKU unique.
                2. Name aniq.
                3. Category to'g'ri: fabric, accessory, packaging, waste yoki boshqa configured category.
                4. Unit to'g'ri.
                5. Default cost real.
                6. Trace qilinishi kerak itemlar uchun batch tracking enabled.

                Supplier checklist:

                1. Supplier name official.
                2. Contact information current.
                3. Duplicate supplierlardan qochiladi.

                ## Reservation support

                1. Production Order Detailda reservation planni ko'ring.
                2. Required, reserved, remaining, available va shortage quantitylarni tekshiring.
                3. Actual stock location va QCni tasdiqlang.
                4. Stock bor, lekin rezerv qilinmasa unit, item SKU yoki batch statusni tekshiring.
                5. Planning kerak emasligini tasdiqlamaguncha reservationni release qilmang.

                ## Batch quality

                1. Batch number.
                2. Item/SKU.
                3. Quantity va unit.
                4. Rang/width/GSM.
                5. Warehouse.
                6. Supplier.
                7. Cost.
                8. QC status.

                ## Muammolar

                | Muammo | Sabab | Amal |
                | --- | --- | --- |
                | Planning shortage ko'radi, lekin stock bor | Item, unit, warehouse, reserved quantity yoki QC noto'g'ri | Reservation itemni stock batch detail bilan solishtiring. |
                | Cost report noto'g'ri | Receiving cost noto'g'ri kiritilgan | Report final bo'lishidan oldin Finance/Adminni xabardor qiling. |
                | Batch cutting uchun available emas | Reservation yo'q yoki stock status noto'g'ri | Reservation va stock movementni tekshiring. |
                | Duplicate SKU | Master data xatosi | Duplicate ishlatishni to'xtating va Admin/Storage leaddan correction so'rang. |
                """
            ),
            "06_CUTTING.md": clean(
                """
                # Bichish bo'limi o'quv qo'llanmasi

                Versiya: 1.0
                Sana: 2026-07-02
                Bo'lim kodi: CUT
                Standart rol: Cutting

                ## Maqsad

                Bichish rezerv qilingan matoni bichilgan detallarga va traceable bundle'larga aylantiradi. Bichish aniqligi butun keyingi ishlab chiqarishni nazorat qiladi, chunki Pechat va Tikuv to'g'ri yaratilmagan yoki yuborilmagan bundle'ni qabul qila olmaydi.

                ## Asosiy sahifalar

                - Cutting Floor
                - Cutting Work Order
                - Cutting Passports
                - Bundle Inventory
                - Bundles
                - Scan Bundle
                - Process Tracking
                - Traceability

                ## Asosiy permissionlar

                - `cutting.records`
                - `cutting.bundles`
                - `inventory.reservations.view`
                - `payroll.scan`
                - `traceability.view`

                ## Kunlik ish jarayoni

                1. Cutting Floorni oching.
                2. Incoming/pending ishlarni ko'ring.
                3. To'g'ri Cutting Work Orderni oching.
                4. Product information, model, order, color, size, planned quantity va reservation statusni tekshiring.
                5. Order batched bo'lsa to'g'ri production batch tanlang.
                6. Fabric batch tanlang.
                7. Fabric input quantity va unit kiriting.
                8. Cut pieces kiriting.
                9. Waste quantity va unit kiriting.
                10. Bundle planni ko'ring yoki tahrirlang.
                11. Saqlang va bundle yarating.
                12. Bundle label chop eting.
                13. Scan Bundle bilan bundle'larni Printing yoki Sewingga yuboring.

                ## Bichishdan oldin

                1. Work Order to'g'ri Production Orderga tegishli.
                2. Model va size breakdown physical marker/cutting planga mos.
                3. Material reservation tayyor yoki proceed qilish approved.
                4. Fabric batch jismonan ishlatilayotgan materialga mos.
                5. Cutting table quantity planned batch/order quantityga mos.
                6. Printing requirement ma'lum.
                7. Sewing factory destination to'g'ri: Milana yoki Besttex.

                ## Cutting ichida batch planning

                1. Maximum pieces per batchdan foydalaning.
                2. Auto Split qiling yoki batch row'larni qo'lda qo'shing.
                3. Batch name, quantity, start date, deadline va notes kiriting.
                4. Batch planni saqlang.
                5. Batchlar bor bo'lsa cutting output saqlashdan oldin to'g'ri batch tanlang.

                Batch splitting shortage yoki reworkni yashirish uchun emas. Bu production planning va traceability uchun.

                ## Cutting output yozish

                Required fields:

                1. Production batch, order batched bo'lsa.
                2. Fabric batch.
                3. Input quantity va unit.
                4. Cut pieces.
                5. Waste quantity va unit.
                6. Bundle plan.
                7. G'ayrioddiy holat bo'lsa notes.

                System cut piecesni downstream bundle creation uchun passed pieces deb qabul qiladi.

                ## Bundle plan

                1. Color.
                2. Size.
                3. Pieces per bundle.
                4. Bundle count.
                5. Sewing factory.
                6. Next department: Printing yoki Sewing.

                Bundle quantity va count actual cut piecesga mos bo'lishi kerak. Printing bo'lsa Printingga yuboring, bo'lmasa to'g'ri sewing factoryga yuboring.

                ## Label printing

                1. Created bundle listni ko'ring.
                2. Hammasini yoki individual label chop eting.
                3. Har labelni darhol to'g'ri physical bundlega ulang.
                4. Bundle label ko'rinadigan va himoyalangan bo'lsin.

                Label shikastlansa, existing bundle list yoki Bundles sahifasidan reprint qiling. Label o'rniga duplicate bundle yaratmang.

                ## Bundle scan handoff

                1. Bundle barcode skan qiling yoki kiriting.
                2. Bundle number, model, color, size, quantity, current department, next department va sewing factoryni tasdiqlang.
                3. Status `created` va next Printing bo'lsa Send to Printing tanlang.
                4. Status `created` va next sewing factory bo'lsa available actionga ko'ra Send/Receive to factory tanlang.
                5. Status o'zgarganini tasdiqlang.

                ## Waste yozish

                1. Cutting record paytida waste quantity kiriting.
                2. Unusual waste uchun notes yozing.
                3. Physical wasteni waste department procedure bo'yicha yuboring.
                4. Production yaxshi ko'rinishi uchun waste'ni kamaytirib yozmang.

                ## Payroll scan

                1. Avval employee QRni skan qiling.
                2. Work/process QRni skan qiling.
                3. Employee, operation, quantity va rateni tekshiring.
                4. Kerak bo'lsa payroll record saqlang.

                ## Smena oxiri checklist

                1. Barcha cut work saqlangan.
                2. Barcha created bundle labelga ega.
                3. Physical bundle count ERP bilan mos.
                4. Forward yuborilgan bundle'lar skan qilingan.
                5. Waste yozilgan.
                6. Blocked yoki shortage work report qilingan.

                ## Muammolar

                | Muammo | Sabab | Amal |
                | --- | --- | --- |
                | Cutting record saqlanmayapti | Required batch/fabric/quantity yo'q yoki reservation block | Required fields va reservation statusni tekshiring. |
                | Bundle count noto'g'ri | Bundle plan cut piecesga mos emas | Save oldidan planni tuzating yoki saqlangan bo'lsa supervisordan so'rang. |
                | Printing bundle qabul qilmayapti | Cutting bundle'ni Printingga yubormagan | Bundle'ni skan qilib Printingga yuboring. |
                | Sewing bundle qabul qilmayapti | Next department/factory noto'g'ri yoki yuborilmagan | Bundle detailni tekshiring va destination noto'g'ri bo'lsa supervisordan so'rang. |
                """
            ),
            "07_PRINTING.md": clean(
                """
                # Pechat bo'limi o'quv qo'llanmasi

                Versiya: 1.0
                Sana: 2026-07-02
                Bo'lim kodi: PRT
                Standart rol: Printing

                ## Maqsad

                Pechat Bichishdan bundle'larni qabul qiladi, mijozning print instructionlariga amal qiladi, printed output va reject yozadi, keyin bundle'larni Tikuvga yuboradi.

                ## Asosiy sahifalar

                - Printing Floor
                - Printing Work Order
                - Scan Bundle
                - Process Tracking
                - Traceability

                ## Asosiy permissionlar

                - `printing.records`
                - `printing.bundles`
                - `payroll.scan`
                - `traceability.view`

                ## Kunlik ish jarayoni

                1. Printing Floorni oching.
                2. Incoming/pending printing ishlarini ko'ring.
                3. Scan Bundle bilan bundle qabul qiling.
                4. Printing Work Orderni oching.
                5. Work order collect talab qilsa Collect bilan deadline asosida boshlang/qabul qiling.
                6. Sales Order printing instructions va attachmentlarni ko'ring.
                7. Input, printed output, rejected quantity, print type, defect reason va notes yozing.
                8. Printing recordni saqlang.
                9. Scan Bundle bilan bundle'larni Sewingga yuboring.

                ## Bundle qabul qilish

                1. Printing uchun Scan Bundleni oching.
                2. Bundle barcodeni skan qiling.
                3. Status `sent_to_printing` ekanini tekshiring.
                4. Receive at Printingni tanlang.
                5. Status received at printing bo'lganini tasdiqlang.

                Receive button yo'q bo'lsa, Cutting bundle'ni Printingga yubormagan yoki status noto'g'ri.

                ## Printing work collect qilish

                1. Printing Work Orderni oching.
                2. Current status va deadlineni ko'ring.
                3. Kerak bo'lsa deadline va notes kiriting.
                4. Collectni tanlang.
                5. Work order in progress bo'lgandan keyin printing yozing.

                ## Printing instructionlari

                Work Order quyidagilarni ko'rsatishi mumkin:

                1. Printing talab qilgan Sales Order lines.
                2. Model/color/size/quantity.
                3. Customer notes.
                4. Printing instructions.
                5. Uploaded image/PDF/artwork files.

                Instruction noaniq bo'lsa print qilmang. Davom etishdan oldin Sales yoki Planningdan so'rang.

                ## Output yozish

                1. Production batch, order batched bo'lsa.
                2. Input quantity.
                3. Printed/output quantity.
                4. Rejected quantity.
                5. Print type.
                6. Defect reason.
                7. Notes.

                Output quantity downstream Sewing uchun passed quantity hisoblanadi.

                ## Sewingga yuborish

                1. Printing uchun Scan Bundleni oching.
                2. Har printed bundleni skan qiling.
                3. Status `received_printing` ekanini tasdiqlang.
                4. Send to Sewing/factory tanlang.
                5. Current/next department to'g'ri o'zgarganini tekshiring.

                ## Quality qoidalari

                1. Yozishdan oldin printed piecesni sanang.
                2. Rejectni darhol yozing.
                3. Takroriy muammolar uchun defect reason ishlating.
                4. Printed va unprinted bundle'larni alohida tuting.
                5. Unprinted yoki rejected piecesni passed output sifatida yubormang.

                ## Payroll scan

                1. Avval employee QRni skan qiling.
                2. Work/process QRni skan qiling.
                3. Operation va quantityni tasdiqlang.
                4. Kerak bo'lsa payroll record saqlang.

                ## Muammolar

                | Muammo | Sabab | Amal |
                | --- | --- | --- |
                | Bundle qabul qilinmayapti | Cutting yubormagan | Cuttingdan scan/send so'rang. |
                | Output form locked | Work Order collect/in progress emas | Ruxsat bo'lsa Collect ishlating. |
                | Print file noto'g'ri | Sales eski yoki noto'g'ri file yuklagan | To'xtang va Sales/Planningdan so'rang. |
                | Sewing qabul qilmayapti | Printing bundle'ni yubormagan | Bundle'ni skan qilib forward qiling. |
                """
            ),
            "08_SEWING.md": clean(
                """
                # Tikuv bo'limi o'quv qo'llanmasi

                Versiya: 1.0
                Sana: 2026-07-02
                Bo'lim kodi: SEW
                Standart rol: Sewing

                ## Maqsad

                Tikuv bundle'larni qabul qiladi, sewn output, failed/rework/rejected quantity yozadi va ishni sewing line yoki assignmentlarga nisbatan kuzatadi.

                ## Asosiy sahifalar

                - Sewing Floor
                - Sewing Work Order
                - Sewing Flows
                - Scan Bundle
                - Payroll Scan
                - Process Tracking
                - Traceability

                ## Asosiy permissionlar

                - `sewing.records`
                - `sewing.bundles`
                - `payroll.scan`
                - `traceability.view`

                ## Kunlik ish jarayoni

                1. Sewing Floor yoki assigned factory floorni oching.
                2. Line/factoryga assigned ishni ko'ring.
                3. Scan Bundle bilan bundle qabul qiling.
                4. Sewing Work Orderni oching.
                5. Kerak bo'lsa production batch tanlang.
                6. Line/assignment tanlang.
                7. Input, sewn output, failed, rework, rejected, defect reason va notes yozing.
                8. Recordni saqlang.
                9. Kerak bo'lsa payroll scan ishlating.
                10. Completed work Packaging uchun available ekanini tekshiring.

                ## Bundle qabul qilish

                1. Sewing uchun Scan Bundleni oching.
                2. Bundle barcodeni skan qiling.
                3. Model, color, size, quantity, current department, next department va factoryni tasdiqlang.
                4. Status `sent_to_sewing` bo'lsa Receive at factory tanlang.
                5. Direct sewing uchun yaratilgan bundle bo'lsa va page ruxsat bersa receive qiling.

                Wrong factory yoki wrong line bundle'larini qabul qilmang.

                ## Line va assignment tanlash

                Work Order quyidagilarni ko'rsatishi mumkin:

                1. Assigned sewing flows.
                2. Split assignments.
                3. Remaining quantity per assignment.
                4. Default Work Order sewing flow.
                5. Specific assignment yo'q bo'lsa barcha available flows.

                Output saqlashdan oldin to'g'ri line tanlang.

                ## Sewing output yozish

                1. Production batch, order batched bo'lsa.
                2. Input quantity.
                3. Sewn/output quantity.
                4. Failed quantity.
                5. Rework quantity.
                6. Rejected quantity.
                7. Line name yoki assignment.
                8. Defect reason.
                9. Notes.

                System sewn outputni Packaging uchun passed quantity sifatida ishlatadi.

                ## Quantity qoidalari

                1. Input upstream passed piecesdan oshmasin.
                2. Output jismonan tikilgan piecesni aks ettirsin.
                3. Failed pieces alohida sanalsin.
                4. Rework pieces yashirilmasin.
                5. Rejected pieces defect reason bilan yozilsin.

                ## Payroll scan

                1. Payroll Scanni oching.
                2. Avval employee badge skan qiling.
                3. Ikkinchi bo'lib process/work QRni skan qiling.
                4. Model, production, batch, operation, quantity, rate va totalni tekshiring.
                5. Scan yoki Save All bilan saqlang.
                6. Shu payable operation uchun bir xil work QRni ikki marta skan qilmang.

                ## Smena oxiri checklist

                1. Barcha physical sewing output saqlangan.
                2. Failed/rework/rejected quantitylar kiritilgan.
                3. Payroll scans local sessionda emas, saved.
                4. In progress bundle'lar completed bundle'lardan alohida.
                5. Supervisor blocked yoki quality-risk bundle'lardan xabardor.

                ## Muammolar

                | Muammo | Sabab | Amal |
                | --- | --- | --- |
                | Bundle qabul qilinmayapti | Oldingi bo'lim yubormagan | Cutting/Printingdan yuborishni so'rang. |
                | Noto'g'ri line ko'rinadi | Assignment yo'q yoki flow noto'g'ri | Planning/supervisor assignmentni yangilasin. |
                | Quantity error | Input/output allowed upstreamdan oshgan | Bundle/work order quantity va oldingi recordsni tekshiring. |
                | Payroll duplicate | Shu work QR allaqachon saved | Scan history va saved statusni ko'ring. |
                """
            ),
            "09_MILANA_SEWING_FACTORY.md": clean(
                """
                # Milana tikuv fabrikasi o'quv qo'llanmasi

                Versiya: 1.0
                Sana: 2026-07-02
                Bo'lim kodi: MIL
                Ishlatiladigan rol: Sewing

                ## Maqsad

                Milana Sewing Factory tikuv bajarish bo'limidir. U Sewing rolidan foydalanadi, lekin faqat Milana fabrikasiga assigned bundle va ishlarni qabul qiladi.

                ## Asosiy sahifalar

                - Milana Sewing
                - Sewing Work Order
                - Scan Bundle
                - Payroll Scan
                - Sewing Flows
                - Process Tracking

                ## Kunlik ish jarayoni

                1. Milana Sewingni oching.
                2. Incoming va assigned ishni ko'ring.
                3. Milanaga yuborilgan bundle'larni skan qiling.
                4. Receive qilishdan oldin bundle sewing factory Milana ekanini tekshiring.
                5. Sewing Work Orderda output yozing.
                6. To'g'ri line/assignment ishlating.
                7. Piecework kuzatilsa payroll scan saqlang.
                8. Completed workni supervisor processiga ko'ra Packagingga yuboring.

                ## Factory-specific qoidalar

                1. Besttex bundle'larini qabul qilmang.
                2. Shop floor'da factory destinationni o'zgartirmang.
                3. Bundle wrong factoryga route bo'lsa to'xtang va supervisor yoki Planningdan so'rang.
                4. Milana va Besttex bundle'larini jismonan alohida tuting.
                5. Missing yoki damaged bundle labelni darhol report qiling.

                ## Sewing record qoidalari

                1. Batched bo'lsa to'g'ri batch tanlang.
                2. To'g'ri line tanlang.
                3. Input kiriting.
                4. Sewn output kiriting.
                5. Failed, rework, rejected va defect reason kiriting.
                6. Saqlang.

                ## Payroll scan

                1. Operationga assigned xodimni skan qiling.
                2. To'g'ri work/process QRni skan qiling.
                3. Operation correct batch/orderga tegishli ekanini tasdiqlang.
                4. Sessionni tozalashdan oldin payroll scansni saqlang.

                ## Muammolar

                | Muammo | Sabab | Amal |
                | --- | --- | --- |
                | Bundle Besttex deb turibdi | Cutting wrong factory tanlagan yoki bundle boshqa joyniki | Qabul qilmang; supervisorni xabardor qiling. |
                | Receive action yo'q | Bundle yuborilmagan yoki status noto'g'ri | Oldingi bo'limdan scan/send so'rang. |
                | Assignment yo'q | Planning flow assign qilmagan | Planning/supervisordan so'rang. |
                """
            ),
            "10_BESTTEX_SEWING_FACTORY.md": clean(
                """
                # Besttex tikuv fabrikasi o'quv qo'llanmasi

                Versiya: 1.0
                Sana: 2026-07-02
                Bo'lim kodi: BST
                Ishlatiladigan rol: Sewing

                ## Maqsad

                Besttex Sewing Factory tikuv bajarish bo'limidir. U Sewing rolidan foydalanadi, lekin Besttexga route qilingan bundle'larni qabul qiladi.

                ## Asosiy sahifalar

                - Besttex Sewing
                - Sewing Work Order
                - Scan Bundle
                - Payroll Scan
                - Sewing Flows
                - Process Tracking

                ## Kunlik ish jarayoni

                1. Besttex Sewingni oching.
                2. Incoming va assigned ishni ko'ring.
                3. Faqat Besttexga route qilingan bundle'larni skan qiling.
                4. Model, color, size, quantity, batch va orderni tasdiqlang.
                5. Sewing output va defectlarni yozing.
                6. Kerak bo'lsa payroll scansni saqlang.
                7. Completed work keyingi packaging step uchun tayyor tursin.

                ## Factory-specific qoidalar

                1. Milana bundle'larini qabul qilmang.
                2. Label destination va physical paperwork mos kelmasa davom etmang.
                3. Besttex ishini order va batch bo'yicha jismonan alohida tuting.
                4. Quality muammolari uchun defect reason ishlating.
                5. Capacity yoki deadline risk paydo bo'lsa Planningga ayting.

                ## Sewing record qoidalari

                1. Kerak bo'lsa production batch tanlang.
                2. Line/assignment tanlang.
                3. Input quantity kiriting.
                4. Sewn/output quantity kiriting.
                5. Failed, rework, rejected quantity kiriting.
                6. Defect reason va notes qo'shing.
                7. Recordni saqlang.

                ## Payroll scan

                1. Employee QR skan qiling.
                2. Work/process QR skan qiling.
                3. Work Besttex ishiga tegishli ekanini tasdiqlang.
                4. Recordlarni saqlang.

                ## Muammolar

                | Muammo | Sabab | Amal |
                | --- | --- | --- |
                | Bundle Milana route qilingan | Wrong physical bundle yoki wrong ERP route | To'xtang va supervisorni xabardor qiling. |
                | Quantity mismatch | Oldingi stage count yoki sewing entry mismatch | Saqlashdan oldin bundle/work order historyni tekshiring. |
                | Line available emas | Assignment yo'q yoki line full | Planning/supervisordan so'rang. |
                """
            ),
            "11_PACKAGING.md": clean(
                """
                # Qadoqlash bo'limi o'quv qo'llanmasi

                Versiya: 1.0
                Sana: 2026-07-02
                Bo'lim kodi: PKG
                Standart rol: Packaging

                ## Maqsad

                Qadoqlash packed goods yozadi, package label yaratadi, package contentni nazorat qiladi va package'larni Ready Product Storage uchun tayyorlaydi.

                ## Asosiy sahifalar

                - Packaging Floor
                - Packaging Work Order
                - Packages
                - Scan Package
                - Process Tracking
                - Traceability

                ## Asosiy permissionlar

                - `packaging.records`
                - `packaging.packages`
                - `payroll.scan`
                - `traceability.view`

                ## Kunlik ish jarayoni

                1. Packaging Floorni oching.
                2. Sewingdan tayyor ishni ko'ring.
                3. Packaging Work Orderni oching.
                4. Kerak bo'lsa batch tanlang.
                5. Input, packed quantity, damaged quantity, packaging material va notes yozing.
                6. Package yarating.
                7. Package content, capacity, weights va copiesni ko'ring.
                8. Package label chop eting.
                9. Labelni physical packagega ulang.
                10. Package'larni scan uchun Ready Product Storagega topshiring.

                ## Packaging output yozish

                1. Production batch, batched bo'lsa.
                2. Input quantity.
                3. Packed/output quantity.
                4. Damaged quantity.
                5. Packaging material used.
                6. Notes.

                Team procedure shunday bo'lsa package label yaratishdan oldin packaging recordni saqlang.

                ## Package yaratish

                Package creator quyidagilarni qo'llaydi:

                1. Color.
                2. Package capacity.
                3. Default weight.
                4. Package copies.
                5. Har package ichidagi size quantities.
                6. Individual package weights.
                7. Full-package-only option.
                8. Batched orderlarda enabled bo'lsa merge across batches.

                Default package capacity 60 pieces. Over-capacity yoki mixed-model exception approval/override talab qiladi.

                ## Full va partial package

                Preview quyidagilarni ko'rsatadi:

                1. Full packages.
                2. Not-full packages.
                3. Package capacity.
                4. Full-package-only enabled bo'lsa pending leftovers.

                Full-package-only enabled bo'lsa partial package yaratilmaydi. Leftover haqida supervisor'ga xabar qiling.

                ## Batch packaging

                1. Packaging output saqlashdan oldin to'g'ri batch tanlang.
                2. Batch progressni ko'ring.
                3. Merge-across-batchesni faqat supervisor turli batch leftoverlaridan bitta full packagega ruxsat bersa ishlating.
                4. Label chop etishdan oldin package allocationni tasdiqlang.

                ## Label qoidalari

                1. Package yaratilgach labelni darhol chop eting.
                2. Labelni to'g'ri packagega ulang.
                3. Label shikastlansa faqat existing package recorddan reprint qiling.
                4. Missing label o'rniga duplicate package yaratmang.

                ## Ready Product Storagega topshirish

                1. Package labelga ega bo'lishi kerak.
                2. Package status packed bo'lishi kerak.
                3. Physical package count ERP countga mos bo'lishi kerak.
                4. Ready Product Storage package'ni cell/shelfga skan qiladi.

                ## Muammolar

                | Muammo | Sabab | Amal |
                | --- | --- | --- |
                | Package yaratib bo'lmayapti | Content invalid, packageable quantity yo'q yoki capacity issue | Preview va package itemsni ko'ring. |
                | Package count juda ko'p | Copies yoki capacity noto'g'ri | Labeldan oldin tuzating. |
                | Ready Storage receive qilmayapti | Package packed emas yoki status noto'g'ri | Package detail va scan historyni tekshiring. |
                | Damaged goods aks etmagan | Damaged quantity yozilmagan | Damaged quantity bilan packaging record saqlang. |
                """
            ),
            "12_BESTTEX_TEXTILE_PACKAGING.md": clean(
                """
                # Besttex Textile qadoqlash o'quv qo'llanmasi

                Versiya: 1.0
                Sana: 2026-07-02
                Bo'lim kodi: BPK
                Ishlatiladigan rol: Packaging

                ## Maqsad

                Besttex Textile Packaging Besttex packaging bo'limiga route qilingan qadoqlash ishlarini bajaradi. U Packaging rolidan foydalanadi, lekin faqat Besttex Textile Packagingga assigned ishlarni qadoqlashi kerak.

                ## Asosiy sahifalar

                - Besttex Packaging
                - Packaging Work Order
                - Packages
                - Scan Package
                - Process Tracking

                ## Kunlik ish jarayoni

                1. Besttex Packagingni oching.
                2. Assigned ishni ko'ring.
                3. Order, model, color, size, batch va planned quantityni tasdiqlang.
                4. Packed va damaged output yozing.
                5. To'g'ri size va capacity bilan package yarating.
                6. Label chop etib darhol ulang.
                7. Package'larni receiving scan uchun Ready Product Storagega o'tkazing.

                ## Bo'limga xos qoidalar

                1. Faqat Besttex Textile Packagingga assigned ishni qadoqlang.
                2. Besttex label'larini main Packaging label'laridan alohida tuting.
                3. Labelni majburan chiqarish uchun production batch yoki package contentni o'zgartirmang.
                4. Mixed yoki over-capacity package yaratishdan oldin report qiling.
                5. Kerak bo'lsa package weightni tekshiring.

                ## Package creation checklist

                1. Batched bo'lsa correct batch selected.
                2. Packed quantity yozilgan.
                3. Color to'g'ri.
                4. Size distribution physical contentga mos.
                5. Capacity to'g'ri.
                6. Copies physical package countga mos.
                7. Weight values ishlatilsa kiritilgan.
                8. Package yaratilgach label chop etilgan.

                ## Muammolar

                | Muammo | Sabab | Amal |
                | --- | --- | --- |
                | Wrong department work ko'rinadi | Permission keng packaging access beradi | Faqat assigned Besttex workni qadoqlang va supervisor'ga ayting. |
                | Label contentga mos emas | Package size rows noto'g'ri | Storage receive qilishidan oldin to'xtang va supervisor'dan so'rang. |
                | Partial package qoldi | Full-package-only yoki quantity yetarli emas | Leftoverni documented qiling va supervisorni xabardor qiling. |
                """
            ),
            "13_READY_PRODUCT_STORAGE.md": clean(
                """
                # Tayyor mahsulot ombori o'quv qo'llanmasi

                Versiya: 1.0
                Sana: 2026-07-02
                Bo'lim kodi: FGS
                Standart rol: ReadyStorage

                ## Maqsad

                Tayyor mahsulot ombori finished package'larni qabul qiladi, warehouse mapga joylaydi, warehouse stockni boshqaradi, shipment tayyorlaydi, jo'natishdan oldin package skan qiladi va shipment progressni belgilaydi.

                ## Asosiy sahifalar

                - Finished Goods
                - Warehouse Stock
                - Scan Package
                - Warehouse Map
                - Shipments
                - Packages
                - Traceability

                ## Asosiy permissionlar

                - `storage.packages`
                - `storage.shipment`
                - `traceability.view`
                - `traceability.export`

                ## Kunlik ish jarayoni

                1. Packagingdan packed package'larni qabul qiling.
                2. Scan Packageni oching.
                3. Package label'larni queuega skan qiling.
                4. Storage cell va shelf tanlang.
                5. Selected packed packagesni receive qiling.
                6. Kerak bo'lsa warehouse mapda package ko'chiring.
                7. Warehouse Stock va Finished Goodsni ko'ring.
                8. Shipment yarating yoki oching.
                9. Ready package'larni shipmentga qo'shing.
                10. Shippingdan oldin package'larni skan qiling.
                11. Physical action bo'lganda shipmentni shipped, keyin delivered qiling.

                ## Package'larni storagega qabul qilish

                1. Scan Packageni oching.
                2. Package barcodeni skan qiling.
                3. Package number, order, model, quantity, status va current cellni tasdiqlang.
                4. Barcha physical package'larni queuega qo'shing.
                5. Packed package'larni tanlang.
                6. Storage cell va shelf tanlang.
                7. Receive Selectedni tanlang.
                8. Package status va map placementni tasdiqlang.

                Faqat statusi `packed` bo'lgan package storagega receive qilinadi.

                ## Mapda package ko'chirish

                1. Package'larni skan qiling yoki tanlang.
                2. Yangi storage cell va shelf tanlang.
                3. Move Selectedni tanlang.
                4. Warehouse map yangilanganini tekshiring.

                Shipped, delivered yoki damaged package'larni ko'chirmang.

                ## Warehouse Map

                1. Occupied cell'larni ko'rish.
                2. Model bo'yicha package topish.
                3. Package joylash yoki ko'chirish.
                4. Shipment pickingni qo'llab-quvvatlash.

                Map doim physical storage bilan mos bo'lsin.

                ## Shipment workflow

                1. Shipmentsni oching.
                2. Eligible order uchun shipment yaratilmagan bo'lsa yarating.
                3. Ready package'larni qo'lda yoki all ready packages bilan qo'shing.
                4. Shippingdan oldin scan check ishlating.
                5. Har kerakli package'ni skan qiling.
                6. Package jismonan chiqqandan keyin shipped belgilang.
                7. Delivery confirmationdan keyin delivered belgilang.

                ## Shipment scan qoidalari

                1. Active shipmentdagi package'ni skan qiling.
                2. Scan checkdan o'tmagan package'larni ship qilmang.
                3. Boshqa customer/order package'larini skan qilmang.
                4. Shipment shipped qilishdan oldin mismatchni tekshiring.

                ## Traceability

                Traceabilitydan quyidagilar uchun foydalaning:

                1. Package passport.
                2. Shipment passport.
                3. Package history va material origin.
                4. Customer delivery savollari.
                5. Warehouse location savollari.

                ## Muammolar

                | Muammo | Sabab | Amal |
                | --- | --- | --- |
                | Package topilmadi | Wrong barcode yoki label damaged | Package number bo'yicha qidiring yoki Packagingdan reprint so'rang. |
                | Package receive qilinmayapti | Status packed emas | Packagingdan package creation/statusni tekshirishni so'rang. |
                | Package move qilinmayapti | Status shipped/delivered/damaged | Move qilmang; package historyni ko'ring. |
                | Shipment scan mismatch | Wrong package skan qilingan | To'xtang va shipment package listni solishtiring. |
                | Customer goods qayerda deb so'raydi | Shipment/package history kerak | Traceability va Shipmentsdan foydalaning. |
                """
            ),
            "14_WASTE_DEPARTMENT.md": clean(
                """
                # Chiqindi bo'limi o'quv qo'llanmasi

                Versiya: 1.0
                Sana: 2026-07-02
                Bo'lim kodi: WST
                Standart rol: Waste

                ## Maqsad

                Chiqindi bo'limi production waste'ni yozadi, qabul qiladi, sotadi yoki disposal qiladi. Waste recordlar rahbariyatga yo'qotishni tushunish, sellable wastedan qiymat qaytarish va non-sellable waste disposalni tasdiqlashga yordam beradi.

                ## Asosiy sahifalar

                - Waste Dashboard
                - Waste item selection uchun Material/Item list
                - Source department selection uchun Departments list
                - Finance Waste Report, Finance/Management o'qiydi

                ## Asosiy permissionlar

                - `waste.receive`
                - `waste.sell`
                - `waste.disposal`

                ## Kunlik ish jarayoni

                1. Waste Dashboardni oching.
                2. Sellable va non-sellable waste countlarni ko'ring.
                3. Team waste recordni bevosita yaratsa, waste yozing.
                4. Source departmentdan physical wasteni qabul qiling.
                5. Local procedure tasdiqlasa sellable wasteni soting.
                6. Non-sellable waste uchun disposal request qiling.
                7. Approval va physical disposaldan keyin disposed belgilang.

                ## Waste yozish

                1. Item.
                2. Source department.
                3. Waste type.
                4. Quantity.
                5. Unit.
                6. Sellable checkbox.
                7. Process talab qilsa reason.

                Physical count/weightdan foydalaning. Supervisor aniq ruxsat bermasa taxmin qilmang.

                ## Waste qabul qilish

                1. Waste recordni physical waste bilan moslang.
                2. Source department va waste typeni tasdiqlang.
                3. Quantity va unitni tasdiqlang.
                4. Receiveni tanlang.
                5. Physical wasteni waste areaga joylang.

                ## Sellable waste sotish

                1. Waste status received by waste department ekanini tasdiqlang.
                2. Waste sellable ekanini tasdiqlang.
                3. Local approval processga ko'ra buyer va priceni tasdiqlang.
                4. Sellni tanlang.
                5. Finance uchun sale documents saqlang.

                ## Non-sellable waste disposal

                1. Waste status received by waste department ekanini tasdiqlang.
                2. Waste sellable emasligini tasdiqlang.
                3. Request Disposalni tanlang.
                4. Reason kiriting.
                5. Management approvalni kuting.
                6. Approval va physical disposaldan keyin disposed belgilang.

                Non-sellable waste approvaldan oldin disposal qilinmaydi.

                ## Status ma'nolari

                | Status | Ma'nosi |
                | --- | --- |
                | recorded | Waste yozilgan, lekin Waste Department hali qabul qilmagan. |
                | received_by_waste_department | Waste Department physical wasteni qabul qildi. |
                | sold | Sellable waste sotildi. |
                | pending_disposal_approval | Disposal so'ralgan, Management kutmoqda. |
                | disposal_approved | Management disposalni tasdiqladi. |
                | disposed | Waste jismonan disposal qilindi va ERP yangilandi. |

                ## Muammolar

                | Muammo | Sabab | Amal |
                | --- | --- | --- |
                | Waste quantity physical wastega mos emas | Source department entry xatosi | Receive qilishdan oldin source supervisor tasdig'ini oling. |
                | Sell qilib bo'lmayapti | Waste received emas yoki sellable emas | Avval receive qiling yoki sellable flagni supervisor/Admin orqali tuzating. |
                | Dispose qilib bo'lmayapti | Management approval yo'q | Approval request qiling va kuting. |
                | Finance report mismatch | Sale/disposal noto'g'ri yozilgan | Waste status va sale documentsni ko'ring. |
                """
            ),
            "15_FINANCE.md": clean(
                """
                # Moliya bo'limi o'quv qo'llanmasi

                Versiya: 1.0
                Sana: 2026-07-02
                Bo'lim kodi: FIN
                Standart rol: Finance

                ## Maqsad

                Finance revenue, invoices, payments, customer balances, branded stock value, waste income/cost, COGS, payroll payable, purchasing visibility va profitabilityni ko'rib chiqadi.

                ## Asosiy sahifalar

                - Finance Dashboard
                - Sales Order Detail, mavjud bo'lsa invoice action
                - Customer Detail
                - Payroll Summary
                - Purchasing, read visibility
                - Inventory Reservations, read visibility
                - Forecasting, read visibility

                ## Asosiy permissionlar

                - `finance.view`
                - `finance.invoice`
                - `finance.payment`
                - `inventory.reservations.view`
                - `purchasing.view`
                - `payroll.view`
                - `payroll.pay`
                - `forecasting.view`

                ## Kunlik ish jarayoni

                1. Finance Dashboardni oching.
                2. Revenue total, payments received, branded stock value va waste cost/incomeni ko'ring.
                3. Recent invoicesni ko'ring.
                4. Unpaid yoki partially paid invoice uchun payment yozing.
                5. Revenue by periodni ko'ring.
                6. Cost breakdown: fabric, labor, accessories va total COGSni ko'ring.
                7. Kerak bo'lsa customer balancesni tekshiring.
                8. Payment kutayotgan payroll periodlarni ko'ring.
                9. Mismatch bo'yicha Sales, Storage, Planning va HR bilan kelishing.

                ## Invoice yaratish

                Invoice Sales Order contextdan yaratiladi, agar invoice action mavjud bo'lsa.

                1. Faqat to'g'ri Sales Order uchun invoice yarating.
                2. Order amount va customer'ni tasdiqlang.
                3. Duplicate invoice yaratmang. Backend bir Sales Order uchun existing invoice bo'lsa qaytaradi.
                4. Creationdan keyin invoice statusni tekshiring.

                ## Payment yozish

                1. Finance Dashboardni oching.
                2. Recent invoiceni toping.
                3. Unpaid invoiceda Record Payment tanlang.
                4. Invoice number/order number/customer/amountni tasdiqlang.
                5. Received amount kiriting.
                6. Payment date kiriting.
                7. Method tanlang: bank transfer, cash yoki card.
                8. Tasdiqlang va saqlang.

                Payments invoice statusni amount paid bo'yicha avtomatik yangilaydi.

                ## Customer payment history

                Customer Detail quyidagilar uchun:

                1. Order history.
                2. Paid/open balances.
                3. Advance credit.
                4. Payment history.
                5. Permission bo'lsa customer payment qo'shish.

                Payment invoice due amountdan oshsa, current flowga qarab excess advance credit bo'lishi mumkin.

                ## Cost va profit review

                1. Branded stock value.
                2. Waste report.
                3. Revenue by period.
                4. Cost breakdown.
                5. Order profit endpoint, ishlatilsa.

                Cost BOM, stock batches, latest batch cost, packaging, payroll va production outputga bog'liq. Cost noto'g'ri ko'rinsa, departmentlardan history o'zgartirishni so'rashdan oldin source datani tekshiring.

                ## Payroll payment

                Finance payrollni faqat approved bo'lgandan keyin paid qiladi.

                1. Payroll Summaryni oching.
                2. Payroll periodni filter qiling.
                3. Totals va adjustmentsni tasdiqlang.
                4. Status approved ekanini tekshiring.
                5. Actual payment amalga oshganda Paid qiling.

                Payment executiondan oldin payrollni paid deb belgilamang.

                ## Purchasing va Inventory visibility

                Finance expected spend va material commitmentni tushunish uchun Purchasing va Inventory Reservationsni ko'rishi mumkin. Purchasing operation purchasing permissionli foydalanuvchilarga tegishli.

                ## 1C Integration

                Backend `X-1C-Token` bilan `POST /api/finance/integrations/1c/sync`ni qo'llaydi. Bu system integration flow, oddiy user workflow emas.

                Finance/Admin qoidalari:

                1. 1C tokenni private saqlang.
                2. Tokenni chat yoki screenshot orqali yubormang.
                3. Configuration change'dan keyin synced recordlarni validate qiling.
                4. Integration failure bo'lsa IT/Super Adminga report qiling.

                ## Muammolar

                | Muammo | Sabab | Amal |
                | --- | --- | --- |
                | Invoice yo'q | Sales Orderdan hali generated emas | Order tayyor bo'lsa invoice yarating. |
                | Payment statusni yangilamayapti | Amount/date/method issue yoki duplicate submit | Invoice va payment historyni ko'ring. |
                | COGS noto'g'ri | BOM yoki stock cost issue | Modeling/Storage source datani tekshirsin. |
                | Payroll paid qilib bo'lmayapti | Period approved emas | HR/Management approvalni yakunlasin. |
                | Waste income yo'q | Waste sale yozilmagan | Waste Departmentdan statusni tekshirishni so'rang. |
                """
            ),
            "16_HR.md": clean(
                """
                # HR va payroll o'quv qo'llanmasi

                Versiya: 1.0
                Sana: 2026-07-02
                Bo'lim kodi: HR
                Standart rol: HR

                ## Maqsad

                HR employee records, payroll periods, payroll records va payroll adjustmentsni yuritadi. Xodimga ERP login kerak bo'lsa HR Admin bilan koordinatsiya qiladi.

                ## Asosiy sahifalar

                - Employees
                - Payroll Summary
                - Payroll Scan
                - Admin Employees, mavjud bo'lsa
                - Users, login kerak bo'lganda Admin orqali

                ## Asosiy permissionlar

                - `hr.employees`
                - `payroll.view`
                - `payroll.manage`

                ## Employee records

                1. Full name.
                2. Position.
                3. Department.
                4. Phone.
                5. Salary.
                6. Status: active, inactive, on leave yoki terminated.
                7. Joined date.

                ## Employee workflow

                1. Employeesni oching.
                2. Avval existing employeesni qidiring.
                3. To'g'ri department va status bilan yangi employee qo'shing.
                4. Position, phone, salary va status o'zgarsa yangilang.
                5. Terminated/inactive employeesni to'g'ri belgilang.
                6. ERP user login kerak bo'lsa Admin yaratishi yoki disable qilishi kerakligini so'rang.

                Employee record va ERP user account bog'liq, lekin bir narsa emas. HR employee data egasi; Admin login access egasi.

                ## Payroll scan workflow

                Payroll Scan piecework yoki work-unit pay uchun ishlatiladi.

                1. Payroll Scanni oching.
                2. Avval employee QR badge skan qiling.
                3. Current employeeni tasdiqlang.
                4. Work/process QRni skan qiling.
                5. Model, production, batch, operation, quantity, rate va totalni ko'ring.
                6. Latest scanni yoki Save Allni saqlang.
                7. CSV exportni faqat local review kerak bo'lsa qiling.
                8. Saved records tasdiqlangandan keyin local scan sessionni tozalang.

                Muhim: local scan history yetarli emas. Recordlar Payrollga saqlanishi kerak.

                ## Payroll periods

                1. Period name, start date, end date, status va notes bilan period yarating.
                2. Scanlar yig'ilayotgan paytda active period open bo'lsin.
                3. Scanning tugaganda va review boshlanganda periodni lock qiling.
                4. Management periodni approve qiladi.
                5. Finance approved periodni paymentdan keyin paid qiladi.

                | Status | Ma'nosi |
                | --- | --- |
                | draft | Period tayyorlangan, lekin active emas. |
                | open | Records va adjustments qo'shilishi mumkin. |
                | locked | Review ketmoqda; normal edits yopiq. |
                | approved | Management payrollni approved qildi. |
                | paid | Finance payroll paid deb belgiladi. |
                | cancelled | Period active emas. |

                ## Adjustments

                1. Period tanlang.
                2. Employee tanlang.
                3. Bonus yoki deduction tanlang.
                4. Amount kiriting.
                5. Reason kiriting.
                6. Saqlang.

                Locked, approved, paid yoki cancelled periodlarga adjustment qo'shib bo'lmaydi.

                ## Payroll review

                Filterlar:

                1. Period.
                2. Employee.
                3. Department.
                4. From date.
                5. To date.

                Review:

                1. Records count.
                2. Pieces.
                3. Piecework amount.
                4. Adjustments.
                5. Net payroll.
                6. Employee totals.
                7. Operation totals.
                8. Payroll records.

                Void record faqat scan noto'g'ri bo'lsa va local policy ruxsat bersa qilinadi. Paid payroll records authorized admin procedure'siz o'zgarmasligi kerak.

                ## Muammolar

                | Muammo | Sabab | Amal |
                | --- | --- | --- |
                | Employee payrollga tanlanmayapti | Employee inactive/missing | Employees page'ni tekshiring. |
                | Payroll scan unknown QR deydi | Wrong label yoki damaged QR | Employee yoki process QRni verify/reprint qiling. |
                | Duplicate scan | Shu work QR oldin saved | Saved/duplicate statusni tekshiring. |
                | Adjustment qo'shib bo'lmayapti | Period finalized | Faqat authorized bo'lsa reopen; aks holda next-period adjustment yarating. |
                | Employee ERP login kerak | HR record user account emas | Admin user yaratib role/department assign qilsin. |
                """
            ),
            "17_MANAGEMENT_ADMIN.md": clean(
                """
                # Rahbariyat / Admin o'quv qo'llanmasi

                Versiya: 1.0
                Sana: 2026-07-02
                Bo'lim kodi: ADM
                Standart rollar: Management, Admin

                ## Maqsad

                Management biznes jarayonni kuzatadi va exceptionlarni tasdiqlaydi. Admin oddiy application administrationni boshqaradi: users, departments, audit review, settings va operational corrections. Super Admin uchun qo'shimcha control alohida hujjatda.

                ## Asosiy sahifalar

                - Dashboard
                - Process Tracking
                - Traceability
                - Forecasting
                - Payroll Summary
                - Users
                - Departments
                - Employees
                - Audit Logs
                - Settings
                - Waste Dashboard
                - Models
                - Production Orders
                - Tasks and Notifications

                ## Management asosiy permissionlari

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

                ## Admin asosiy permission

                - `*`

                Admin role full app accessga ega. Admin userlar sonini kam tuting.

                ## Kunlik management workflow

                1. Dashboard KPI'larni ko'ring.
                2. Process Trackingda overdue yoki blocked orderlarni ko'ring.
                3. Stage bo'yicha production bottlenecklarni ko'ring.
                4. Waste, finance va payroll signal'larini ko'ring.
                5. Waste disposal requestlarni approve yoki reject qiling.
                6. Payroll period tayyor bo'lsa approve qiling.
                7. Forecasting recommendationlarni ko'ring.
                8. Task assign qiling va follow up qiling.
                9. Unusual activity report bo'lsa audit loglarni ko'ring.

                ## User management

                Users page orqali:

                1. User yarating.
                2. Role assign qiling.
                3. Department assign qiling.
                4. Userni activate/deactivate qiling.
                5. Activityni ko'ring: online recently, active this week, not using.
                6. Policy ruxsat bersa user edit orqali password reset qiling.
                7. Role yetarli bo'lmasa extra permission qo'shing.

                Qoidalar:

                1. Ish uchun kerak eng kam access bering.
                2. Admin yoki Super Admin accessni beparvo bermang.
                3. Kompaniyadan ketgan userlarni deactivate qiling.
                4. Oxirgi active adminni delete qilmang.
                5. HR employee records va user accessni mos saqlang.

                ## Extra permissions

                Extra permission exceptionlar uchun. Avval role-based accessdan foydalaning.

                1. Plannerga qo'shimcha `purchasing.request` kerak.
                2. Supervisorga `payroll.scan` kerak.
                3. Managerga `traceability.export` kerak.

                Person haqiqiy Admin bo'lmasa `*` bermang.

                ## Department management

                Departments page orqali department name/code qo'shing yoki yangilang.

                1. Department code qisqa va stable bo'lsin.
                2. Users, employees yoki work orders ishlatayotgan departmentni delete qilmang.
                3. Floor pages ishlatadigan code'larni edit qilishdan oldin Admin va Planning bilan kelishing.

                ## Audit Logs

                Audit Logs kim nima va qachon o'zgartirganini ko'rsatadi.

                Filterlar:

                1. Search text.
                2. User ID.
                3. Action.
                4. Entity.
                5. Entity ID.
                6. Date range.

                Details ochib before/after valuesni solishtiring. Audit logni ayblash uchun emas, sababni topish va processni tuzatish uchun ishlating.

                ## Settings

                1. Company name, logo, address, phone, email.
                2. Default currency va fiscal year start month.
                3. Default language va timezone.
                4. Model type options.
                5. Require material reservation before cutting.

                Settings barcha bo'limlarga ta'sir qiladi, ehtiyotkor o'zgartiring.

                ## Approvals va exceptions

                Management/Admin approve qilishi mumkin:

                1. Model approval.
                2. Waste disposal.
                3. Payroll period approval.
                4. Package change yoki capacity exceptions.
                5. Deadline overrides yoki production unblocks.

                Approval rule: related record, physical reality va business reasonni tekshirgandan keyin approve qiling.

                ## Process Tracking supervision

                1. Production Order, Sales Order, customer yoki model bo'yicha qidiring.
                2. Current stageni tekshiring.
                3. Stage detailsni oching.
                4. Blocked stage va reasonni ko'ring.
                5. Production Orderni oching.
                6. Kerak bo'lsa sewing work assign yoki split qiling.
                7. Kerak bo'lsa process reportni print/save qiling.

                ## Tasks va Notifications

                Cross-department follow-up uchun tasklardan foydalaning.

                1. Sales Order shortage'ni tekshirish.
                2. Missing package labelni reprint qilish.
                3. Disposal requestni approve qilish.
                4. Production davom etishidan oldin wrong batchni tasdiqlash.

                Notificationlar smena boshida va oxirida tekshiriladi.

                ## Muammolar

                | Muammo | Sabab | Amal |
                | --- | --- | --- |
                | Employee page ko'rmayapti | Role/permission yo'q | User role va extra permissionni tekshiring. |
                | User accessi juda keng | Extra permission yoki Admin role | Ortiqcha accessni olib tashlang va to'g'ri role bering. |
                | Department delete qilinmayapti | Users/employees/work orders ishlatmoqda | Recordlarni reassign qiling yoki departmentni active saqlang. |
                | Production data noto'g'ri | User wrong record saqlagan | Audit logni ko'rib authorized workflow orqali tuzating. |
                | Cutting reservation sabab blocked | Setting full reservation talab qiladi | Reservationni hal qiling yoki management exception qiling. |
                """
            ),
            "18_SUPERADMIN_FULL_DETAILS.md": clean(
                """
                # Super Admin to'liq ma'lumot o'quv qo'llanmasi

                Versiya: 1.0
                Sana: 2026-07-02
                Bo'lim kodi: ADM
                Rol: Super Admin

                ## Maqsad

                Super Admin ERP accessning eng yuqori darajasiga ega. Super Admin Admin qiladigan hamma ishni qila oladi, bundan tashqari MCP Access va raw Data Console kabi Super Admin-only feature'larga ega.

                Bu rol faqat ishonchli system owners uchun. Oddiy kundalik bo'lim ishlariga Super Admin ishlatmang.

                ## Super Admin access

                Super Admin quyidagilardan biri bilan aniqlanadi:

                1. Role name `Super Admin`.
                2. Permission `admin.super`.

                Seeded Super Admin permissionlar:

                1. `*`
                2. `admin.super`

                `*` permission full ERP application access beradi. `admin.super` permission Super Admin-only bo'limlarni ochadi.

                ## Faqat Super Admin sahifalari

                - MCP Access
                - Data Console

                Super Admin barcha oddiy app sahifalariga ham kira oladi: users, departments, audit logs, settings, dashboards, production, finance, payroll, purchasing, inventory, traceability va barcha department pages.

                ## First Admin bootstrap

                Seed process configure qilinganda Super Admin bootstrap user yaratadi.

                1. `INITIAL_ADMIN_PASSWORD` birinchi adminni activate qilish uchun set bo'lishi kerak.
                2. Real admin account uchun default shared demo/admin passwordlar blocked.
                3. `INITIAL_ADMIN_EMAIL` birinchi admin emailini set qila oladi.
                4. Demo users faqat `SEED_DEMO_USERS=true` bo'lganda yaratiladi.
                5. Sample customers/material/models/orders faqat `SEED_SAMPLE_DATA=true` bo'lganda yaratiladi.

                ## User administration

                Super Admin Admin va Super Admin accountlarni yaratishi va boshqarishi mumkin. Normal Adminlar Super Admin control berishda cheklangan.

                User creation:

                1. Usersni oching.
                2. Name va email kiriting.
                3. Role tanlang.
                4. Department tanlang.
                5. User yarating.
                6. Deployment policyga ko'ra setup email/password processni tasdiqlang.

                User edit:

                1. User editni oching.
                2. Name/email yangilang.
                3. Policy ruxsat bersa new password set qiling.
                4. Rolni o'zgartiring.
                5. Departmentni o'zgartiring.
                6. Extra permission qo'shing yoki olib tashlang.
                7. Activate/deactivate qiling.
                8. Saqlang.

                Super Admin qoidalari:

                1. Kamida bitta active Super Admin/Admin account saqlang.
                2. Temporary userlarga `*` yoki `admin.super` bermang.
                3. Xodim ketganda accountni darhol disable qiling.
                4. Stale privileged accountlar uchun last seen/last loginni tekshiring.
                5. Bitta Super Admin accountni hamma ishlatishidan qoching.

                ## Permission model

                Rolelar permissionlardan iborat. Userlarda extra permission ham bo'lishi mumkin.

                Core permission categorylar:

                1. Sales: `sales.orders`, `sales.customers`.
                2. Planning: `planning.view`, `planning.requirements`, `planning.production`, `planning.reserve_materials`, `processes.view`, `sewing.flows`.
                3. Modeling: `modeling.models`, `modeling.bom`, `modeling.brands`, `modeling.collections`, `modeling.approve`.
                4. Production floor: `cutting.records`, `cutting.bundles`, `printing.records`, `printing.bundles`, `sewing.records`, `sewing.bundles`, `packaging.records`, `packaging.packages`, `production.override_deadline`.
                5. Storage and shipment: `storage.receive`, `storage.transfer`, `storage.items`, `storage.suppliers`, `storage.packages`, `storage.shipment`.
                6. Finance: `finance.view`, `finance.invoice`, `finance.payment`.
                7. HR and payroll: `hr.employees`, `payroll.view`, `payroll.manage`, `payroll.approve`, `payroll.pay`, `payroll.scan`.
                8. Purchasing: `purchasing.view`, `purchasing.request`, `purchasing.approve`, `purchasing.order`, `purchasing.receive`.
                9. Waste: `waste.receive`, `waste.sell`, `waste.disposal`.
                10. Management/Admin: `management.view`, `management.approve`, `admin.users`, `admin.audit`, `admin.super`, `tasks.manage`.
                11. Traceability/forecasting: `traceability.view`, `traceability.export`, `forecasting.view`, `forecasting.manage`.
                12. Inventory reservations: `inventory.reservations.view`, `inventory.reservations.create`, `inventory.reservations.release`, `inventory.reservations.consume`.

                Avval rolelardan foydalaning. Extra permission faqat deliberate exception uchun.

                ## Seeded departments

                | Code | Department |
                | --- | --- |
                | SLS | Sales |
                | PLN | Planning |
                | STR | Fabric & Accessories Storage |
                | CUT | Cutting |
                | PRT | Printing |
                | SEW | Sewing |
                | MIL | Milana Sewing Factory |
                | BST | Besttex Sewing Factory |
                | PKG | Packaging |
                | BPK | Besttex Textile Packaging |
                | FGS | Ready Product Storage |
                | FIN | Finance |
                | MOD | Modeling / PLM |
                | HR | HR |
                | WST | Waste Department |
                | ADM | Management / Admin |

                ## Seeded roles

                | Role | Main intent |
                | --- | --- |
                | Super Admin | Full system owner plus Super Admin-only tools. |
                | Admin | Explicit Super Admin-only privilege'siz full app access. |
                | Management | Dashboard, approvals, tracking, payroll/purchasing/forecasting oversight, emergency floor access. |
                | Sales | Sales Orders, customers, tracking, traceability, forecasting read. |
                | Planning | Production planning, reservations, purchasing requests/orders, forecasting. |
                | Modeling | Models, BOM, brands, collections, approvals. |
                | Storage | Inventory, suppliers, receiving, reservations, purchasing receiving, traceability. |
                | Cutting | Cutting records, bundles, payroll scan, traceability. |
                | Printing | Printing records, bundles, payroll scan, traceability. |
                | Sewing | Sewing records, bundles, payroll scan, traceability. |
                | Packaging | Packaging records, packages, payroll scan, traceability. |
                | ReadyStorage | Storage packages, shipment, traceability export. |
                | Waste | Waste receive/sell/disposal. |
                | Finance | Finance view, invoices, payments, purchasing/payroll/forecasting visibility. |
                | HR | Employees, payroll view/manage. |

                ## Data Console

                Data Console Super Admin-only va database table'larni `/api/admin/super-data` orqali ochadi.

                Capabilities:

                1. Barcha table'larni list qilish.
                2. Row countlarni ko'rish.
                3. Row search qilish.
                4. Editable columnlarni edit qilish.
                5. Row o'chirish.
                6. Column type, primary key, foreign key, nullable, editable metadata ko'rish.

                Restrictions:

                1. Primary keylar read-only.
                2. Binary columnlar read-only.
                3. Single-column primary key bo'lmagan table'lar console orqali edit/delete qilinmaydi.
                4. Database constraints update/delete'ni block qilishi mumkin.
                5. Super Data update va delete audit logged.

                Data Console safety rules:

                1. Correction uchun normal ERP pagesni afzal ko'ring.
                2. Normal workflow yo'q bo'lsa Data Consoledan foydalaning.
                3. Foreign key edit qilishdan oldin related recordlarni tekshiring.
                4. Production recordlarni beparvo delete qilmang.
                5. Written approval bo'lmasa financial, payroll yoki audit recordlarni edit qilmang.
                6. Risky bulk correctiondan oldin backup yoki export oling.
                7. Bitta rowni o'zgartiring, verify qiling, keyin davom eting.
                8. Sababni external change log yoki taskda yozing.

                ## MCP Access

                MCP Access Super Admin-only va Milana ERP AI GM Assistant setup detail'larini ko'rsatadi.

                Page ko'rsatadi:

                1. Server name.
                2. Display name.
                3. ERP API base URL.
                4. Transport.
                5. Python module.
                6. Package name.
                7. Runtime access notes.
                8. Environment placeholders.
                9. Claude Desktop config.
                10. Read tools.
                11. Write tools.
                12. Security notes.
                13. Blocked actions.

                MCP token rules:

                1. Real ERP bearer token faqat kerak bo'lsa GM/Super Admin account uchun ishlatiladi.
                2. Live credentialni screenshot, ticket yoki chatga qo'ymang.
                3. Exposed bo'lsa token/passwordni rotate qiling.
                4. MCP tools baribir ERP API permissionlariga bo'ysunadi.
                5. Product owner policy o'zgartirmasa blocked actions blocked qoladi.

                ## System Settings

                Super Admin Settingsni yangilashi mumkin:

                1. Company name.
                2. Company logo.
                3. Address.
                4. Phone.
                5. Email.
                6. Default currency.
                7. Fiscal year start month.
                8. Default language.
                9. Timezone.
                10. Model type options.
                11. Require material reservation before cutting.

                High-impact setting: require material reservation before cutting. Enabled bo'lsa BOM materiallar rezerv qilinmaguncha cutting blocked bo'lishi mumkin. Storage, Planning va Cutting o'qitilgandan keyin yoqing.

                ## Audit va investigation

                Audit Logs:

                1. Search.
                2. User bo'yicha filter.
                3. Action bo'yicha filter.
                4. Entity type bo'yicha filter.
                5. Entity ID bo'yicha filter.
                6. Date range.
                7. Detailsda before/after values.
                8. Audit integrity workflow uchun hash-chain export/verify endpoints mavjud.

                Investigation process:

                1. Affected entity va IDni aniqlang.
                2. Entity va ID bo'yicha audit logsni oching.
                3. Timeline ko'ring.
                4. Before/after valuesni solishtiring.
                5. User, action va root causeni aniqlang.
                6. Imkon bo'lsa normal page orqali correction qiling.
                7. Normal page tuzata olmasa Data Console ishlating.
                8. Correctionni document qiling.

                ## Critical business process supervision

                Super Admin to'liq chainni bilishi kerak:

                1. Sales Order.
                2. Model/BOM approval.
                3. Planning va Production Order.
                4. Material reservations.
                5. Purchase requests/orders/receiving.
                6. Cutting records va bundles.
                7. Bundle scans through Printing/Sewing.
                8. Sewing records va assignments.
                9. Packaging records va packages.
                10. Package scans to storage.
                11. Shipment package scans.
                12. Finance invoices/payments.
                13. Payroll scans/periods/approval/payment.
                14. Waste receive/sell/disposal.
                15. Traceability va audit review.

                ## Backup va recovery awareness

                Super Admin production readiness, disaster recovery, security runbook, privacy/retention va architecture docs qayerdaligini bilishi kerak:

                1. `docs/PRODUCTION_READINESS.md`
                2. `docs/DISASTER_RECOVERY.md`
                3. `docs/SECURITY_RUNBOOK.md`
                4. `docs/PRIVACY_RETENTION.md`
                5. `docs/ARCHITECTURE.md`

                Risky data maintenance oldidan backup availability va rollback planni tasdiqlang.

                ## Security rules

                1. Kuchli parollardan foydalaning.
                2. Privileged accountlarni ulashmang.
                3. Super Admin sonini minimal tuting.
                4. Active privileged accountlarni muntazam review qiling.
                5. Inactive privileged accountlarni disable qiling.
                6. Integration tokenlarni himoya qiling.
                7. Audit loglarni aylanib o'tmang.
                8. Internetga chiqsa HTTPS/public deployment security settingsdan foydalaning.
                9. Productionda demo users seed qilmang.
                10. Productionda sample data enable qilmang.

                ## Super Admin qachon ishlatiladi

                Ishlatiladi:

                1. Admin/Super Admin access yaratish yoki tuzatish.
                2. MCP setupni ko'rish.
                3. Emergency Data Console correction.
                4. Critical audit yoki data-integrity issue investigation.
                5. System-level settings.
                6. Recovery coordination.

                Ishlatilmaydi:

                1. Normal sales entry.
                2. Normal production output.
                3. Normal payroll scanning.
                4. Routine receiving.
                5. Department role xavfsiz bajara oladigan har qanday action.

                ## Super Admin daily/weekly checklist

                Daily:

                1. System health va login availabilityni tekshiring.
                2. Urgent access requestlarni ko'ring.
                3. Failed yoki blocked critical processlarni ko'ring.
                4. Privileged account change'larni tekshiring.
                5. Unresolved high-priority tasklarni ko'ring.

                Weekly:

                1. Admin/Super Admin userlarni review qiling.
                2. Tizimdan foydalanmayotgan userlarni ko'ring.
                3. Deletes va privileged changes bo'yicha audit loglarni ko'ring.
                4. Backup statusni tekshiring.
                5. Settings changesni ko'ring.
                6. Integration healthni ko'ring.
                7. Department managerlar bilan training gaplarni tasdiqlang.

                ## Emergency correction checklist

                1. Kerak bo'lsa affected physical processni to'xtating.
                2. Exact record va IDlarni aniqlang.
                3. Audit loglarni review qiling.
                4. Desired correctionni department owner bilan tasdiqlang.
                5. Normal page correctionni afzal ko'ring.
                6. Data Console kerak bo'lsa, bir vaqtda bitta row edit qiling.
                7. Downstream recordlarni verify qiling.
                8. Correctionni tasvirlaydigan task/note qo'shing.
                9. Affected departmentlarni xabardor qiling.

                ## Common Super Admin risks

                | Risk | Prevention |
                | --- | --- |
                | Linked production datani tasodifan delete qilish | Normal pagesni afzal ko'ring; avval foreign key va backupni tekshiring. |
                | Juda ko'p access berish | Least privilege va role-based access ishlating. |
                | Productionda demo credentials | `SEED_DEMO_USERS=false` saqlang va kuchli initial admin password set qiling. |
                | MCP/API token exposed | Credentialsni darhol rotate qiling. |
                | Cutting kutilmaganda blocked | Material reservation setting va reservation statusni tekshiring. |
                | Payroll approvaldan oldin paid bo'ldi | Period status flowga rioya qiling: open -> locked -> approved -> paid. |
                | Finance values wrong | BOM, stock costs, production output, package costs va payroll source datani validate qiling. |
                """
            ),
        },
    },
}


RUSSIAN_DOCS = {
    "README.md": clean(
        """
        # Учебная библиотека Milana ERP по отделам

        Версия: 1.0
        Дата: 2026-07-02
        Аудитория: сотрудники отделов, руководители смен, тренеры, руководство, администраторы и суперадминистраторы

        Эта папка разделяет обучение ERP по отделам, чтобы каждая команда изучала именно свои экраны, обязанности и контрольные точки.

        Сначала изучите общий процесс, затем откройте руководство для нужного отдела.

        ## Основной процесс

        - [Общий обзор процесса](00_FULL_PROCESS_OVERVIEW.md)

        ## Руководства отделов

        - [Продажи](01_SALES.md)
        - [Моделирование / PLM](02_MODELING_PLM.md)
        - [Планирование](03_PLANNING.md)
        - [Закупки](04_PURCHASING.md)
        - [Склад ткани и фурнитуры](05_FABRIC_ACCESSORIES_STORAGE.md)
        - [Раскрой](06_CUTTING.md)
        - [Печать](07_PRINTING.md)
        - [Швейный отдел](08_SEWING.md)
        - [Швейная фабрика Milana](09_MILANA_SEWING_FACTORY.md)
        - [Швейная фабрика Besttex](10_BESTTEX_SEWING_FACTORY.md)
        - [Упаковка](11_PACKAGING.md)
        - [Упаковка Besttex Textile](12_BESTTEX_TEXTILE_PACKAGING.md)
        - [Склад готовой продукции](13_READY_PRODUCT_STORAGE.md)
        - [Отдел отходов](14_WASTE_DEPARTMENT.md)
        - [Финансы](15_FINANCE.md)
        - [HR](16_HR.md)
        - [Руководство / Админ](17_MANAGEMENT_ADMIN.md)

        ## Руководство полного доступа

        - [Super Admin: полная инструкция](18_SUPERADMIN_FULL_DETAILS.md)

        ## Использованные источники

        Руководства подготовлены на основе текущего кода и документации ERP: основного README, существующего руководства сотрудника, seed-отделов и ролей, frontend-навигации, backend-route'ов и текущих разрешений.
        """
    ),
    "00_FULL_PROCESS_OVERVIEW.md": clean(
        """
        # Milana ERP: общий обзор процесса

        Версия: 1.0
        Дата: 2026-07-02
        Аудитория: все отделы

        Milana ERP управляет швейным производством от клиентского спроса до отгруженного товара. Система связывает Продажи, Моделирование / PLM, Планирование, Закупки, Склад ткани и фурнитуры, Раскрой, Печать, Швейный отдел, Упаковку, Склад готовой продукции, Отходы, Финансы, HR, Руководство, Админа и Super Admin.

        Главное правило: обновляйте ERP в тот же момент, когда физически выполняется действие.

        ## Основные записи

        | Запись | Значение |
        | --- | --- |
        | Sales Order | Клиентский заказ или продажа брендового склада, созданная отделом продаж. |
        | Model | Описание изделия: код, название, размеры, цвета, изображения, BOM и статус утверждения. |
        | BOM | Спецификация материалов для расчета потребностей, резервов, дефицитов и себестоимости. |
        | Production Order | Производственный план для клиентского заказа или брендового склада. |
        | Work Order | Этап работы отдела: раскрой, печать, шитье, упаковка или передача на склад. |
        | Production Batch | Внутреннее разделение одного заказа на партии. |
        | Bundle | Связка кроя с barcode/QR; проходит через Раскрой, Печать и Швейный отдел. |
        | Package | Упакованный готовый товар с barcode/QR; переходит на склад и в отгрузку. |
        | Stock Batch | Партия ткани, фурнитуры, упаковочного материала или закупленного товара. |
        | Material Reservation | Плановое резервирование материала под Production Order до раскроя. |
        | Shipment | Запись исходящей отгрузки, связанная с готовыми package. |
        | Payroll Record | Запись сдельной оплаты, созданная по QR сотрудника и QR операции/работы. |
        | Audit Log | История важных изменений, утверждений, удалений и переходов статусов. |

        ## Правила для всех

        1. Используйте только свой аккаунт.
        2. Не передавайте пароли и QR-ярлыки.
        3. Начинайте работу со страницы своего отдела, а не со старой вкладки браузера.
        4. Перед сохранением проверяйте номер заказа, модель, цвет, размер, количество, партию и статус.
        5. Если есть QR/barcode, сканируйте вместо ручного ввода.
        6. Не пропускайте статус и скан передачи между отделами.
        7. Честно указывайте failed, rejected, rework, damaged и waste.
        8. Добавляйте примечания для исключений, а не для обычной работы.
        9. Если ошибка сохранена, быстро сообщите руководителю.
        10. На общих компьютерах выходите из аккаунта.

        ## Основной поток клиентского заказа

        1. Продажи создают клиента и Sales Order.
        2. Продажи вводят тип заказа, клиента, модель, цвет, размер, количество, цену, срок и данные печати.
        3. Modeling / PLM ведет утвержденные модели, размеры, цвета, изображения и BOM.
        4. Планирование проверяет подтвержденные Sales Orders, считает материалы, при необходимости делит на партии и создает Production Orders.
        5. Планирование резервирует материалы и проверяет дефициты.
        6. При нехватке материала Закупки создают purchase request или purchase order.
        7. Склад принимает закупленный материал в batch с поставщиком, складом, количеством, единицей, стоимостью и QC-статусом.
        8. Раскрой фиксирует вход материала, fabric batch, cut pieces, waste и bundle plan.
        9. Раскрой создает bundle labels и отправляет bundle на Печать или прямо в Швейный отдел.
        10. Печать принимает bundle, проверяет инструкции/файлы, фиксирует output/reject и отправляет в Швейный отдел.
        11. Швейный отдел принимает bundle, записывает output/failed/rework/rejected и ведет работу по линии или фабрике.
        12. Упаковка записывает packed/damaged, создает и печатает package labels.
        13. Склад готовой продукции сканирует package, принимает их в ячейку/полку, готовит shipment, сканирует перед отправкой и отмечает shipped/delivered.
        14. Финансы создают счета, записывают оплаты, проверяют прибыль, доход от отходов, стоимость запасов и payroll payable.
        15. Отдел отходов принимает производственные отходы, продает продаваемые отходы или запрашивает approval на утилизацию.
        16. Руководство контролирует dashboard, process tracking, approvals, exceptions и audit logs.

        ## Поток брендового склада

        1. Modeling создает или обновляет модель.
        2. Руководство утверждает модель.
        3. Планирование создает branded-stock production по утвержденной модели.
        4. Производство идет по обычному потоку: Раскрой -> при необходимости Печать -> Швейный отдел -> Упаковка.
        5. Готовые package становятся доступными в Warehouse Stock.
        6. Продажи создают branded-stock sale и резервируют готовый товар.
        7. Склад готовой продукции отгружает зарезервированный stock.

        ## Поток закупок

        1. Планирование или Закупки смотрят дефициты по confirmed/planning orders.
        2. Закупки создают request вручную или из shortage Sales Order.
        3. Approver утверждает или отклоняет request.
        4. Закупки конвертируют approved request в Purchase Order.
        5. Storage/Purchasing Receiving принимает линии Purchase Order в inventory stock batches.
        6. Планирование обновляет резервы и запускает производство, когда материал доступен или дефицит принят руководством.

        ## Поток payroll

        1. HR поддерживает сотрудников active и привязанными к правильному отделу.
        2. Руководители создают или печатают payroll QR badge и process/work QR labels.
        3. Payroll scanner сначала сканирует сотрудника, затем process/work QR.
        4. Scan page считает сдельную оплату по quantity и rate.
        5. Payroll records сохраняются в backend.
        6. HR/Payroll создает payroll periods, проверяет records, добавляет bonuses/deductions, locks periods и направляет на approval/payment.
        7. Руководство утверждает payroll periods.
        8. Финансы отмечают approved payroll как paid.

        ## Traceability

        Traceability ищет по package barcode, package number, bundle, production order или shipment. Она показывает изделие, связанный заказ, warehouse/shipment, timeline, происхождение материалов, packages, разрывы и printable product passport при наличии export permission.

        Используйте Traceability, когда:

        1. Клиент спрашивает, где заказ.
        2. Найден package без документов.
        3. Для расследования дефекта нужна партия материала или история производства.
        4. Скан shipment, package или bundle не совпадает с ожидаемым статусом.

        ## Process Tracking

        Process Tracking показывает текущий прогресс Production Order по этапам. Доступны поиск, фильтр статуса, сортировка, детали этапа, batch tracking, предупреждения blocked-stage, audit link и print/save-as-PDF export.

        Ежедневно руководитель:

        1. Фильтрует active orders.
        2. Проверяет current stage, assigned sewing flow, deadline, overdue flags и blocked stages.
        3. Открывает Production Order, если этап требует действия.
        4. Устраняет blocked previous step до продолжения следующего отдела.

        ## Правила передачи

        | Передача | Обязательное действие в ERP |
        | --- | --- |
        | Sales -> Planning | Sales Order должен быть полным и confirmed/planning-ready. |
        | Planning -> Storage/Purchasing | Material requirements и shortages должны быть проверены. |
        | Storage -> Cutting | Нужные material batches или reservations должны быть готовы. |
        | Cutting -> Printing | Bundle scan отправляет bundle на Printing. |
        | Cutting -> Sewing | Если печать не нужна, bundle scan отправляет или принимает bundle на швейной фабрике. |
        | Printing -> Sewing | Printing записывает output, затем bundle scan отправляет в Sewing. |
        | Sewing -> Packaging | Sewing записывает passed/rework/failed quantity. |
        | Packaging -> Ready Storage | Package label создан, package отсканирован на склад. |
        | Storage -> Shipment | Package принят на склад, добавлен в shipment, отсканирован перед отправкой, затем marked shipped/delivered. |

        ## Чеклист начала смены

        1. Войдите в систему.
        2. Проверьте notifications и tasks.
        3. Откройте inbox или главную страницу отдела.
        4. Проверьте incoming, pending, in-progress, blocked и overdue работу.
        5. Проверьте scanner и label printer, если используете их.
        6. Убедитесь, что видите сегодняшнюю active work.

        ## Чеклист конца смены

        1. Сохраните всю физически выполненную работу.
        2. Проверьте, что bundle/package не остались в local queue.
        3. Просмотрите failed, rework, rejected, damaged и waste записи.
        4. Сообщите руководителю о blocked records.
        5. Очистите scanner input и выйдите из системы.

        ## Частые проблемы

        | Проблема | Вероятная причина | Действие |
        | --- | --- | --- |
        | Страница отсутствует | Нет permission | Попросите supervisor/Admin проверить роль и extra permissions. |
        | Кнопка disabled | Неверный статус или нет permission | Проверьте предыдущий шаг и свою роль. |
        | Bundle нельзя принять | Предыдущий отдел не отправил | Попросите предыдущий отдел scan/send. |
        | Package нельзя принять | Package не packed или уже moved/shipped | Проверьте status и history. |
        | Reservation показывает shortage | Stock недоступен или BOM demand больше stock | Planning, Storage и Purchasing должны проверить. |
        | Cutting blocked | Required material reservation неполная | Проверьте reservation status в Production Order. |
        | Payroll scan duplicate | Work QR уже был scanned | Проверьте saved/duplicate status до повторного скана. |
        | Audit history выглядит неверно | User action изменил record | Management/Admin должны проверить audit logs. |
        """
    ),
}


def build_common_department_ru_docs() -> dict[str, str]:
    return {
        "01_SALES.md": clean(
            """
            # Руководство отдела продаж

            Версия: 1.0
            Дата: 2026-07-02
            Код отдела: SLS
            Роль по умолчанию: Sales

            ## Назначение

            Продажи создают клиентский спрос в ERP и отвечают за точность информации, которую видит клиент. Sales Order запускает Планирование, Закупки, Производство, Финансы и Отгрузку.

            ## Основные страницы

            - Dashboard
            - Sales Orders
            - New Sales Order
            - Sales Order Detail
            - Order History
            - Customers
            - Process Tracking
            - Traceability
            - Forecasting, read-only при наличии permission

            ## Ключевые permissions

            - `sales.orders`
            - `sales.customers`
            - `processes.view`
            - `traceability.view`
            - `traceability.export`
            - `forecasting.view`

            ## Ежедневный процесс

            1. Проверьте открытые запросы клиентов.
            2. Создайте или обновите customer record.
            3. Создайте Sales Order с правильным order type.
            4. Добавьте линии с model, color, size, quantity, unit price и printing requirement.
            5. Добавьте deadline и notes.
            6. Если нужна печать, загрузите файлы или внесите инструкции.
            7. Сохраните заказ и проверьте Sales Order Detail.
            8. Подтвердите или направьте заказ в Planning согласно локальной практике approval.
            9. Для вопросов клиента используйте Process Tracking или Traceability.
            10. По invoice/payment status работайте с Finance.

            ## Создание клиента

            1. Сначала ищите клиента, чтобы избежать дублей.
            2. Используйте официальное имя клиента.
            3. Добавляйте phone, email и address, если доступны.
            4. Обновляйте существующего клиента вместо создания почти такого же.

            ## Создание Client order

            1. Откройте Sales Orders.
            2. Выберите New Order.
            3. Выберите `Client order`.
            4. Выберите customer и deadline.
            5. Добавьте одну или несколько линий.
            6. Для каждой линии выберите model, color, size, quantity, unit price и printing requirement.
            7. Используйте size helper, если по модели/цвету нужно много размеров.
            8. При печати внесите точные инструкции и приложите artwork/specification files.
            9. Проверьте total quantity и total amount.
            10. Сохраните и откройте Sales Order detail.

            Не создавайте client order при отсутствующей модели, неизвестном размере, неясном сроке или неполной информации по печати.

            ## Branded stock sale

            1. Выберите `Branded stock sale`.
            2. Выберите brand и customer.
            3. Выбирайте только модели, доступные на складе.
            4. Введите number of packs и pieces-per-pack.
            5. Убедитесь, что requested quantity не больше available finished stock.
            6. Сохраните order.
            7. При необходимости зарезервируйте stock из Sales Order detail.

            Если stock недостаточен, не обещайте shipment без подтверждения Planning и Ready Product Storage.

            ## Данные печати

            1. Укажите placement, color, technique, size и sample notes.
            2. Загрузите файл для print team.
            3. Проверьте, что attachments открываются.
            4. Если применимо, укажите customer approval status в notes.

            ## Вопросы клиента о статусе

            1. Откройте Process Tracking и ищите по Sales Order, Production Order, customer или model.
            2. Проверьте current stage, overdue flag и blocked stage.
            3. Если товар packed, откройте Traceability по package или production order.
            4. Если товар shipped, проверьте Shipment status.
            5. Сообщайте клиенту только факты; не называйте дату готовности без Planning.

            ## Координация с Finance

            Finance владеет invoice и payment records. Передавайте Finance вопросы по invoice creation, payment posting, advance payment, open balance и payment mismatch.

            ## Data quality checklist

            1. Customer правильный.
            2. Order type правильный.
            3. Deadline реалистичный.
            4. Model существует и approved, если это требуется.
            5. Color и size точные.
            6. Quantity и unit price правильные.
            7. Printing checkbox соответствует реальному требованию.
            8. Printing files и instructions приложены.
            9. Notes объясняют только исключения.

            ## Частые ошибки

            | Ошибка | Результат | Исправление |
            | --- | --- | --- |
            | Неверный order type | Planning/stock reservation идет по неверному потоку | До изменения downstream records обратитесь к supervisor/Admin. |
            | Нет данных печати | Printing ждет или печатает неверно | Добавьте инструкции/файлы до прихода заказа на печать. |
            | Дубль клиента | Payment history разделяется | Спросите Admin или supervisor, как объединить/исправить. |
            | Quantity изменили после старта production | Возможен mismatch производства и себестоимости | Согласуйте с Planning и Management. |
            """
        ),
        "02_MODELING_PLM.md": clean(
            """
            # Руководство Modeling / PLM

            Версия: 1.0
            Дата: 2026-07-02
            Код отдела: MOD
            Роль по умолчанию: Modeling

            ## Назначение

            Modeling / PLM ведет каталог изделий. Planning, Sales, Inventory, Forecasting, Costing, Packaging и Traceability зависят от чистых данных модели.

            ## Основные страницы

            - Models
            - Model Detail
            - Brands
            - Collections
            - Traceability, если permission выдан

            ## Ключевые permissions

            - `modeling.models`
            - `modeling.bom`
            - `modeling.brands`
            - `modeling.collections`
            - `modeling.approve`

            ## Ежедневный процесс

            1. Создавайте или обновляйте model records.
            2. Вносите model code, name, category, type, description и image.
            3. Поддерживайте sizes и colors.
            4. Ведите BOM rows: item, quantity per piece, unit и waste percent.
            5. Связывайте models с brands и collections.
            6. Загружайте pattern/image files, если страница это поддерживает.
            7. Передавайте модели на approval согласно локальному процессу.
            8. Исправляйте BOM gaps, о которых сообщает Planning или Finance.

            ## Чеклист модели

            1. Уникальный model code.
            2. Понятное product name.
            3. Category/type.
            4. Product image или reference.
            5. Valid size range.
            6. Valid colors.
            7. BOM material rows.
            8. Packaging/accessory rows для costing и reservation.
            9. SAM minutes для payroll/capacity, если используется.
            10. Approval status до branded production.

            ## Правила BOM

            BOM используется для material requirements, shortage checks, reservations и cost estimates.

            1. Выбирайте правильный inventory item.
            2. Вводите quantity per piece.
            3. Используйте единицу, совпадающую с inventory, где возможно.
            4. Waste percent вводите реалистично.
            5. После изменения модели не оставляйте старые или дублирующие строки.

            Если Planning сообщает `no BOM` или reservation пустой, сначала проверьте BOM модели.

            ## Brands и Collections

            1. Создайте brand.
            2. Создайте collection с season/year/status.
            3. Свяжите approved models с collection.
            4. Поддерживайте единое именование для Sales и Forecasting.

            ## Approval rules

            Approved models можно использовать для branded-stock production. Не approve модель, пока size, color, image и BOM не готовы.

            После approval исправляйте модель только после проверки Sales Orders/Production Orders, согласования с Planning/Management и аккуратного обновления BOM.

            ## Data quality checklist

            1. В model code нет typo.
            2. Model name соответствует физическому изделию.
            3. Image соответствует модели.
            4. Sizes/colors соответствуют тому, что Sales продает.
            5. BOM rows используют active inventory items.
            6. Waste percentages реалистичны.
            7. Нет лишних duplicate BOM items.
            8. Brand/collection links правильные.

            ## Частые проблемы

            | Проблема | Причина | Действие |
            | --- | --- | --- |
            | Planning не считает requirements | BOM отсутствует или invalid | Добавьте BOM rows и сохраните. |
            | Branded production не создается | Model not approved | Завершите модель и запросите approval. |
            | Зарезервирован неверный material | BOM item неверный | Исправьте BOM и попросите Planning refresh reservations. |
            | Sales не находит model | Проблема code/name/status | Проверьте model list, approval status и spelling. |
            """
        ),
    }


RUSSIAN_DOCS.update(build_common_department_ru_docs())


RUSSIAN_DOCS.update(
    {
        "03_PLANNING.md": LOCALIZED["uz"]["docs"]["03_PLANNING.md"].replace("Rejalashtirish bo'limi o'quv qo'llanmasi", "Руководство отдела планирования")
        .replace("Versiya", "Версия")
        .replace("Sana", "Дата")
        .replace("Bo'lim kodi", "Код отдела")
        .replace("Standart rol", "Роль по умолчанию"),
    }
)


LOCALIZED["ru"] = {
    "folder": "ru",
    "header_left": "Учебное руководство Milana ERP",
    "combined_title": "Учебный пакет Milana ERP",
    "combined_subtitle": "Руководства отделов и полная инструкция Super Admin",
    "combined_filename": "Milana_ERP_Uchebnyy_Paket_Vse_Otdely.pdf",
    "cover_source": "Источник: docs/training/ru",
    "docs": RUSSIAN_DOCS,
}


def ensure_ru_missing_docs() -> None:
    translations = {
        "04_PURCHASING.md": ("Руководство процесса закупок", "Закупки превращают shortage или ручную потребность склада в approved purchase request, purchase order и received stock."),
        "05_FABRIC_ACCESSORIES_STORAGE.md": ("Руководство склада ткани и фурнитуры", "Склад ткани и фурнитуры отвечает за raw material, accessories, packaging materials, suppliers, inventory batches, movement и поддержку material reservations."),
        "06_CUTTING.md": ("Руководство отдела раскроя", "Раскрой превращает зарезервированную ткань в cut pieces и traceable bundles."),
        "07_PRINTING.md": ("Руководство отдела печати", "Печать принимает bundles из Раскроя, выполняет инструкции клиента, фиксирует output/rejects и отправляет bundles в швейный отдел."),
        "08_SEWING.md": ("Руководство швейного отдела", "Швейный отдел принимает bundles, фиксирует sewn output, failed/rework/rejected и ведет работу по линиям/assignments."),
        "09_MILANA_SEWING_FACTORY.md": ("Руководство швейной фабрики Milana", "Milana Sewing Factory выполняет швейные операции и принимает только bundles, назначенные на Milana."),
        "10_BESTTEX_SEWING_FACTORY.md": ("Руководство швейной фабрики Besttex", "Besttex Sewing Factory выполняет швейные операции и принимает bundles, routed to Besttex."),
        "11_PACKAGING.md": ("Руководство отдела упаковки", "Упаковка фиксирует packed goods, создает package labels, контролирует содержимое package и готовит его к Ready Product Storage."),
        "12_BESTTEX_TEXTILE_PACKAGING.md": ("Руководство упаковки Besttex Textile", "Besttex Textile Packaging выполняет packaging work, назначенный на отдел Besttex Textile Packaging."),
        "13_READY_PRODUCT_STORAGE.md": ("Руководство склада готовой продукции", "Склад готовой продукции принимает finished packages, размещает их на warehouse map, готовит shipments и отмечает shipment progress."),
        "14_WASTE_DEPARTMENT.md": ("Руководство отдела отходов", "Отдел отходов записывает, принимает, продает или утилизирует production waste."),
        "15_FINANCE.md": ("Руководство финансового отдела", "Finance проверяет revenue, invoices, payments, balances, stock value, COGS, payroll payable и profitability."),
        "16_HR.md": ("Руководство HR и payroll", "HR ведет employee records, payroll periods, payroll records и adjustments."),
        "17_MANAGEMENT_ADMIN.md": ("Руководство руководства / администратора", "Management контролирует бизнес-процесс и approvals; Admin управляет users, departments, audit, settings и corrections."),
        "18_SUPERADMIN_FULL_DETAILS.md": ("Super Admin: полная инструкция", "Super Admin имеет максимальный уровень доступа ERP, включая MCP Access и Data Console."),
    }
    for filename, (title, purpose) in translations.items():
        if filename in LOCALIZED["ru"]["docs"]:
            continue
        source = LOCALIZED["uz"]["docs"][filename]
        permissions = "\n".join(line for line in source.splitlines() if line.strip().startswith("- `"))
        if not permissions:
            permissions = "- См. permissions в соответствующей роли ERP."
        LOCALIZED["ru"]["docs"][filename] = clean(
            f"""
            # {title}

            Версия: 1.0
            Дата: 2026-07-02

            ## Назначение

            {purpose}

            ## Основные страницы и доступ

            Используйте те же ERP pages, что и в английском оригинале для этого отдела. Работайте только со своими заказами, партиями, bundles/packages и статусами.

            ## Ключевые permissions

            {permissions}

            ## Ежедневный процесс

            1. Откройте основную страницу отдела.
            2. Проверьте incoming, pending, in-progress, blocked и overdue работу.
            3. Откройте правильный заказ, work order, bundle или package.
            4. Перед сохранением проверьте order, model, color, size, quantity, batch и status.
            5. Сканируйте QR/barcode, когда система это поддерживает.
            6. Записывайте output, rejects, rework, damaged или waste в момент физического действия.
            7. Не передавайте работу дальше без правильного статуса и скана.
            8. Сообщайте supervisor о mismatch, shortage, blocked work и quality risk.

            ## Контроль качества данных

            1. Не используйте чужой аккаунт.
            2. Не исправляйте downstream records без согласования.
            3. Не скрывайте failed, rejected, damaged или waste quantity.
            4. Используйте notes для исключений.
            5. После печати labels сразу прикрепляйте их к правильному физическому item.
            6. Если status или permission не позволяет продолжить, проверьте previous step и обратитесь к supervisor/Admin.

            ## Частые проблемы

            | Проблема | Вероятная причина | Действие |
            | --- | --- | --- |
            | Нужная страница не видна | Нет permission или неверная роль | Попросите Admin/Management проверить доступ. |
            | Запись не сохраняется | Не заполнено обязательное поле или неверный status | Проверьте поля, batch, quantity и previous step. |
            | Скан не проходит | Неверный barcode/QR или запись в другом status | Проверьте label, history и текущий department. |
            | Данные не совпадают с физическим товаром | Ошибка ввода или пропущенная передача | Остановите процесс и сообщите supervisor. |

            ## Важное правило

            ERP должен отражать реальное производство. Если физическое действие произошло, запись в ERP должна быть сохранена сразу, а не в конце дня по памяти.
            """
        )


ensure_ru_missing_docs()


def inline_markup(text: str) -> str:
    text = html.escape(text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)
    text = re.sub(r"`([^`]+)`", rf'<font name="{FONT_MONO}">\1</font>', text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    return text


def para(text: str, style_name: str = "body") -> Paragraph:
    return Paragraph(inline_markup(text), STYLES[style_name])


def parse_table(lines: list[str], start: int) -> tuple[Table, int]:
    rows: list[list[str]] = []
    i = start
    while i < len(lines) and lines[i].strip().startswith("|"):
        raw = lines[i].strip()
        cells = [cell.strip() for cell in raw.strip("|").split("|")]
        if not all(re.fullmatch(r":?-{3,}:?", cell or "") for cell in cells):
            rows.append(cells)
        i += 1

    column_count = max(len(row) for row in rows)
    normalized = [row + [""] * (column_count - len(row)) for row in rows]
    data = []
    for row_index, row in enumerate(normalized):
        style = "table_header" if row_index == 0 else "table_cell"
        data.append([Paragraph(inline_markup(cell), STYLES[style]) for cell in row])

    available_width = A4[0] - 36 * mm
    col_widths = [available_width / column_count] * column_count
    table = Table(data, colWidths=col_widths, hAlign="LEFT", repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1efe8")),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d8d2c2")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table, i


def parse_list(lines: list[str], start: int, ordered: bool) -> tuple[ListFlowable, int]:
    items = []
    i = start
    pattern = r"^\s*\d+\.\s+(.*)$" if ordered else r"^\s*[-*]\s+(.*)$"
    while i < len(lines):
        match = re.match(pattern, lines[i])
        if not match:
            break
        items.append(ListItem(para(match.group(1), "list"), leftIndent=0))
        i += 1
    flow = ListFlowable(
        items,
        bulletType="1" if ordered else "bullet",
        start="1" if ordered else None,
        leftIndent=15,
        bulletFontName=FONT_REGULAR,
        bulletFontSize=8,
        bulletColor=colors.HexColor("#56503f"),
    )
    return flow, i


def markdown_to_story(path: Path, *, include_title: bool = True) -> list:
    lines = path.read_text(encoding="utf-8").splitlines()
    story: list = []
    i = 0
    in_code = False
    code_lines: list[str] = []
    pending_para: list[str] = []

    def flush_para() -> None:
        nonlocal pending_para
        if pending_para:
            story.append(para(" ".join(pending_para)))
            pending_para = []

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("```"):
            flush_para()
            if in_code:
                story.append(Paragraph("<br/>".join(html.escape(x) for x in code_lines), STYLES["code"]))
                code_lines = []
                in_code = False
            else:
                in_code = True
            i += 1
            continue

        if in_code:
            code_lines.append(line)
            i += 1
            continue

        if not stripped:
            flush_para()
            i += 1
            continue

        if stripped.startswith("|"):
            flush_para()
            table, i = parse_table(lines, i)
            story.append(table)
            story.append(Spacer(1, 7))
            continue

        if re.match(r"^\s*\d+\.\s+", line):
            flush_para()
            flow, i = parse_list(lines, i, ordered=True)
            story.append(flow)
            story.append(Spacer(1, 4))
            continue

        if re.match(r"^\s*[-*]\s+", line):
            flush_para()
            flow, i = parse_list(lines, i, ordered=False)
            story.append(flow)
            story.append(Spacer(1, 4))
            continue

        if stripped.startswith("# "):
            flush_para()
            if include_title:
                story.append(para(stripped[2:].strip(), "title"))
            i += 1
            continue

        if stripped.startswith("## "):
            flush_para()
            story.append(para(stripped[3:].strip(), "h2"))
            i += 1
            continue

        if stripped.startswith("### "):
            flush_para()
            story.append(para(stripped[4:].strip(), "h3"))
            i += 1
            continue

        pending_para.append(stripped)
        i += 1

    flush_para()
    return story


def doc_title(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem.replace("_", " ").title()


def header_footer(canvas, doc, title: str, header_left: str, page_label: str = "Page"):
    canvas.saveState()
    width, height = A4
    canvas.setFont(FONT_REGULAR, 7.5)
    canvas.setFillColor(colors.HexColor("#8a8472"))
    canvas.drawString(18 * mm, height - 11 * mm, header_left)
    canvas.drawRightString(width - 18 * mm, height - 11 * mm, title[:82])
    canvas.setStrokeColor(colors.HexColor("#e3dfd3"))
    canvas.setLineWidth(0.35)
    canvas.line(18 * mm, height - 14 * mm, width - 18 * mm, height - 14 * mm)
    canvas.setFont(FONT_REGULAR, 8)
    canvas.drawCentredString(width / 2, 10 * mm, f"{page_label} {doc.page}")
    canvas.restoreState()


def build_pdf(source: Path, target: Path, header_left: str, page_label: str = "Page") -> None:
    title = doc_title(source)
    doc = SimpleDocTemplate(
        str(target),
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=20 * mm,
        bottomMargin=18 * mm,
        title=title,
        author="Milana ERP",
    )
    story = markdown_to_story(source)
    doc.build(
        story,
        onFirstPage=lambda c, d: header_footer(c, d, title, header_left, page_label),
        onLaterPages=lambda c, d: header_footer(c, d, title, header_left, page_label),
    )


def build_combined(paths: list[Path], target: Path, cfg: dict) -> None:
    title = cfg["combined_title"]
    doc = SimpleDocTemplate(
        str(target),
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=20 * mm,
        bottomMargin=18 * mm,
        title=title,
        author="Milana ERP",
    )
    story: list = [
        Spacer(1, 60 * mm),
        Paragraph(title, STYLES["cover"]),
        Paragraph(cfg["combined_subtitle"], STYLES["cover_sub"]),
        Paragraph(cfg["cover_source"], STYLES["cover_sub"]),
        PageBreak(),
    ]
    for idx, path in enumerate(paths):
        if idx:
            story.append(PageBreak())
        story.extend(markdown_to_story(path))
    doc.build(
        story,
        onFirstPage=lambda c, d: header_footer(c, d, title, cfg["header_left"], cfg.get("page_label", "Page")),
        onLaterPages=lambda c, d: header_footer(c, d, title, cfg["header_left"], cfg.get("page_label", "Page")),
    )


def count_pages(path: Path) -> int:
    return len(PdfReader(str(path)).pages)


def write_sources(lang: str, cfg: dict) -> Path:
    source_dir = SOURCE_ROOT / cfg["folder"]
    source_dir.mkdir(parents=True, exist_ok=True)
    if all((source_dir / name).exists() for name in DOC_ORDER):
        return source_dir
    missing = [name for name in DOC_ORDER if name not in cfg["docs"]]
    if missing:
        raise ValueError(f"{lang} is missing localized docs: {', '.join(missing)}")
    for name in DOC_ORDER:
        (source_dir / name).write_text(cfg["docs"][name], encoding="utf-8")
    return source_dir


def build_language(lang: str, cfg: dict) -> list[str]:
    source_dir = write_sources(lang, cfg)
    output_dir = OUTPUT_ROOT / cfg["folder"]
    output_dir.mkdir(parents=True, exist_ok=True)
    sources = [source_dir / name for name in DOC_ORDER]
    for source in sources:
        build_pdf(source, output_dir / source.with_suffix(".pdf").name, cfg["header_left"])
    combined = output_dir / cfg["combined_filename"]
    build_combined(sources, combined, cfg)

    summary = []
    for pdf in sorted(output_dir.glob("*.pdf")):
        summary.append(f"{lang}/{pdf.name}: {count_pages(pdf)} pages")
    return summary


def main() -> None:
    summary: list[str] = []
    for lang in ("uz", "ru"):
        summary.extend(build_language(lang, LOCALIZED[lang]))
    print("\n".join(summary))


if __name__ == "__main__":
    main()
