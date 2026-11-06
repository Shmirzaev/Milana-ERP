"use client";
import PageHeader from "@/components/PageHeader";
import PackagePrintRuns from "@/components/PackagePrintRuns";
import { useT } from "@/lib/i18n";

export default function PhysicalPrintRunsPage() {
  const { t } = useT();
  return <div>
    <PageHeader title={t("nav.physicalPrintRuns")} subtitle={t("page.physicalPrintRuns.subtitle")} />
    <PackagePrintRuns standalone />
  </div>;
}
