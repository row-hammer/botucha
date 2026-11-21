import { type ClassValue, clsx } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

// custom theme colours, so `text-ok` replaces a variant's `text-foreground` instead of being dropped
const twMerge = extendTailwindMerge({ extend: { theme: { color: ["ok", "bad", "warn"] } } });

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
