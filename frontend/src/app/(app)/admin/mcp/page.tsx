"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";
import { Ban, CheckCircle2, Clipboard, KeyRound, RefreshCw, ShieldCheck, Terminal } from "lucide-react";
import PageHeader from "@/components/PageHeader";
import { fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";

type McpTool = {
  name: string;
  description: string;
};

type McpInfo = {
  server_name: string;
  display_name: string;
  erp_api_base_url: string;
  transport: string;
  python_module: string;
  package_name: string;
  section_access: string;
  runtime_access: string;
  env: Record<string, string>;
  claude_desktop_config: Record<string, unknown>;
  read_tools: McpTool[];
  write_tools: McpTool[];
  blocked_actions: string[];
  security_notes: string[];
};

function JsonBlock({
  title,
  value,
  onCopy,
  copied,
}: {
  title: string;
  value: string;
  onCopy: () => void;
  copied: boolean;
}) {
  const { t } = useT();
  return (
    <section className="card">
      <div className="flex items-center justify-between gap-3 border-b border-[#e3dfd3] px-4 py-3">
        <h2 className="app-card-title">{title}</h2>
        <button type="button" className="btn h-8 px-2" onClick={onCopy}>
          <Clipboard />
          {copied ? t("page.mcp.copied") : t("page.mcp.copy")}
        </button>
      </div>
      <pre className="max-h-[360px] overflow-auto bg-[#14110b] p-4 text-xs leading-5 text-[#fdfcf8]">
        {value}
      </pre>
    </section>
  );
}

function ToolTable({ title, tools }: { title: string; tools: McpTool[] }) {
  const { t } = useT();
  return (
    <section className="card">
      <div className="border-b border-[#e3dfd3] px-4 py-3">
        <h2 className="app-card-title">{title}</h2>
      </div>
      <div className="overflow-x-auto">
        <table className="table">
          <thead>
            <tr>
              <th>{t("page.mcp.tool")}</th>
              <th>{t("field.description")}</th>
            </tr>
          </thead>
          <tbody>
            {tools.map((tool) => (
              <tr key={tool.name}>
                <td className="mono text-xs">{tool.name}</td>
                <td>{tool.description}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default function AdminMcpPage() {
  const { t } = useT();
  const { data, error, isLoading, mutate } = useSWR<McpInfo>("/api/admin/mcp-info", fetcher);
  const [copied, setCopied] = useState("");
  const claudeConfig = useMemo(() => JSON.stringify(data?.claude_desktop_config ?? {}, null, 2), [data]);
  const envConfig = useMemo(() => JSON.stringify(data?.env ?? {}, null, 2), [data]);

  async function copy(label: string, value: string) {
    await navigator.clipboard.writeText(value);
    setCopied(label);
    window.setTimeout(() => setCopied((current) => (current === label ? "" : current)), 1800);
  }

  return (
    <div>
      <PageHeader
        title={t("page.mcp.title")}
        subtitle={t("page.mcp.subtitle")}
        actions={
          <button type="button" className="btn" onClick={() => mutate()}>
            <RefreshCw />
            {t("page.mcp.refresh")}
          </button>
        }
      />

      {isLoading ? <div className="panel p-4 text-sm text-[#56503f]">{t("page.mcp.loading")}</div> : null}
      {error ? <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">{String(error.message || error)}</div> : null}

      {data ? (
        <div className="space-y-4">
          <section className="card p-4">
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(280px,360px)]">
              <div className="min-w-0">
                <div className="mb-3 flex items-center gap-2">
                  <Terminal className="h-5 w-5 text-[#56503f]" />
                  <h2 className="app-card-title text-base">{data.display_name}</h2>
                </div>
                <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <div>
                    <dt className="label">{t("page.mcp.server")}</dt>
                    <dd className="mono break-all text-sm text-[#2c2920]">{data.server_name}</dd>
                  </div>
                  <div>
                    <dt className="label">{t("page.mcp.transport")}</dt>
                    <dd className="mono text-sm text-[#2c2920]">{data.transport}</dd>
                  </div>
                  <div>
                    <dt className="label">{t("page.mcp.erpApi")}</dt>
                    <dd className="mono break-all text-sm text-[#2c2920]">{data.erp_api_base_url}</dd>
                  </div>
                  <div>
                    <dt className="label">{t("page.mcp.pythonModule")}</dt>
                    <dd className="mono break-all text-sm text-[#2c2920]">{data.python_module}</dd>
                  </div>
                </dl>
              </div>
              <div className="rounded-md border border-[#e3dfd3] bg-[#f8f6ef] p-3">
                <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-[#2c2920]">
                  <ShieldCheck className="h-4 w-4" />
                  {t("page.mcp.access")}
                </div>
                <p className="text-sm text-[#56503f]">{data.section_access}</p>
                <p className="mt-2 text-sm text-[#56503f]">{data.runtime_access}</p>
              </div>
            </div>
          </section>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <JsonBlock
              title={t("page.mcp.claudeConfig")}
              value={claudeConfig}
              onCopy={() => copy("claude", claudeConfig)}
              copied={copied === "claude"}
            />
            <JsonBlock
              title={t("page.mcp.environment")}
              value={envConfig}
              onCopy={() => copy("env", envConfig)}
              copied={copied === "env"}
            />
          </div>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <ToolTable title={t("page.mcp.readTools")} tools={data.read_tools} />
            <ToolTable title={t("page.mcp.writeTools")} tools={data.write_tools} />
          </div>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <section className="card">
              <div className="border-b border-[#e3dfd3] px-4 py-3">
                <h2 className="app-card-title">{t("page.mcp.securityNotes")}</h2>
              </div>
              <ul className="divide-y divide-[#ecebe3]">
                {data.security_notes.map((note) => (
                  <li key={note} className="flex gap-3 px-4 py-3 text-sm text-[#2c2920]">
                    <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-[#1f7a4d]" />
                    <span>{note}</span>
                  </li>
                ))}
              </ul>
            </section>

            <section className="card">
              <div className="border-b border-[#e3dfd3] px-4 py-3">
                <h2 className="app-card-title">{t("page.mcp.blockedActions")}</h2>
              </div>
              <ul className="divide-y divide-[#ecebe3]">
                {data.blocked_actions.map((action) => (
                  <li key={action} className="flex gap-3 px-4 py-3 text-sm text-[#2c2920]">
                    <Ban className="mt-0.5 h-4 w-4 shrink-0 text-[#9a3308]" />
                    <span>{action}</span>
                  </li>
                ))}
              </ul>
            </section>
          </div>

          <section className="rounded-md border border-[#ded9ca] bg-[#f8f6ef] p-4 text-sm text-[#56503f]">
            <div className="mb-2 flex items-center gap-2 font-semibold text-[#2c2920]">
              <KeyRound className="h-4 w-4" />
              {t("page.mcp.tokenHandling")}
            </div>
            {t("page.mcp.tokenHint")}
          </section>
        </div>
      ) : null}
    </div>
  );
}
