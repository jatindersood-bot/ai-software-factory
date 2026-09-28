"use client";

import { ToastProvider } from "./ToastContext";

export default function ToastProviderWrapper({
  children,
}: {
  children: React.ReactNode;
}) {
  return <ToastProvider>{children}</ToastProvider>;
}
