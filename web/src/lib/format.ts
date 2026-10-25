const dollars = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const wholeDollars = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});

export const money = (cents: number) => dollars.format(cents / 100);
export const moneyWhole = (cents: number) => wholeDollars.format(cents / 100);
export const percent = (part: number, whole: number) =>
  whole ? `${((part / whole) * 100).toFixed(1)}%` : "–";

const CHANNELS: Record<string, string> = {
  dine_in: "Dine-in",
  ubereats: "Uber Eats",
  doordash: "DoorDash",
  grubhub: "Grubhub",
  takeout: "Takeout",
};
export const channelName = (c: string) =>
  CHANNELS[c] ?? c.replace(/_/g, " ").replace(/^\w/, (s) => s.toUpperCase());

const day = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" });
export const dayRange = (from: string, to: string) =>
  `${day.format(new Date(`${from}T12:00`))} to ${day.format(new Date(`${to}T12:00`))}`;
