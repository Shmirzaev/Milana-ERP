"use client";
import Modal from "@/components/Modal";

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
  confirmText = "Confirm",
  cancelText = "Cancel",
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  return (
    <Modal open={isOpen} onClose={onCancel} title={title}>
      <div className="space-y-4">
        <p className="text-sm text-slate-700">{message}</p>
        <div className="flex justify-end gap-2">
          <button type="button" className="btn" onClick={onCancel}>{cancelText}</button>
          <button type="button" className="btn btn-danger" onClick={onConfirm}>{confirmText}</button>
        </div>
      </div>
    </Modal>
  );
}
