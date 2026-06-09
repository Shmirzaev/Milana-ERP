"use client";
import Modal from "@/components/Modal";
import { useT } from "@/lib/i18n";

type ConfirmDialogProps = {
  isOpen: boolean;
  title: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  onConfirm: () => void;
  onCancel: () => void;
};

export default function ConfirmDialog({
  isOpen,
  title,
  message,
  confirmText,
  cancelText,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const { t } = useT();
  return (
    <Modal open={isOpen} onClose={onCancel} title={title}>
      <div className="space-y-4">
        <p className="text-sm text-slate-700">{message}</p>
        <div className="flex justify-end gap-2">
          <button type="button" className="btn" onClick={onCancel}>{cancelText ?? t("common.cancel")}</button>
          <button type="button" className="btn btn-danger" onClick={onConfirm}>{confirmText ?? t("common.confirm")}</button>
        </div>
      </div>
    </Modal>
  );
}
