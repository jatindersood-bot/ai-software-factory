import type { Metadata } from "next";
import "./globals.css";
import ToastProviderWrapper from "./components/ToastProviderWrapper";

export const metadata: Metadata = {
  title: "AI Software Factory",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-gray-50 text-gray-900 antialiased">
        <ToastProviderWrapper>{children}</ToastProviderWrapper>
      </body>
    </html>
  );
}
