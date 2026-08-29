export type ModelImageLike = {
  file_url?: string | null;
  file_name?: string | null;
  content_type?: string | null;
};

const PREVIEW_IMAGE_RE = /\.(png|jpe?g|webp|gif)(?:[?#].*)?$/i;

export function isPreviewImageUrl(value?: string | null): boolean {
  const url = String(value || "").trim();
  return Boolean(url && (url.startsWith("/storage/model-files/") || PREVIEW_IMAGE_RE.test(url)));
}

export function isPreviewModelImage(image?: ModelImageLike | null): boolean {
  if (!image) return false;
  const contentType = String(image.content_type || "").toLowerCase();
  const name = String(image.file_name || image.file_url || "").toLowerCase();
  return contentType.startsWith("image/") || isPreviewImageUrl(name);
}

export function storageThumbnailUrl(value?: string | null, size = 320): string {
  const url = String(value || "").trim();
  if (!url) return "";
  if (url.startsWith("/storage/model-files/thumb/")) return url;
  const match = url.match(/^\/storage\/model-files\/([^/?#]+)(?:[?#].*)?$/);
  if (!match) return url;
  return `/storage/model-files/thumb/${match[1]}?size=${Math.max(96, Math.min(size, 1280))}&quality=hq2`;
}

export function storageFullImageUrl(value?: string | null): string {
  const url = String(value || "").trim();
  if (!url) return "";
  const thumbMatch = url.match(/^\/storage\/model-files\/thumb\/([^/?#]+)(?:[?#].*)?$/);
  if (thumbMatch) return `/storage/model-files/${thumbMatch[1]}`;
  return url;
}

export function imagePreviewHref(value?: string | null, title?: string | null): string {
  const src = storageFullImageUrl(value);
  const params = new URLSearchParams();
  if (src) params.set("src", src);
  const label = String(title || "").trim();
  if (label) params.set("title", label);
  return `/image-preview?${params.toString()}`;
}
