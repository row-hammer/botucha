"use client";

import { toast } from "sonner";
import { translate, useLang } from "@/lib/i18n";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

let token: Promise<string> | null = null;

async function getToken(): Promise<string> {
  token ??= fetch("/api/session")
    .then((r) => r.json())
    .then((b) => b.token as string)
    .catch((e) => {
      token = null;
      throw e;
    });
  return token;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (method !== "GET") headers.set("X-Botucha-Token", await getToken());
  let res: Response;
  try {
    res = await fetch(path, { ...init, method, headers });
  } catch {
    const msg = translate(useLang.getState().lang, "errors.network");
    toast.error(msg);
    throw new ApiError(0, msg);
  }
  if (res.status === 403 && method !== "GET") token = null; // service restarted: new token
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = await res.json();
      msg = body.error ?? (typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail)) ?? msg;
    } catch {
      /* not JSON */
    }
    if (res.status === 503 && msg === "busy") toast.error(translate(useLang.getState().lang, "errors.busy"));
    throw new ApiError(res.status, msg);
  }
  const type = res.headers.get("content-type") ?? "";
  return (type.includes("json") ? res.json() : res.text()) as Promise<T>;
}

export const post = <T>(path: string, body: unknown, method = "POST") =>
  api<T>(path, { method, body: JSON.stringify(body) });
