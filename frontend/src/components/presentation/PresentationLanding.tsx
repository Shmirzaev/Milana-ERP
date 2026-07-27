"use client";

import { useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  CheckCircle2,
  ExternalLink,
  Languages,
  Menu,
  Moon,
  Sun,
  X,
} from "lucide-react";
import BrandLogo from "@/components/BrandLogo";
import FeatureFlowScene from "@/components/presentation/FeatureFlowScene";
import LiveFactoryProcess from "@/components/presentation/LiveFactoryProcess";
import { getPresentationContent, type PresentationContent } from "@/components/presentation/presentationData";
import { useT } from "@/lib/i18n";
import type { Lang } from "@/lib/i18n/types";
import { useTheme } from "@/lib/theme";

const languageOptions: Array<{ value: Lang; label: string; title: string }> = [
  { value: "en", label: "EN", title: "English" },
  { value: "ru", label: "RU", title: "Russian" },
  { value: "uz", label: "UZ", title: "O'zbek" },
];

export default function PresentationLanding() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const { lang, setLang } = useT();
  const { theme, setTheme } = useTheme();
  const content = getPresentationContent(lang);

  return (
    <div className="presentation-page min-h-screen bg-[var(--erp-bg)] text-[var(--erp-text)]">
      <header className="sticky top-0 z-50 border-b border-[var(--erp-border)] bg-[var(--erp-surface)] backdrop-blur-md">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
          <Link href="/presentation" className="flex min-w-0 items-center" aria-label="Milana Ecosystem">
            <span className="presentation-logo-lockup">
              <BrandLogo alt="Milana Ecosystem" className="h-10 w-auto max-w-[180px]" />
            </span>
          </Link>

          <nav className="hidden items-center gap-7 text-sm text-[var(--erp-text-soft)] lg:flex" aria-label={content.controls.menu}>
            {content.nav.map((item) => (
              <a key={item.href} href={item.href} className="transition hover:text-[var(--erp-text)]">
                {item.label}
              </a>
            ))}
          </nav>

          <div className="hidden items-center gap-2 lg:flex">
            <LanguageControl content={content} lang={lang} setLang={setLang} />
            <ThemeControl content={content} theme={theme} setTheme={setTheme} />
            <Link href="/login" className="presentation-button presentation-button-secondary">
              {content.controls.login}
            </Link>
            <a href="#flow" className="presentation-button presentation-button-primary">
              {content.controls.explore}
              <ArrowRight className="h-4 w-4" />
            </a>
          </div>

          <button
            type="button"
            className="grid h-9 w-9 place-items-center rounded-md border border-[var(--erp-border-strong)] bg-[var(--erp-surface)] text-[var(--erp-text-soft)] lg:hidden"
            onClick={() => setMobileOpen(true)}
            aria-label={content.controls.menu}
            aria-expanded={mobileOpen}
          >
            <Menu className="h-5 w-5" />
          </button>
        </div>

        {mobileOpen ? (
          <div className="border-t border-[var(--erp-border-soft)] bg-[var(--erp-surface)] px-4 py-4 lg:hidden">
            <div className="mb-4 flex items-center justify-between">
              <span className="text-sm font-semibold">Milana Ecosystem</span>
              <button
                type="button"
                className="grid h-8 w-8 place-items-center rounded-md text-[var(--erp-text-soft)] hover:bg-[var(--erp-surface-muted)]"
                onClick={() => setMobileOpen(false)}
                aria-label={content.controls.closeMenu}
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="mb-4 grid gap-3">
              <LanguageControl content={content} lang={lang} setLang={setLang} mobile />
              <ThemeControl content={content} theme={theme} setTheme={setTheme} mobile />
            </div>

            <nav className="grid gap-2 text-sm">
              {content.nav.map((item) => (
                <a
                  key={item.href}
                  href={item.href}
                  className="rounded-md px-2 py-2 text-[var(--erp-text-soft)] hover:bg-[var(--erp-surface-muted)] hover:text-[var(--erp-text)]"
                  onClick={() => setMobileOpen(false)}
                >
                  {item.label}
                </a>
              ))}
              <Link href="/login" className="presentation-button presentation-button-secondary mt-2 w-full">
                {content.controls.login}
                <ExternalLink className="h-4 w-4" />
              </Link>
              <a
                href="#flow"
                className="presentation-button presentation-button-primary w-full"
                onClick={() => setMobileOpen(false)}
              >
                {content.controls.explore}
                <ArrowRight className="h-4 w-4" />
              </a>
            </nav>
          </div>
        ) : null}
      </header>

      <main>
        <HeroSection content={content} theme={theme} />
        <ProblemSection content={content} />
        <PromiseSection content={content} />
        <ComparisonSection content={content} />
        <LifecycleSection content={content} />
        <BenefitsSection content={content} />
        <DepartmentSection content={content} />
        <ManagementSection content={content} />
        <DifferenceImpactSection content={content} />
        <TrustSection content={content} />
        <FinalCtaSection content={content} />
      </main>

      <footer className="border-t border-[var(--erp-border)] bg-[var(--erp-surface)]">
        <div className="mx-auto flex max-w-7xl flex-col gap-4 px-4 py-8 text-sm text-[var(--erp-text-soft)] sm:px-6 md:flex-row md:items-center md:justify-between lg:px-8">
          <div>{content.footer.line}</div>
          <div className="flex flex-wrap items-center gap-4">
            <Link href="/login" className="hover:text-[var(--erp-text)]">
              {content.controls.login}
            </Link>
            {content.nav.slice(0, 3).map((item) => (
              <a key={item.href} href={item.href} className="hover:text-[var(--erp-text)]">
                {item.label}
              </a>
            ))}
          </div>
        </div>
      </footer>
    </div>
  );
}

function LanguageControl({
  content,
  lang,
  setLang,
  mobile = false,
}: {
  content: PresentationContent;
  lang: Lang;
  setLang: (lang: Lang) => void;
  mobile?: boolean;
}) {
  return (
    <div className={mobile ? "presentation-control w-full" : "presentation-control"} aria-label={content.controls.language}>
      <Languages className="h-4 w-4" aria-hidden="true" />
      <div className="presentation-segment" role="group" aria-label={content.controls.language}>
        {languageOptions.map((option) => (
          <button
            key={option.value}
            type="button"
            className="presentation-segment-button"
            data-active={lang === option.value}
            onClick={() => setLang(option.value)}
            aria-pressed={lang === option.value}
            title={option.title}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function ThemeControl({
  content,
  theme,
  setTheme,
  mobile = false,
}: {
  content: PresentationContent;
  theme: "day" | "night";
  setTheme: (theme: "day" | "night") => void;
  mobile?: boolean;
}) {
  return (
    <div className={mobile ? "presentation-control w-full" : "presentation-control"} aria-label={content.controls.theme}>
      <div className="presentation-segment presentation-segment-wide" role="group" aria-label={content.controls.theme}>
        <button
          type="button"
          className="presentation-segment-button"
          data-active={theme === "day"}
          onClick={() => setTheme("day")}
          aria-pressed={theme === "day"}
          title={content.controls.light}
        >
          <Sun className="h-4 w-4" />
          <span className="hidden sm:inline">{content.controls.light}</span>
        </button>
        <button
          type="button"
          className="presentation-segment-button"
          data-active={theme === "night"}
          onClick={() => setTheme("night")}
          aria-pressed={theme === "night"}
          title={content.controls.dark}
        >
          <Moon className="h-4 w-4" />
          <span className="hidden sm:inline">{content.controls.dark}</span>
        </button>
      </div>
    </div>
  );
}

function SectionHeading({
  heading,
  text,
  inverted = false,
}: {
  heading: string;
  text?: string;
  inverted?: boolean;
}) {
  return (
    <div className={inverted ? "presentation-section-heading presentation-section-heading-dark" : "presentation-section-heading"}>
      <h2>{heading}</h2>
      {text ? <p>{text}</p> : null}
    </div>
  );
}

function HeroSection({ content, theme }: { content: PresentationContent; theme: "day" | "night" }) {
  return (
    <section className="relative overflow-hidden border-b border-[var(--erp-border)] bg-[var(--erp-bg)]">
      <div className="absolute inset-0">
        <FeatureFlowScene key={theme} />
        <div className="presentation-weave absolute inset-0" aria-hidden="true" />
      </div>

      <div className="relative mx-auto flex min-h-[calc(100vh-4rem)] max-w-7xl flex-col px-4 pb-10 pt-10 sm:px-6 sm:pt-14 lg:px-8 lg:pt-16">
        <div className="presentation-reveal min-w-0 max-w-5xl">
          <span className="presentation-logo-lockup mb-8">
            <BrandLogo alt="Milana Ecosystem" className="h-14 w-auto max-w-[240px]" />
          </span>
          <h1 className="max-w-5xl break-words text-4xl font-bold leading-[1.04] sm:text-5xl lg:text-6xl">
            {content.hero.title}
          </h1>
          <p className="mt-6 max-w-3xl text-lg leading-8 text-[var(--erp-text-strong)] sm:text-xl">
            {content.hero.subtitle}
          </p>
          <p className="mt-4 max-w-3xl text-base leading-7 text-[var(--erp-text-soft)]">
            {content.hero.support}
          </p>

          <div className="mt-8 flex flex-col gap-3 sm:flex-row">
            <a href="#flow" className="presentation-button presentation-button-primary h-11 px-5">
              {content.hero.primaryAction}
              <ArrowRight className="h-4 w-4" />
            </a>
            <Link href="/login" className="presentation-button presentation-button-secondary h-11 px-5">
              {content.hero.secondaryAction}
              <ExternalLink className="h-4 w-4" />
            </Link>
          </div>
        </div>

        <div className="presentation-reveal mt-auto pt-12" style={{ animationDelay: "120ms" }}>
          <div>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {content.hero.valueCards.map((card, index) => {
                const CardIcon = card.Icon;
                return (
                  <article key={card.title} className="rounded-md border border-[var(--erp-border)] bg-[var(--erp-surface)] p-4 shadow-sm">
                    <div className="flex items-start gap-3">
                      <div className="grid h-10 w-10 shrink-0 place-items-center rounded-md border border-[var(--erp-border-strong)] bg-[var(--erp-surface-raised)] text-[var(--erp-accent)]">
                        <CardIcon className="h-5 w-5" />
                      </div>
                      <div>
                        <h2 className="text-base font-semibold">{card.title}</h2>
                        <p className="mt-1 text-sm leading-6 text-[var(--erp-text-soft)]">{card.text}</p>
                      </div>
                    </div>
                    <div className="mt-3 h-px bg-[var(--erp-border-soft)]" />
                    <div className="mt-2 font-mono text-xs text-[var(--erp-text-muted)]">
                      {String(index + 1).padStart(2, "0")}
                    </div>
                  </article>
                );
              })}
            </div>
            <div className="presentation-signal mt-4">
              <div className="grid gap-2 text-sm text-[var(--erp-text-soft)]">
                {content.hero.trust.map((item) => (
                  <div key={item} className="flex items-center gap-2">
                    <CheckCircle2 className="h-4 w-4 text-[var(--erp-success)]" />
                    <span>{item}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function ProblemSection({ content }: { content: PresentationContent }) {
  return (
    <section id="problem" className="border-b border-[var(--erp-border)] bg-[var(--erp-surface)] py-16 sm:py-20">
      <div className="mx-auto grid max-w-7xl gap-10 px-4 sm:px-6 lg:grid-cols-[0.85fr_1.15fr] lg:px-8">
        <SectionHeading heading={content.problem.heading} text={content.problem.text} />
        <div className="grid gap-3 sm:grid-cols-2">
          {content.problem.pains.map((pain, index) => (
            <div
              key={pain}
              className="presentation-reveal border border-[var(--erp-border)] bg-[var(--erp-surface-raised)] p-4 text-sm leading-6 text-[var(--erp-text-soft)]"
              style={{ animationDelay: `${index * 40}ms` }}
            >
              <div className="mb-3 font-mono text-xs text-[var(--erp-accent)]">{String(index + 1).padStart(2, "0")}</div>
              {pain}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function PromiseSection({ content }: { content: PresentationContent }) {
  return (
    <section className="border-b border-[var(--erp-border)] bg-[var(--erp-bg)] py-16 sm:py-20">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <SectionHeading heading={content.promise.heading} text={content.promise.text} />
        <div className="mt-10 grid gap-4 md:grid-cols-3">
          {content.promise.cards.map((card, index) => {
            const CardIcon = card.Icon;
            return (
              <article
                key={card.title}
                className="presentation-feature-card presentation-reveal"
                style={{ animationDelay: `${index * 70}ms` }}
              >
                <div className="grid h-12 w-12 place-items-center rounded-md border border-[var(--erp-border-strong)] bg-[var(--erp-accent-soft)] text-[var(--erp-accent)]">
                  <CardIcon className="h-5 w-5" />
                </div>
                <h3 className="mt-5 text-lg font-semibold">{card.title}</h3>
                <p className="mt-3 text-sm leading-6 text-[var(--erp-text-soft)]">{card.text}</p>
              </article>
            );
          })}
        </div>
      </div>
    </section>
  );
}

function ComparisonSection({ content }: { content: PresentationContent }) {
  return (
    <section className="border-b border-[var(--erp-border)] bg-[var(--erp-surface)] py-16 sm:py-20">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <SectionHeading heading={content.comparison.heading} />
        <div className="mt-10 grid gap-4 lg:grid-cols-2">
          <ComparisonList title={content.comparison.beforeTitle} items={content.comparison.before} tone="muted" />
          <ComparisonList title={content.comparison.afterTitle} items={content.comparison.after} tone="strong" />
        </div>
      </div>
    </section>
  );
}

function ComparisonList({ title, items, tone }: { title: string; items: string[]; tone: "muted" | "strong" }) {
  return (
    <article className="border border-[var(--erp-border)] bg-[var(--erp-surface-raised)] p-5">
      <h3 className="text-xl font-semibold">{title}</h3>
      <ul className="mt-5 grid gap-3">
        {items.map((item) => (
          <li key={item} className="flex gap-3 text-sm leading-6 text-[var(--erp-text-soft)]">
            <span
              className={`mt-2 h-2 w-2 shrink-0 rounded-full ${
                tone === "strong" ? "bg-[var(--erp-success)]" : "bg-[var(--erp-text-muted)]"
              }`}
            />
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </article>
  );
}

function LifecycleSection({ content }: { content: PresentationContent }) {
  return <LiveFactoryProcess content={content} />;
}

function BenefitsSection({ content }: { content: PresentationContent }) {
  return (
    <section id="benefits" className="border-b border-[var(--erp-border)] bg-[var(--erp-surface)] py-16 sm:py-20">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <SectionHeading heading={content.benefits.heading} text={content.benefits.text} />
        <div className="mt-10 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {content.benefits.groups.map((benefit, index) => {
            const BenefitIcon = benefit.Icon;
            return (
              <article
                key={benefit.title}
                className="presentation-feature-card presentation-reveal"
                style={{ animationDelay: `${(index % 6) * 55}ms` }}
              >
                <div className="grid h-12 w-12 place-items-center rounded-md border border-[var(--erp-border-strong)] bg-[var(--erp-accent-soft)] text-[var(--erp-accent)]">
                  <BenefitIcon className="h-5 w-5" />
                </div>
                <h3 className="mt-5 text-lg font-semibold">{benefit.title}</h3>
                <p className="mt-3 text-sm leading-6 text-[var(--erp-text-soft)]">{benefit.text}</p>
              </article>
            );
          })}
        </div>
      </div>
    </section>
  );
}

function DepartmentSection({ content }: { content: PresentationContent }) {
  return (
    <section id="departments" className="presentation-inverted border-b py-16 sm:py-20">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <SectionHeading heading={content.departments.heading} text={content.departments.text} inverted />

        <div className="presentation-inverted-list mt-10 divide-y border-y">
          {content.departments.panels.map((panel, index) => (
            <article
              key={panel.name}
              className="presentation-department-row presentation-reveal grid gap-4 py-6 lg:grid-cols-[220px_1fr_420px] lg:items-center"
              style={{ animationDelay: `${index * 40}ms` }}
            >
              <h3 className="text-xl font-semibold text-white">{panel.name}</h3>
              <p className="max-w-3xl text-sm leading-6 text-[#e8dfcf]">{panel.scope}</p>
              <div className="flex flex-wrap gap-2">
                {panel.tools.map((tool) => (
                  <span key={tool} className="presentation-chip">
                    {tool}
                  </span>
                ))}
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

function ManagementSection({ content }: { content: PresentationContent }) {
  return (
    <section className="border-b border-[var(--erp-border)] bg-[var(--erp-bg)] py-16 sm:py-20">
      <div className="mx-auto grid max-w-7xl gap-10 px-4 sm:px-6 lg:grid-cols-[0.9fr_1.1fr] lg:px-8">
        <SectionHeading heading={content.management.heading} text={content.management.text} />
        <div className="grid gap-3 sm:grid-cols-3">
          {content.management.signals.map((signal, index) => (
            <div
              key={signal}
              className="presentation-reveal border border-[var(--erp-border)] bg-[var(--erp-surface)] p-4 text-sm font-semibold text-[var(--erp-text-strong)]"
              style={{ animationDelay: `${index * 35}ms` }}
            >
              <div className="mb-4 h-1 w-10 rounded-full bg-[var(--erp-accent)]" />
              {signal}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function DifferenceImpactSection({ content }: { content: PresentationContent }) {
  return (
    <section className="border-b border-[var(--erp-border)] bg-[var(--erp-surface)] py-16 sm:py-20">
      <div className="mx-auto grid max-w-7xl gap-10 px-4 sm:px-6 lg:grid-cols-2 lg:px-8">
        <article className="presentation-feature-card">
          <h2 className="text-3xl font-bold leading-tight">{content.difference.heading}</h2>
          <ul className="mt-8 grid gap-3">
            {content.difference.points.map((point) => (
              <li key={point} className="flex gap-3 text-sm leading-6 text-[var(--erp-text-soft)]">
                <CheckCircle2 className="mt-1 h-4 w-4 shrink-0 text-[var(--erp-success)]" />
                <span>{point}</span>
              </li>
            ))}
          </ul>
        </article>

        <article className="presentation-feature-card">
          <h2 className="text-3xl font-bold leading-tight">{content.impact.heading}</h2>
          <div className="mt-8 flex flex-wrap gap-2">
            {content.impact.outcomes.map((outcome) => (
              <span
                key={outcome}
                className="rounded-md border border-[var(--erp-border)] bg-[var(--erp-surface-muted)] px-3 py-2 text-sm text-[var(--erp-text-strong)]"
              >
                {outcome}
              </span>
            ))}
          </div>
        </article>
      </div>
    </section>
  );
}

function TrustSection({ content }: { content: PresentationContent }) {
  return (
    <section id="trust" className="border-b border-[var(--erp-border)] bg-[var(--erp-bg)] py-16 sm:py-20">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <SectionHeading heading={content.trust.heading} text={content.trust.text} />

        <div className="mt-10 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {content.trust.highlights.map((item, index) => {
            const ItemIcon = item.Icon;
            return (
              <article
                key={item.title}
                className="presentation-platform-card presentation-reveal"
                style={{ animationDelay: `${index * 55}ms` }}
              >
                <ItemIcon className="h-5 w-5 text-[var(--erp-accent)]" />
                <h3 className="mt-4 text-base font-semibold">{item.title}</h3>
                <p className="mt-3 text-sm leading-6 text-[var(--erp-text-soft)]">{item.text}</p>
              </article>
            );
          })}
        </div>

        <div className="mt-6 border border-[var(--erp-border)] bg-[var(--erp-surface)] p-5">
          <h3 className="text-base font-semibold">{content.trust.stackLabel}</h3>
          <p className="mt-2 text-sm leading-6 text-[var(--erp-text-soft)]">{content.trust.stack}</p>
        </div>
      </div>
    </section>
  );
}

function FinalCtaSection({ content }: { content: PresentationContent }) {
  return (
    <section className="presentation-inverted border-b py-16 sm:py-20">
      <div className="mx-auto max-w-7xl px-4 text-center sm:px-6 lg:px-8">
        <h2 className="mx-auto max-w-4xl text-4xl font-bold leading-tight text-white sm:text-5xl">
          {content.finalCta.heading}
        </h2>
        <p className="mx-auto mt-5 max-w-3xl text-base leading-7 text-[#e8dfcf] sm:text-lg">
          {content.finalCta.text}
        </p>
        <div className="mt-8 flex flex-col justify-center gap-3 sm:flex-row">
          <a href="#flow" className="presentation-button presentation-button-primary h-11 px-5">
            {content.finalCta.primaryAction}
            <ArrowRight className="h-4 w-4" />
          </a>
          <Link href="/login" className="presentation-button h-11 border-[#5a4b37] bg-[#201b15] px-5 text-[#fdfcf8] hover:bg-[#2b241d]">
            {content.finalCta.secondaryAction}
            <ExternalLink className="h-4 w-4" />
          </Link>
        </div>
      </div>
    </section>
  );
}
