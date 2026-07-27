import type { Metadata } from "next";
import { storageFullImageUrl } from "@/lib/modelImages";
import ImagePreviewClient from "./ImagePreviewClient";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Image preview",
};

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

function firstParam(value: string | string[] | undefined): string {
  return Array.isArray(value) ? value[0] || "" : value || "";
}

function safeImageSrc(value: string): string {
  const src = storageFullImageUrl(value).trim();
  if (!src) return "";
  if (src.startsWith("/storage/")) return src;
  try {
    const parsed = new URL(src);
    if (parsed.protocol === "http:" || parsed.protocol === "https:") return parsed.toString();
  } catch {}
  return "";
}

export default async function ImagePreviewPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const title = firstParam(params.title) || "Image preview";
  const src = safeImageSrc(firstParam(params.src));

  return <ImagePreviewClient title={title} src={src} />;
}
