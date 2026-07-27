import type { LucideIcon } from "lucide-react";
import {
  AlertTriangle,
  BarChart3,
  Calculator,
  ClipboardCheck,
  ClipboardList,
  Coins,
  Eye,
  Factory,
  FileSearch,
  FileText,
  Link2,
  PackageSearch,
  QrCode,
  ScanLine,
  Search,
  Settings,
  ShieldCheck,
  Shirt,
  ShoppingBag,
  ShoppingCart,
  Truck,
  Users,
  Warehouse,
} from "lucide-react";
import type { Lang } from "@/lib/i18n/types";

type NavLink = {
  href: string;
  label: string;
};

export type PresentationCard = {
  title: string;
  text: string;
  Icon: LucideIcon;
};

type TextPresentationCard = Omit<PresentationCard, "Icon">;

export type LifecycleStep = {
  title: string;
  shortLabel: string;
  detail: string;
  tags: string[];
  Icon: LucideIcon;
};

type TextLifecycleStep = Omit<LifecycleStep, "Icon">;

export type DepartmentPanel = {
  name: string;
  scope: string;
  tools: string[];
};

export type PresentationContent = {
  localeName: string;
  nav: NavLink[];
  controls: {
    menu: string;
    closeMenu: string;
    language: string;
    theme: string;
    light: string;
    dark: string;
    login: string;
    explore: string;
  };
  hero: {
    title: string;
    subtitle: string;
    support: string;
    primaryAction: string;
    secondaryAction: string;
    valueCards: PresentationCard[];
    trust: string[];
  };
  problem: {
    heading: string;
    text: string;
    pains: string[];
  };
  promise: {
    heading: string;
    text: string;
    cards: PresentationCard[];
  };
  comparison: {
    heading: string;
    beforeTitle: string;
    afterTitle: string;
    before: string[];
    after: string[];
  };
  lifecycle: {
    heading: string;
    text: string;
    steps: LifecycleStep[];
  };
  benefits: {
    heading: string;
    text: string;
    groups: PresentationCard[];
  };
  departments: {
    heading: string;
    text: string;
    panels: DepartmentPanel[];
  };
  management: {
    heading: string;
    text: string;
    signals: string[];
  };
  difference: {
    heading: string;
    points: string[];
  };
  impact: {
    heading: string;
    outcomes: string[];
  };
  trust: {
    heading: string;
    text: string;
    highlights: PresentationCard[];
    stackLabel: string;
    stack: string;
  };
  finalCta: {
    heading: string;
    text: string;
    primaryAction: string;
    secondaryAction: string;
  };
  footer: {
    line: string;
  };
};

type PresentationText = Omit<PresentationContent, "hero" | "promise" | "lifecycle" | "benefits" | "trust"> & {
  hero: Omit<PresentationContent["hero"], "valueCards"> & { valueCards: TextPresentationCard[] };
  promise: Omit<PresentationContent["promise"], "cards"> & { cards: TextPresentationCard[] };
  lifecycle: Omit<PresentationContent["lifecycle"], "steps"> & { steps: TextLifecycleStep[] };
  benefits: Omit<PresentationContent["benefits"], "groups"> & { groups: TextPresentationCard[] };
  trust: Omit<PresentationContent["trust"], "highlights"> & { highlights: TextPresentationCard[] };
};

const nav = {
  en: [
    { href: "#problem", label: "Problem" },
    { href: "#flow", label: "Lifecycle" },
    { href: "#benefits", label: "Benefits" },
    { href: "#departments", label: "Departments" },
    { href: "#trust", label: "Trust" },
  ],
  ru: [
    { href: "#problem", label: "Проблема" },
    { href: "#flow", label: "Цикл" },
    { href: "#benefits", label: "Польза" },
    { href: "#departments", label: "Отделы" },
    { href: "#trust", label: "Основа" },
  ],
  uz: [
    { href: "#problem", label: "Muammo" },
    { href: "#flow", label: "Jarayon" },
    { href: "#benefits", label: "Foyda" },
    { href: "#departments", label: "Bo'limlar" },
    { href: "#trust", label: "Ishonch" },
  ],
} satisfies Record<Lang, NavLink[]>;

const valueIcons = [Eye, QrCode, Link2, Users];
const promiseIcons = [ClipboardCheck, AlertTriangle, Users];
const lifecycleIcons = [
  ShoppingCart,
  Shirt,
  ClipboardList,
  ShoppingBag,
  Warehouse,
  Factory,
  QrCode,
  Truck,
  Coins,
];
const benefitIcons = [Eye, AlertTriangle, ScanLine, Calculator, Users, BarChart3];
const trustIcons = [ShieldCheck, FileSearch, FileText, Settings, PackageSearch, Search];

const text: Record<Lang, PresentationText> = {
  en: {
    localeName: "English",
    nav: nav.en,
    controls: {
      menu: "Menu",
      closeMenu: "Close menu",
      language: "Language",
      theme: "Theme",
      light: "Light",
      dark: "Dark",
      login: "Open ERP",
      explore: "Explore lifecycle",
    },
    hero: {
      title: "Run Your Garment Factory From One Connected Control System",
      subtitle:
        "From customer order to finished shipment, Milana Ecosystem gives every department the same live truth.",
      support:
        "Stop managing production through scattered files, chats, and manual reports. Milana connects sales, planning, materials, production, warehouse, finance, payroll, and delivery into one traceable operating flow.",
      primaryAction: "Explore lifecycle",
      secondaryAction: "Open ERP",
      valueCards: [
        {
          title: "Live order visibility",
          text: "See what is confirmed, planned, produced, packed, shipped, paid, or at risk.",
        },
        {
          title: "QR-traceable production",
          text: "Know where every bundle, package, and shipment is, and who handled it.",
        },
        {
          title: "Connected stock and finance",
          text: "Connect materials, reservations, production costs, payments, waste, and stock value.",
        },
        {
          title: "Department-level accountability",
          text: "Give each team a clear workspace while management keeps full control.",
        },
      ],
      trust: ["Built for garment manufacturing", "Light and dark mode", "English, Russian, and Uzbek"],
    },
    problem: {
      heading:
        "Most factories do not lose money because people are not working hard. They lose money because information is disconnected.",
      text:
        "When order status, material movement, production progress, and finance numbers live in separate files or chats, managers only see the truth after delays become expensive.",
      pains: [
        "Managers do not know the true order status.",
        "Sales, planning, warehouse, production, and finance work in separate files or chats.",
        "Material shortages are discovered too late.",
        "Production delays are hard to predict.",
        "Finished goods, packages, and bundles are difficult to trace.",
        "Finance waits for manual updates to understand costs, payments, and profit.",
        "Manual reporting wastes time and creates mistakes.",
      ],
    },
    promise: {
      heading: "One order. One flow. One source of truth.",
      text:
        "Every customer order stays connected from sales confirmation to model data, material planning, purchasing, production, QR scans, warehouse movement, shipment, payment, and profit analysis.",
      cards: [
        {
          title: "Control every order",
          text: "Keep sales, model data, material needs, production work, shipment, and payment attached to one order record.",
        },
        {
          title: "See problems earlier",
          text: "Shortages, late work, missing scans, and delivery risks become visible before managers are forced to react.",
        },
        {
          title: "Make every department accountable",
          text: "Teams receive clear work queues and managers can trace what changed, who moved it, and when it happened.",
        },
      ],
    },
    comparison: {
      heading: "Before and after Milana",
      beforeTitle: "Before Milana",
      afterTitle: "After Milana",
      before: [
        "Orders tracked manually.",
        "Stock checked late.",
        "Departments wait for updates.",
        "Finance calculates after the fact.",
        "Managers ask people for status.",
        "Problems are discovered too late.",
      ],
      after: [
        "Every order has a live lifecycle.",
        "Shortages appear early.",
        "Departments receive clear work queues.",
        "QR scans show real movement.",
        "Finance sees cost, revenue, payment, and profit.",
        "Managers see risks before they become delays.",
      ],
    },
    lifecycle: {
      heading: "Your Entire Factory Flow, Connected Live",
      text:
        "Watch how one order moves through sales, models, planning, materials, production, QR tracking, shipment, and finance - with every department working from the same live truth.",
      steps: [
        {
          title: "Sales order",
          shortLabel: "Order received",
          detail:
            "Capture the customer order with payment status, confirmations, invoices, and production context connected from day one.",
          tags: ["Sales", "Finance"],
        },
        {
          title: "Product model",
          shortLabel: "Model approved",
          detail:
            "Keep model photos, sizes, BOM, operations, files, and costing rules in one approved product source.",
          tags: ["Design", "Costing"],
        },
        {
          title: "Planning",
          shortLabel: "Plan created",
          detail:
            "Turn demand into material needs, work orders, deadlines, and shortage warnings before production is blocked.",
          tags: ["Planning", "Production"],
        },
        {
          title: "Purchasing",
          shortLabel: "Materials requested",
          detail: "Buy what is actually needed based on real shortages, approvals, and production demand.",
          tags: ["Purchase", "Warehouse"],
        },
        {
          title: "Inventory",
          shortLabel: "Stock controlled",
          detail:
            "Know what materials and accessories are available, reserved, received, moved, returned, or running low.",
          tags: ["Warehouse", "Planning"],
        },
        {
          title: "Production floor",
          shortLabel: "Production moving",
          detail:
            "Give cutting, printing, sewing, packaging, and quality teams clear work queues and protected quantity rules.",
          tags: ["Cutting", "Sewing", "QC"],
        },
        {
          title: "QR traceability",
          shortLabel: "Every movement scanned",
          detail:
            "Trace bundles, packages, materials, scans, operators, and movement history when you need answers fast.",
          tags: ["Operators", "Audit"],
        },
        {
          title: "Shipment",
          shortLabel: "Shipment prepared",
          detail:
            "Control finished goods, package readiness, scan checks, dispatch, delivery status, and package history.",
          tags: ["Logistics", "Warehouse"],
        },
        {
          title: "Finance",
          shortLabel: "Profit visible",
          detail:
            "See revenue, payments, cost breakdowns, order profit, stock value, waste economics, and finance sync from real operations data.",
          tags: ["Finance", "Management"],
        },
      ],
    },
    benefits: {
      heading: "What managers get back",
      text:
        "The value is not a list of screens. The value is faster decisions, fewer mistakes, stronger accountability, and better protection of margin.",
      groups: [
        {
          title: "Know the truth of every order",
          text: "Sales, planning, production, warehouse, logistics, and finance all work from the same order record.",
        },
        {
          title: "Stop discovering problems too late",
          text: "Material shortages, late work, missing scans, and production risks become visible before they damage delivery.",
        },
        {
          title: "Turn factory movement into live data",
          text: "QR scans convert physical handoffs into traceable digital events across bundles, packages, and shipments.",
        },
        {
          title: "Protect profit from order to shipment",
          text: "Connect BOM costs, production operations, waste, stock, invoices, and payments to understand real order profitability.",
        },
        {
          title: "Give every department a focused workspace",
          text: "Each team sees only the tools and tasks they need, while management keeps full visibility.",
        },
        {
          title: "Replace manual reporting with daily control",
          text: "Dashboards show active production, late orders, output, defects, finance, stock, and follow-up tasks without waiting for manual reports.",
        },
      ],
    },
    departments: {
      heading: "Built around the way garment factories actually work",
      text:
        "Every department gets a focused workspace, but the order, materials, scans, packages, payments, and audit history stay connected.",
      panels: [
        {
          name: "Management",
          scope: "See active orders, late work, output, defects, money, traceability, and audit history in one control view.",
          tools: ["Dashboard", "Process tracking", "Traceability", "Audit logs"],
        },
        {
          name: "Sales",
          scope: "Manage customer orders, balances, invoices, payments, and shipment follow-up without losing production context.",
          tools: ["Sales orders", "Customers", "Invoices", "Payments"],
        },
        {
          name: "Planning",
          scope: "Create production orders, calculate material needs, detect shortages, and coordinate deadlines.",
          tools: ["Planning", "Forecasting", "Work orders", "Shortages"],
        },
        {
          name: "Storage",
          scope: "Control receipts, batches, warehouse movement, accessory issue and returns, and finished-goods stock.",
          tools: ["Inventory", "Batches", "Warehouse stock", "Warehouse map"],
        },
        {
          name: "Factory floor",
          scope: "Give cutting, printing, sewing, and packaging teams clear work queues with QR-based movement history.",
          tools: ["Cutting", "Printing", "Sewing", "Packaging"],
        },
        {
          name: "Logistics",
          scope: "Prepare packages, scan before shipment, dispatch finished goods, confirm delivery, and track package history.",
          tools: ["Packages", "Shipments", "Finished goods", "Scan checks"],
        },
        {
          name: "Finance",
          scope: "Connect revenue, invoices, payments, order profit, costs, branded-stock value, waste value, and 1C sync.",
          tools: ["Finance dashboard", "Payments", "Profit", "1C sync"],
        },
        {
          name: "HR and payroll",
          scope: "Connect employees, payroll summaries, process QR, and operation-based compensation inputs.",
          tools: ["Employees", "Payroll", "Process QR", "Paid operations"],
        },
      ],
    },
    management: {
      heading: "Manage the factory by signals, not by guessing.",
      text:
        "Milana gives managers daily operating views across production, planning, finance, inventory, waste, defects, and order progress.",
      signals: [
        "Late orders",
        "Active production",
        "Shortages",
        "Department output",
        "Defects and quality issues",
        "Payments and balances",
        "Stock value",
        "Waste cost or income",
        "Tasks and notifications",
      ],
    },
    difference: {
      heading: "Built for garment manufacturing, not generic office accounting.",
      points: [
        "Full lifecycle from sales to shipment.",
        "Built around garment models, BOM, sizes, colors, bundles, packages, and production departments.",
        "QR-first traceability for real factory movement.",
        "Production, warehouse, finance, payroll, and audit connected.",
        "Department-specific workflows.",
        "Management visibility without manual reporting.",
      ],
    },
    impact: {
      heading: "From factory chaos to factory control.",
      outcomes: [
        "Reduce manual reporting",
        "Reduce production confusion",
        "Reduce stock mistakes",
        "Reduce late discovery of shortages",
        "Improve delivery confidence",
        "Improve accountability",
        "Improve financial visibility",
        "Improve customer trust",
        "Reduce dependency on Excel, Telegram, WhatsApp, and manual status updates",
      ],
    },
    trust: {
      heading: "Built on a production-ready foundation",
      text:
        "Technical details belong behind the sales story, but they matter for trust. Milana is structured for secure access, auditability, integrations, and deployment.",
      highlights: [
        {
          title: "Secure role-based access",
          text: "Permission-aligned navigation and backend authorization keep each department inside its approved workflow.",
        },
        {
          title: "Audit trail",
          text: "Operational changes can be reviewed through audit history, making exceptions easier to investigate.",
        },
        {
          title: "Documented operations",
          text: "Architecture, security, disaster recovery, privacy retention, and training documents support handover and maintenance.",
        },
        {
          title: "Deployment-ready architecture",
          text: "The project includes deployment wiring and a clean separation between frontend, backend, database, and storage.",
        },
        {
          title: "API and integration foundation",
          text: "The system is prepared for machine access, finance sync, and future integrations where factory data needs to move.",
        },
        {
          title: "QR and barcode storage",
          text: "Bundle and package labels are generated and stored so factory movement can be scanned and traced.",
        },
      ],
      stackLabel: "Stack, briefly",
      stack: "FastAPI, PostgreSQL, Next.js, TypeScript, Tailwind, Docker, and Vercel deployment wiring.",
    },
    finalCta: {
      heading: "Ready to run every order with more control?",
      text:
        "Milana Ecosystem helps garment manufacturers manage every order, every material, every department, and every shipment from one connected system.",
      primaryAction: "Explore lifecycle",
      secondaryAction: "Open ERP",
    },
    footer: {
      line: "Milana Ecosystem. Factory control system for garment manufacturers.",
    },
  },
  ru: {
    localeName: "Русский",
    nav: nav.ru,
    controls: {
      menu: "Меню",
      closeMenu: "Закрыть меню",
      language: "Язык",
      theme: "Тема",
      light: "Светлая",
      dark: "Темная",
      login: "Открыть ERP",
      explore: "Изучить цикл",
    },
    hero: {
      title: "Управляйте швейной фабрикой из одной связанной системы контроля",
      subtitle:
        "От заказа клиента до готовой отгрузки Milana Ecosystem дает каждому отделу одну живую правду.",
      support:
        "Перестаньте управлять производством через разрозненные файлы, чаты и ручные отчеты. Milana связывает продажи, планирование, материалы, производство, склад, финансы, зарплату и доставку в один прослеживаемый операционный поток.",
      primaryAction: "Изучить цикл",
      secondaryAction: "Открыть ERP",
      valueCards: [
        {
          title: "Живая видимость заказов",
          text: "Видно, что подтверждено, запланировано, произведено, упаковано, отгружено, оплачено или находится в риске.",
        },
        {
          title: "Производство с QR-трассировкой",
          text: "Понимайте, где находится каждая пачка, упаковка и отгрузка, и кто с ними работал.",
        },
        {
          title: "Связанные склад и финансы",
          text: "Материалы, резервы, производственные затраты, оплаты, отходы и стоимость склада работают вместе.",
        },
        {
          title: "Ответственность по отделам",
          text: "Каждая команда получает свой рабочий экран, а руководство сохраняет полный контроль.",
        },
      ],
      trust: ["Создано для швейного производства", "Светлая и темная тема", "Английский, русский и узбекский"],
    },
    problem: {
      heading:
        "Большинство фабрик теряет деньги не потому, что люди плохо работают. Деньги теряются потому, что информация разорвана.",
      text:
        "Когда статус заказа, движение материалов, ход производства и финансовые цифры живут в разных файлах или чатах, руководство видит правду только после того, как задержки уже стали дорогими.",
      pains: [
        "Руководители не знают настоящий статус заказа.",
        "Продажи, планирование, склад, производство и финансы работают в отдельных файлах или чатах.",
        "Нехватка материалов обнаруживается слишком поздно.",
        "Производственные задержки трудно предсказать.",
        "Готовые изделия, упаковки и пачки сложно проследить.",
        "Финансы ждут ручных обновлений, чтобы понять затраты, оплаты и прибыль.",
        "Ручная отчетность тратит время и создает ошибки.",
      ],
    },
    promise: {
      heading: "Один заказ. Один поток. Один источник правды.",
      text:
        "Каждый клиентский заказ остается связанным от подтверждения продажи до данных модели, планирования материалов, закупки, производства, QR-сканов, движения склада, отгрузки, оплаты и анализа прибыли.",
      cards: [
        {
          title: "Контролируйте каждый заказ",
          text: "Продажи, модель, материалы, производство, отгрузка и оплата остаются в одной записи заказа.",
        },
        {
          title: "Видьте проблемы раньше",
          text: "Нехватки, просрочки, отсутствующие сканы и риски доставки видны до того, как нужно срочно реагировать.",
        },
        {
          title: "Сделайте отделы ответственными",
          text: "Команды получают понятные очереди работ, а менеджеры видят, что изменилось, кто переместил и когда.",
        },
      ],
    },
    comparison: {
      heading: "До и после Milana",
      beforeTitle: "До Milana",
      afterTitle: "После Milana",
      before: [
        "Заказы ведутся вручную.",
        "Склад проверяется поздно.",
        "Отделы ждут обновлений.",
        "Финансы считают постфактум.",
        "Менеджеры спрашивают статус у людей.",
        "Проблемы обнаруживаются слишком поздно.",
      ],
      after: [
        "У каждого заказа есть живой цикл.",
        "Нехватки появляются заранее.",
        "Отделы получают четкие очереди работ.",
        "QR-сканы показывают реальное движение.",
        "Финансы видят затраты, выручку, оплату и прибыль.",
        "Менеджеры видят риски до задержек.",
      ],
    },
    lifecycle: {
      heading: "Весь процесс фабрики связан в реальном времени",
      text:
        "Посмотрите, как один заказ проходит путь от продаж и модели до планирования, материалов, производства, QR-контроля, отгрузки и финансов - все отделы работают с одной актуальной информацией.",
      steps: [
        {
          title: "Заказ клиента",
          shortLabel: "Заказ принят",
          detail:
            "Заказ клиента, статус оплаты, подтверждения, счета и производственный контекст связаны с первого дня.",
          tags: ["Продажи", "Финансы"],
        },
        {
          title: "Модель продукта",
          shortLabel: "Модель утверждена",
          detail:
            "Фото модели, размеры, BOM, операции, файлы и правила расчета себестоимости хранятся в одном утвержденном источнике.",
          tags: ["Дизайн", "Костинг"],
        },
        {
          title: "Планирование",
          shortLabel: "План создан",
          detail:
            "Спрос превращается в потребности по материалам, производственные задания, сроки и предупреждения о нехватке до остановки производства.",
          tags: ["Планирование", "Производство"],
        },
        {
          title: "Закупки",
          shortLabel: "Материалы запрошены",
          detail: "Закупаются только нужные материалы на основе реальной нехватки, подтверждений и производственного спроса.",
          tags: ["Закупки", "Склад"],
        },
        {
          title: "Склад",
          shortLabel: "Склад под контролем",
          detail:
            "Видно, какие материалы и аксессуары доступны, зарезервированы, приняты, перемещены, возвращены или заканчиваются.",
          tags: ["Склад", "Планирование"],
        },
        {
          title: "Производство",
          shortLabel: "Производство движется",
          detail:
            "Раскрой, печать, швейный цех, упаковка и контроль качества получают понятные очереди задач и защищенные правила количества.",
          tags: ["Раскрой", "Шитье", "QC"],
        },
        {
          title: "QR-трассировка",
          shortLabel: "Каждое движение сканируется",
          detail:
            "Отслеживайте пачки, упаковки, материалы, сканы, операторов и историю движения, когда нужны быстрые ответы.",
          tags: ["Операторы", "Аудит"],
        },
        {
          title: "Отгрузка",
          shortLabel: "Отгрузка подготовлена",
          detail:
            "Контролируйте готовую продукцию, готовность упаковок, скан-проверки, отправку, статус доставки и историю упаковки.",
          tags: ["Логистика", "Склад"],
        },
        {
          title: "Финансы",
          shortLabel: "Прибыль видна",
          detail:
            "Видны выручка, платежи, структура затрат, прибыль заказа, стоимость склада, экономика отходов и финансовая синхронизация на основе реальных операций.",
          tags: ["Финансы", "Руководство"],
        },
      ],
    },
    benefits: {
      heading: "Что руководство получает обратно",
      text:
        "Ценность не в количестве экранов. Ценность в быстрых решениях, меньшем количестве ошибок, ответственности и защите маржи.",
      groups: [
        {
          title: "Знайте правду по каждому заказу",
          text: "Продажи, планирование, производство, склад, логистика и финансы работают с одной записью заказа.",
        },
        {
          title: "Не узнавайте о проблемах слишком поздно",
          text: "Нехватки материалов, просрочки, отсутствующие сканы и производственные риски видны до ущерба поставке.",
        },
        {
          title: "Превратите движение фабрики в живые данные",
          text: "QR-сканы превращают физические передачи в цифровые события по пачкам, упаковкам и отгрузкам.",
        },
        {
          title: "Защищайте прибыль от заказа до отгрузки",
          text: "BOM, операции, отходы, склад, счета и оплаты помогают понимать реальную прибыльность заказа.",
        },
        {
          title: "Дайте каждому отделу фокус",
          text: "Команды видят только свои инструменты и задачи, а руководство сохраняет полную видимость.",
        },
        {
          title: "Замените ручные отчеты ежедневным контролем",
          text: "Дашборды показывают активное производство, просрочки, выпуск, дефекты, финансы, склад и задачи без ожидания отчетов.",
        },
      ],
    },
    departments: {
      heading: "Построено вокруг реальной работы швейной фабрики",
      text:
        "У каждого отдела есть свой рабочий экран, но заказ, материалы, сканы, упаковки, оплаты и аудит остаются связанными.",
      panels: [
        {
          name: "Руководство",
          scope: "Активные заказы, просрочки, выпуск, дефекты, деньги, трассировка и аудит в одном контрольном виде.",
          tools: ["Dashboard", "Process tracking", "Traceability", "Audit logs"],
        },
        {
          name: "Продажи",
          scope: "Заказы клиентов, балансы, счета, оплаты и контроль отгрузки без потери производственного контекста.",
          tools: ["Sales orders", "Customers", "Invoices", "Payments"],
        },
        {
          name: "Планирование",
          scope: "Создание производственных заказов, расчет материалов, выявление нехваток и координация сроков.",
          tools: ["Planning", "Forecasting", "Work orders", "Shortages"],
        },
        {
          name: "Склад",
          scope: "Приемки, партии, движение по складу, выдача и возврат аксессуаров, готовая продукция.",
          tools: ["Inventory", "Batches", "Warehouse stock", "Warehouse map"],
        },
        {
          name: "Производство",
          scope: "Раскрой, печать, шитье и упаковка получают очереди работ с QR-историей движения.",
          tools: ["Cutting", "Printing", "Sewing", "Packaging"],
        },
        {
          name: "Логистика",
          scope: "Подготовка упаковок, скан перед отгрузкой, отправка готовых изделий, доставка и история упаковок.",
          tools: ["Packages", "Shipments", "Finished goods", "Scan checks"],
        },
        {
          name: "Финансы",
          scope: "Выручка, счета, оплаты, прибыль заказа, затраты, стоимость брендов, отходы и синхронизация 1C.",
          tools: ["Finance dashboard", "Payments", "Profit", "1C sync"],
        },
        {
          name: "HR и зарплата",
          scope: "Сотрудники, зарплатные сводки, process QR и вводы для оплаты по операциям.",
          tools: ["Employees", "Payroll", "Process QR", "Paid operations"],
        },
      ],
    },
    management: {
      heading: "Управляйте фабрикой по сигналам, а не догадками.",
      text:
        "Milana дает руководителям ежедневные операционные виды по производству, планированию, финансам, складу, отходам, дефектам и прогрессу заказов.",
      signals: [
        "Просроченные заказы",
        "Активное производство",
        "Нехватки",
        "Выпуск отделов",
        "Дефекты и качество",
        "Оплаты и балансы",
        "Стоимость склада",
        "Стоимость или доход от отходов",
        "Задачи и уведомления",
      ],
    },
    difference: {
      heading: "Создано для швейного производства, а не для обычной офисной бухгалтерии.",
      points: [
        "Полный цикл от продажи до отгрузки.",
        "Работа вокруг моделей, BOM, размеров, цветов, пачек, упаковок и производственных отделов.",
        "QR-first трассировка для реального движения фабрики.",
        "Производство, склад, финансы, зарплата и аудит связаны.",
        "Рабочие процессы по отделам.",
        "Видимость для руководства без ручной отчетности.",
      ],
    },
    impact: {
      heading: "От фабричного хаоса к фабричному контролю.",
      outcomes: [
        "Снизить ручную отчетность",
        "Снизить производственную путаницу",
        "Снизить складские ошибки",
        "Раньше видеть нехватки",
        "Повысить уверенность в доставке",
        "Усилить ответственность",
        "Улучшить финансовую видимость",
        "Повысить доверие клиентов",
        "Снизить зависимость от Excel, Telegram, WhatsApp и ручных обновлений статуса",
      ],
    },
    trust: {
      heading: "Построено на производственной основе",
      text:
        "Технические детали должны быть ниже основной истории, но они важны для доверия. Milana структурирована для безопасного доступа, аудита, интеграций и развертывания.",
      highlights: [
        {
          title: "Безопасный ролевой доступ",
          text: "Навигация и backend-авторизация используют согласованную модель прав для каждого отдела.",
        },
        {
          title: "Аудит действий",
          text: "Операционные изменения можно проверять через историю аудита, чтобы быстрее разбирать исключения.",
        },
        {
          title: "Документированные операции",
          text: "Архитектура, безопасность, disaster recovery, privacy retention и training docs помогают поддержке.",
        },
        {
          title: "Архитектура для развертывания",
          text: "Проект разделяет frontend, backend, базу данных и storage и готов к deployment wiring.",
        },
        {
          title: "API и интеграционная основа",
          text: "Система готова к машинному доступу, финансовой синхронизации и будущим интеграциям.",
        },
        {
          title: "QR и barcode storage",
          text: "Этикетки пачек и упаковок генерируются и хранятся, чтобы движение можно было сканировать и прослеживать.",
        },
      ],
      stackLabel: "Стек, кратко",
      stack: "FastAPI, PostgreSQL, Next.js, TypeScript, Tailwind, Docker и Vercel deployment wiring.",
    },
    finalCta: {
      heading: "Готовы управлять каждым заказом с большим контролем?",
      text:
        "Milana Ecosystem помогает швейным производителям управлять каждым заказом, материалом, отделом и отгрузкой из одной связанной системы.",
      primaryAction: "Изучить цикл",
      secondaryAction: "Открыть ERP",
    },
    footer: {
      line: "Milana Ecosystem. Система контроля фабрики для швейных производителей.",
    },
  },
  uz: {
    localeName: "O'zbek",
    nav: nav.uz,
    controls: {
      menu: "Menyu",
      closeMenu: "Menyuni yopish",
      language: "Til",
      theme: "Mavzu",
      light: "Yorug'",
      dark: "Qorong'i",
      login: "ERPni ochish",
      explore: "Jarayonni ko'rish",
    },
    hero: {
      title: "Tikuv fabrikangizni bitta ulangan nazorat tizimidan boshqaring",
      subtitle:
        "Mijoz buyurtmasidan tayyor jo'natmagacha Milana Ecosystem har bir bo'limga bir xil jonli haqiqatni beradi.",
      support:
        "Ishlab chiqarishni tarqoq fayllar, chatlar va qo'lda hisobotlar orqali boshqarishni to'xtating. Milana sotuv, reja, material, ishlab chiqarish, ombor, moliya, ish haqi va yetkazishni bitta kuzatiladigan operatsion oqimga ulaydi.",
      primaryAction: "Jarayonni ko'rish",
      secondaryAction: "ERPni ochish",
      valueCards: [
        {
          title: "Buyurtmalar jonli ko'rinadi",
          text: "Nima tasdiqlangan, rejalangan, ishlab chiqarilgan, qadoqlangan, jo'natilgan, to'langan yoki xavfda ekanini ko'ring.",
        },
        {
          title: "QR orqali kuzatiladigan ishlab chiqarish",
          text: "Har bir bog'lam, paket va jo'natma qayerda ekanini va kim ishlaganini biling.",
        },
        {
          title: "Ulangan ombor va moliya",
          text: "Materiallar, rezervlar, ishlab chiqarish xarajatlari, to'lovlar, chiqindi va ombor qiymatini bog'lang.",
        },
        {
          title: "Bo'limlar bo'yicha javobgarlik",
          text: "Har bir jamoaga aniq ish oynasi bering, rahbariyat esa to'liq nazoratni saqlaydi.",
        },
      ],
      trust: ["Tikuv ishlab chiqarishi uchun qurilgan", "Yorug' va qorong'i mavzu", "Ingliz, rus va o'zbek tillari"],
    },
    problem: {
      heading:
        "Ko'p fabrikalar pulni odamlar ishlamayotgani uchun emas, ma'lumot uzilganligi uchun yo'qotadi.",
      text:
        "Buyurtma holati, material harakati, ishlab chiqarish progressi va moliyaviy raqamlar alohida fayl yoki chatlarda turganda, rahbarlar haqiqatni kechikishlar qimmatga tushgandan keyin ko'radi.",
      pains: [
        "Rahbarlar buyurtmaning haqiqiy holatini bilmaydi.",
        "Sotuv, reja, ombor, ishlab chiqarish va moliya alohida fayl yoki chatlarda ishlaydi.",
        "Material yetishmovchiligi juda kech aniqlanadi.",
        "Ishlab chiqarish kechikishini oldindan ko'rish qiyin.",
        "Tayyor mahsulot, paket va bog'lamlarni kuzatish qiyin.",
        "Moliya xarajat, to'lov va foydani tushunish uchun qo'lda yangilanish kutadi.",
        "Qo'lda hisobot vaqtni oladi va xatolar yaratadi.",
      ],
    },
    promise: {
      heading: "Bitta buyurtma. Bitta oqim. Bitta haqiqat manbai.",
      text:
        "Har bir mijoz buyurtmasi sotuv tasdig'idan model ma'lumotlari, material reja, xarid, ishlab chiqarish, QR skanlar, ombor harakati, jo'natma, to'lov va foyda tahliligacha bog'langan qoladi.",
      cards: [
        {
          title: "Har bir buyurtmani nazorat qiling",
          text: "Sotuv, model, material ehtiyoji, ishlab chiqarish, jo'natma va to'lov bitta buyurtma yozuviga ulanadi.",
        },
        {
          title: "Muammolarni ertaroq ko'ring",
          text: "Yetishmovchilik, kechikkan ish, yo'q skanlar va yetkazish xavflari majburiy reaksiya bo'lishidan oldin ko'rinadi.",
        },
        {
          title: "Har bir bo'limni javobgar qiling",
          text: "Jamoalar aniq ish navbatlarini oladi, menejerlar esa nima o'zgargani, kim o'tkazgani va qachon bo'lganini ko'radi.",
        },
      ],
    },
    comparison: {
      heading: "Milana oldin va keyin",
      beforeTitle: "Milanadan oldin",
      afterTitle: "Milanadan keyin",
      before: [
        "Buyurtmalar qo'lda yuritiladi.",
        "Ombor kech tekshiriladi.",
        "Bo'limlar yangilanish kutadi.",
        "Moliya hammasini keyin hisoblaydi.",
        "Menejerlar statusni odamlardan so'raydi.",
        "Muammolar juda kech aniqlanadi.",
      ],
      after: [
        "Har bir buyurtmaning jonli lifecycle'i bor.",
        "Yetishmovchiliklar erta ko'rinadi.",
        "Bo'limlar aniq ish navbatlarini oladi.",
        "QR skanlar real harakatni ko'rsatadi.",
        "Moliya xarajat, tushum, to'lov va foydani ko'radi.",
        "Menejerlar xavflarni kechikishdan oldin ko'radi.",
      ],
    },
    lifecycle: {
      heading: "Fabrikaning butun jarayoni jonli bog‘langan",
      text:
        "Bitta buyurtma sotuvdan modelga, rejaga, materialga, ishlab chiqarishga, QR kuzatuvga, jo‘natmaga va moliyaga qanday o‘tishini ko‘ring - har bir bo‘lim bitta jonli ma’lumot bilan ishlaydi.",
      steps: [
        {
          title: "Savdo buyurtmasi",
          shortLabel: "Buyurtma qabul qilindi",
          detail:
            "Mijoz buyurtmasi, to‘lov holati, tasdiqlar, hisob-fakturalar va ishlab chiqarish konteksti birinchi kundan bog‘lanadi.",
          tags: ["Sotuv", "Moliya"],
        },
        {
          title: "Mahsulot modeli",
          shortLabel: "Model tasdiqlandi",
          detail:
            "Model rasmlari, o‘lchamlar, BOM, operatsiyalar, fayllar va tannarx qoidalari bitta tasdiqlangan manbada saqlanadi.",
          tags: ["Dizayn", "Tannarx"],
        },
        {
          title: "Rejalashtirish",
          shortLabel: "Reja yaratildi",
          detail:
            "Talab material ehtiyojlari, work order, muddatlar va ishlab chiqarish to‘xtashidan oldingi yetishmovchilik ogohlantirishlariga aylanadi.",
          tags: ["Reja", "Ishlab chiqarish"],
        },
        {
          title: "Xarid",
          shortLabel: "Material so‘raldi",
          detail: "Real yetishmovchilik, tasdiqlar va ishlab chiqarish talabiga asoslanib kerakli narsalar xarid qilinadi.",
          tags: ["Xarid", "Ombor"],
        },
        {
          title: "Ombor",
          shortLabel: "Ombor nazoratda",
          detail:
            "Qaysi material va aksessuar mavjud, rezerv qilingan, qabul qilingan, ko‘chirilgan, qaytarilgan yoki tugab borayotganini biling.",
          tags: ["Ombor", "Reja"],
        },
        {
          title: "Ishlab chiqarish sexi",
          shortLabel: "Ishlab chiqarish yurmoqda",
          detail:
            "Kesish, bosma, tikuv, qadoqlash va sifat jamoalariga aniq ish navbatlari hamda himoyalangan miqdor qoidalari beriladi.",
          tags: ["Kesish", "Tikuv", "QC"],
        },
        {
          title: "QR kuzatuv",
          shortLabel: "Har bir harakat skan qilinadi",
          detail:
            "Bog‘lamlar, paketlar, materiallar, skanlar, operatorlar va harakat tarixini tezda kuzating.",
          tags: ["Operatorlar", "Audit"],
        },
        {
          title: "Jo‘natma",
          shortLabel: "Jo‘natma tayyorlandi",
          detail:
            "Tayyor mahsulot, paket tayyorligi, skan tekshiruvi, jo‘natish, yetkazish holati va paket tarixini nazorat qiling.",
          tags: ["Logistika", "Ombor"],
        },
        {
          title: "Moliya",
          shortLabel: "Foyda ko‘rinadi",
          detail:
            "Tushum, to‘lovlar, xarajat tuzilmasi, buyurtma foydasi, ombor qiymati, chiqindi iqtisodi va moliya syncni real operatsion ma’lumotdan ko‘ring.",
          tags: ["Moliya", "Rahbariyat"],
        },
      ],
    },
    benefits: {
      heading: "Rahbarlar nimani qaytarib oladi",
      text:
        "Qiymat ekranlar sonida emas. Qiymat tezroq qaror, kamroq xato, kuchli javobgarlik va marjani himoya qilishda.",
      groups: [
        {
          title: "Har bir buyurtmaning haqiqatini biling",
          text: "Sotuv, reja, ishlab chiqarish, ombor, logistika va moliya bitta buyurtma yozuvidan ishlaydi.",
        },
        {
          title: "Muammolarni kech aniqlashni to'xtating",
          text: "Material yetishmovchiligi, kech ish, yo'q skanlar va ishlab chiqarish xavflari yetkazishga zarar berishidan oldin ko'rinadi.",
        },
        {
          title: "Fabrika harakatini jonli ma'lumotga aylantiring",
          text: "QR skanlar jismoniy topshirishni bog'lam, paket va jo'natma bo'yicha raqamli hodisaga aylantiradi.",
        },
        {
          title: "Buyurtmadan jo'natmagacha foydani himoya qiling",
          text: "BOM xarajatlari, operatsiyalar, chiqindi, ombor, hisob-faktura va to'lovlar real foydani tushunishga yordam beradi.",
        },
        {
          title: "Har bir bo'limga fokusli ish joyi bering",
          text: "Jamoa faqat kerakli vosita va vazifalarni ko'radi, rahbariyat esa to'liq ko'rinishni saqlaydi.",
        },
        {
          title: "Qo'lda hisobot o'rniga kundalik nazorat",
          text: "Dashboardlar faol ishlab chiqarish, kech buyurtmalar, output, nuqson, moliya, ombor va vazifalarni qo'lda hisobot kutmasdan ko'rsatadi.",
        },
      ],
    },
    departments: {
      heading: "Tikuv fabrikasi real ishlashiga mos qurilgan",
      text:
        "Har bir bo'lim o'z ish oynasiga ega, lekin buyurtma, material, skan, paket, to'lov va audit tarixi bog'langan qoladi.",
      panels: [
        {
          name: "Rahbariyat",
          scope: "Faol buyurtmalar, kechikkan ish, output, nuqson, pul, kuzatuv va audit tarixini bitta nazorat ko'rinishida ko'radi.",
          tools: ["Dashboard", "Process tracking", "Traceability", "Audit logs"],
        },
        {
          name: "Sotuv",
          scope: "Mijoz buyurtmalari, balanslar, hisob-fakturalar, to'lovlar va jo'natma follow-up ishlab chiqarish kontekstini yo'qotmasdan yuritiladi.",
          tools: ["Sales orders", "Customers", "Invoices", "Payments"],
        },
        {
          name: "Rejalashtirish",
          scope: "Production order yaratish, material ehtiyojini hisoblash, yetishmovchilikni aniqlash va muddatlarni muvofiqlashtirish.",
          tools: ["Planning", "Forecasting", "Work orders", "Shortages"],
        },
        {
          name: "Ombor",
          scope: "Kirim, partiya, ombor harakati, aksessuar berish/qaytarish va tayyor mahsulot zaxirasini nazorat qilish.",
          tools: ["Inventory", "Batches", "Warehouse stock", "Warehouse map"],
        },
        {
          name: "Sex",
          scope: "Kesish, bosma, tikuv va qadoqlash jamoalariga QR asosidagi harakat tarixi bilan aniq ish navbatlari beriladi.",
          tools: ["Cutting", "Printing", "Sewing", "Packaging"],
        },
        {
          name: "Logistika",
          scope: "Paketlarni tayyorlash, jo'natishdan oldin skan, tayyor mahsulotni yuborish, yetkazishni tasdiqlash va paket tarixini yuritish.",
          tools: ["Packages", "Shipments", "Finished goods", "Scan checks"],
        },
        {
          name: "Moliya",
          scope: "Tushum, hisob-faktura, to'lov, buyurtma foydasi, xarajat, brend ombor qiymati, chiqindi va 1C sync ulanadi.",
          tools: ["Finance dashboard", "Payments", "Profit", "1C sync"],
        },
        {
          name: "HR va ish haqi",
          scope: "Xodimlar, ish haqi xulosalari, process QR va operatsiya asosidagi to'lov inputlari ulanadi.",
          tools: ["Employees", "Payroll", "Process QR", "Paid operations"],
        },
      ],
    },
    management: {
      heading: "Fabrikani taxmin bilan emas, signal bilan boshqaring.",
      text:
        "Milana menejerlarga ishlab chiqarish, reja, moliya, ombor, chiqindi, nuqson va buyurtma progressi bo'yicha kundalik operatsion ko'rinishlar beradi.",
      signals: [
        "Kechikkan buyurtmalar",
        "Faol ishlab chiqarish",
        "Yetishmovchiliklar",
        "Bo'lim outputi",
        "Nuqson va sifat masalalari",
        "To'lovlar va balanslar",
        "Ombor qiymati",
        "Chiqindi xarajati yoki daromadi",
        "Vazifalar va bildirishnomalar",
      ],
    },
    difference: {
      heading: "Oddiy ofis buxgalteriyasi emas, tikuv ishlab chiqarishi uchun qurilgan.",
      points: [
        "Sotuvdan jo'natmagacha to'liq lifecycle.",
        "Tikuv modellari, BOM, o'lchamlar, ranglar, bog'lamlar, paketlar va ishlab chiqarish bo'limlari atrofida qurilgan.",
        "Real fabrika harakati uchun QR-first kuzatuv.",
        "Ishlab chiqarish, ombor, moliya, ish haqi va audit bog'langan.",
        "Bo'limga xos workflowlar.",
        "Qo'lda hisobotlarsiz rahbariyat ko'rinishi.",
      ],
    },
    impact: {
      heading: "Fabrika xaosidan fabrika nazoratiga.",
      outcomes: [
        "Qo'lda hisobotni kamaytirish",
        "Ishlab chiqarish chalkashligini kamaytirish",
        "Ombor xatolarini kamaytirish",
        "Yetishmovchilikni kech bilishni kamaytirish",
        "Yetkazishga ishonchni oshirish",
        "Javobgarlikni oshirish",
        "Moliyaviy ko'rinishni yaxshilash",
        "Mijoz ishonchini oshirish",
        "Excel, Telegram, WhatsApp va qo'lda status yangilashga bog'liqlikni kamaytirish",
      ],
    },
    trust: {
      heading: "Production-ready asosda qurilgan",
      text:
        "Texnik tafsilotlar asosiy savdo hikoyasidan keyin turishi kerak, lekin ishonch uchun muhim. Milana xavfsiz kirish, audit, integratsiya va deploy uchun tuzilgan.",
      highlights: [
        {
          title: "Xavfsiz role-based access",
          text: "Navigatsiya va backend authorization har bir bo'limni tasdiqlangan workflow ichida ushlaydi.",
        },
        {
          title: "Audit trail",
          text: "Operatsion o'zgarishlar audit tarixi orqali ko'rilib, exceptionlarni tezroq tekshirishga yordam beradi.",
        },
        {
          title: "Hujjatlangan operatsiyalar",
          text: "Architecture, security, disaster recovery, privacy retention va training docs qo'llab-quvvatlashga yordam beradi.",
        },
        {
          title: "Deployment-ready arxitektura",
          text: "Frontend, backend, database va storage aniq ajratilgan, deployment wiring mavjud.",
        },
        {
          title: "API va integratsiya asosi",
          text: "Tizim machine access, finance sync va kelajakdagi integratsiyalar uchun tayyor.",
        },
        {
          title: "QR va barcode storage",
          text: "Bog'lam va paket yorliqlari yaratiladi hamda saqlanadi, harakatni skan qilish va kuzatish mumkin.",
        },
      ],
      stackLabel: "Stack, qisqa",
      stack: "FastAPI, PostgreSQL, Next.js, TypeScript, Tailwind, Docker va Vercel deployment wiring.",
    },
    finalCta: {
      heading: "Har bir buyurtmani ko'proq nazorat bilan yuritishga tayyormisiz?",
      text:
        "Milana Ecosystem tikuv ishlab chiqaruvchilariga har bir buyurtma, material, bo'lim va jo'natmani bitta ulangan tizimdan boshqarishga yordam beradi.",
      primaryAction: "Jarayonni ko'rish",
      secondaryAction: "ERPni ochish",
    },
    footer: {
      line: "Milana Ecosystem. Tikuv ishlab chiqaruvchilari uchun fabrika nazorat tizimi.",
    },
  },
};

function attachIcons<T extends object>(items: T[], icons: LucideIcon[]) {
  return items.map((item, index) => ({
    ...item,
    Icon: icons[index % icons.length],
  }));
}

export function getPresentationContent(lang: Lang): PresentationContent {
  const selected = text[lang] || text.en;
  return {
    ...selected,
    hero: {
      ...selected.hero,
      valueCards: attachIcons(selected.hero.valueCards, valueIcons),
    },
    promise: {
      ...selected.promise,
      cards: attachIcons(selected.promise.cards, promiseIcons),
    },
    lifecycle: {
      ...selected.lifecycle,
      steps: attachIcons(selected.lifecycle.steps, lifecycleIcons),
    },
    benefits: {
      ...selected.benefits,
      groups: attachIcons(selected.benefits.groups, benefitIcons),
    },
    trust: {
      ...selected.trust,
      highlights: attachIcons(selected.trust.highlights, trustIcons),
    },
  };
}
