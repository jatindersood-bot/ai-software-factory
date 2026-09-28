import { NextResponse } from "next/server";

export async function POST(req: Request) {
  const body = await req.json();

  const API_BASE =
    process.env.NEXT_PUBLIC_API_BASE ||
    process.env.API_BASE ||
    "http://localhost:8000";

  const r = await fetch(`${API_BASE}/submit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  const text = await r.text();

  return new NextResponse(text, {
    status: r.status,
    headers: {
      "Content-Type": r.headers.get("content-type") ?? "application/json",
    },
  });
}
