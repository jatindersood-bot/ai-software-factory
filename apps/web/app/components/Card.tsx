"use client";

import type { ReactNode } from "react";

type CardProps = {
  children: ReactNode;
  className?: string;
};

/** Renders a div - use for JSX when compiler rejects lowercase div */
export function Box({
  children,
  className = "",
  ...props
}: { children?: ReactNode; className?: string } & React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={className} {...props}>
      {children}
    </div>
  );
}

export function Card({ children, className = "" }: CardProps) {
  return (
    <div
      className={`rounded-lg border border-gray-200 bg-white shadow-sm ${className}`}
    >
      {children}
    </div>
  );
}

export function CardHeader({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`border-b border-gray-100 px-4 py-3 ${className}`}>
      {children}
    </div>
  );
}

export function CardBody({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={`px-4 py-3 ${className}`}>{children}</div>;
}
