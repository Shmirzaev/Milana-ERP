"use client";

import { useState, type CSSProperties } from "react";
import type { PresentationContent } from "@/components/presentation/presentationData";

const stationPositions = [
  { row: 1, column: 1 },
  { row: 1, column: 2 },
  { row: 1, column: 3 },
  { row: 2, column: 3 },
  { row: 2, column: 2 },
  { row: 2, column: 1 },
  { row: 3, column: 1 },
  { row: 3, column: 2 },
  { row: 3, column: 3 },
] as const;

export default function LiveFactoryProcess({ content }: { content: PresentationContent }) {
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const activeStep = activeIndex === null ? null : content.lifecycle.steps[activeIndex];

  return (
    <section id="flow" className="border-b border-[var(--erp-border)] bg-[var(--erp-bg)] py-16 sm:py-20">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="presentation-section-heading">
          <h2>{content.lifecycle.heading}</h2>
          <p>{content.lifecycle.text}</p>
        </div>

        <div className="live-process-shell presentation-reveal mt-10">
          <div className="live-process-map" aria-label={content.lifecycle.heading}>
            <svg
              className="live-process-svg"
              viewBox="0 0 100 100"
              preserveAspectRatio="none"
              aria-hidden="true"
              focusable="false"
            >
              <path className="live-process-path-base" d="M10 15 H50 H90 V50 H50 H10 V85 H50 H90" />
              <path className="live-process-path-flow" d="M10 15 H50 H90 V50 H50 H10 V85 H50 H90" />
              <g className="live-process-package">
                <rect x="-2.7" y="-2.7" width="5.4" height="5.4" rx="0.9" />
                <path d="M-2.7 -0.5 H2.7" />
                <path d="M0 -2.7 V2.7" />
                <animateMotion
                  dur="13s"
                  repeatCount="indefinite"
                  path="M10 15 H50 H90 V50 H50 H10 V85 H50 H90"
                />
              </g>
            </svg>

            {content.lifecycle.steps.map((step, index) => {
              const StepIcon = step.Icon;
              const position = stationPositions[index] || stationPositions[0];
              const isActive = activeIndex === index;
              const style = {
                gridColumn: position.column,
                gridRow: position.row,
                "--station-delay": `${index * 70}ms`,
              } as CSSProperties;

              return (
                <button
                  key={step.title}
                  type="button"
                  className="live-process-station"
                  data-active={isActive}
                  data-scan={index === 6}
                  style={style}
                  onMouseEnter={() => setActiveIndex(index)}
                  onFocus={() => setActiveIndex(index)}
                  onClick={() => setActiveIndex(index)}
                  aria-pressed={isActive}
                  aria-label={`${String(index + 1).padStart(2, "0")} ${step.title}: ${step.shortLabel}`}
                >
                  <span className="live-process-number">{String(index + 1).padStart(2, "0")}</span>
                  <span className="live-process-icon-wrap" aria-hidden="true">
                    <span className="live-process-icon-plate">
                      <StepIcon className="h-5 w-5" />
                    </span>
                  </span>
                  <span className="live-process-title">{step.title}</span>
                  <span className="live-process-short">{step.shortLabel}</span>

                  {isActive ? (
                    <span className="live-process-station-detail">
                      <span>{step.detail}</span>
                      <span className="live-process-station-tags">
                        {step.tags.map((tag) => (
                          <span key={tag}>{tag}</span>
                        ))}
                      </span>
                    </span>
                  ) : null}
                </button>
              );
            })}
          </div>

          <aside className="live-process-detail" aria-live="polite">
            {activeStep ? (
              <div key={activeStep.title} className="live-process-detail-card">
                <div className="live-process-detail-meta">
                  <span>{String(activeIndex! + 1).padStart(2, "0")}</span>
                  <span>{activeStep.shortLabel}</span>
                </div>
                <h3>{activeStep.title}</h3>
                <p>{activeStep.detail}</p>
                <div className="live-process-detail-tags">
                  {activeStep.tags.map((tag) => (
                    <span key={tag}>{tag}</span>
                  ))}
                </div>
              </div>
            ) : (
              <div className="live-process-idle" aria-hidden="true">
                {content.lifecycle.steps.map((step, index) => (
                  <span key={step.title}>
                    <b>{String(index + 1).padStart(2, "0")}</b>
                    {step.shortLabel}
                  </span>
                ))}
              </div>
            )}
          </aside>
        </div>
      </div>
    </section>
  );
}
