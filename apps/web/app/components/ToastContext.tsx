"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type ToastType = "success" | "error";

export type Toast = {
  id: number;
  type: ToastType;
  message: string;
};

type ToastContextValue = {
  toasts: Toast[];
  addToast: (type: ToastType, message: string) => void;
  removeToast: (id: number) => void;
};

const ToastContext = createContext<ToastContextValue | null>(null);

let nextId = 0;
const AUTO_DISMISS_MS = 5000;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const addToast = useCallback((type: ToastType, message: string) => {
    const id = ++nextId;
    setToasts((prev) => [...prev, { id, type, message }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, AUTO_DISMISS_MS);
  }, []);

  const removeToast = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const value = useMemo(
    () => ({ toasts, addToast, removeToast }),
    [toasts, addToast, removeToast]
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      <ToastContainer />
    </ToastContext.Provider>
  );
}

function ToastContainer() {
  const ctx = useContext(ToastContext);
  if (!ctx) return null;
  const { toasts, removeToast } = ctx;
  if (toasts.length === 0) return null;
  return (
    <div
      className="fixed bottom-4 right-4 z-[100] flex flex-col gap-2 max-w-md"
      role="region"
      aria-label="Notifications"
    >
      {toasts.map((t) => (
        <div
          key={t.id}
          role="alert"
          className={
            t.type === "success"
              ? "rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-800 shadow"
              : "rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800 shadow"
          }
        >
          <p className="font-medium">
            {t.type === "success" ? "Success" : "Error"}
          </p>
          <p className="mt-0.5">{t.message}</p>
          <button
            type="button"
            onClick={() => removeToast(t.id)}
            className="mt-2 text-xs underline hover:no-underline"
          >
            Dismiss
          </button>
        </div>
      ))}
    </div>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within ToastProvider");
  return ctx;
}
