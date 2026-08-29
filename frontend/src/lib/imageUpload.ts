const MODEL_IMAGE_MAX_LONG_EDGE = 1920;
const MODEL_IMAGE_OPTIMIZE_FROM_BYTES = 4 * 1024 * 1024;

type DecodedImage = {
  source: CanvasImageSource;
  width: number;
  height: number;
  close: () => void;
};

async function decodeImage(file: File): Promise<DecodedImage> {
  if (typeof window.createImageBitmap === "function") {
    const bitmap = await window.createImageBitmap(file, { imageOrientation: "from-image" });
    return {
      source: bitmap,
      width: bitmap.width,
      height: bitmap.height,
      close: () => bitmap.close(),
    };
  }

  const objectUrl = URL.createObjectURL(file);
  const image = new Image();
  try {
    await new Promise<void>((resolve, reject) => {
      image.onload = () => resolve();
      image.onerror = () => reject(new Error("The selected image could not be read"));
      image.src = objectUrl;
    });
    return {
      source: image,
      width: image.naturalWidth,
      height: image.naturalHeight,
      close: () => URL.revokeObjectURL(objectUrl),
    };
  } catch (error) {
    URL.revokeObjectURL(objectUrl);
    throw error;
  }
}

function canvasBlob(canvas: HTMLCanvasElement, quality: number): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => blob ? resolve(blob) : reject(new Error("The selected image could not be optimized")),
      "image/webp",
      quality,
    );
  });
}

export async function prepareModelImageUpload(file: File): Promise<File> {
  if (!file.type.startsWith("image/") || file.type === "image/gif" || file.size <= MODEL_IMAGE_OPTIMIZE_FROM_BYTES) {
    return file;
  }

  const decoded = await decodeImage(file);
  try {
    const scale = Math.min(1, MODEL_IMAGE_MAX_LONG_EDGE / Math.max(decoded.width, decoded.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(decoded.width * scale));
    canvas.height = Math.max(1, Math.round(decoded.height * scale));
    const context = canvas.getContext("2d", { alpha: false });
    if (!context) throw new Error("Image optimization is not available in this browser");
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(decoded.source, 0, 0, canvas.width, canvas.height);

    let optimized = await canvasBlob(canvas, 0.9);
    if (optimized.size > MODEL_IMAGE_OPTIMIZE_FROM_BYTES) optimized = await canvasBlob(canvas, 0.82);
    if (optimized.size > MODEL_IMAGE_OPTIMIZE_FROM_BYTES) optimized = await canvasBlob(canvas, 0.74);
    if (optimized.size >= file.size) return file;

    const baseName = file.name.replace(/\.[^.]+$/, "") || "model-photo";
    return new File([optimized], `${baseName}.webp`, {
      type: "image/webp",
      lastModified: Date.now(),
    });
  } finally {
    decoded.close();
  }
}
