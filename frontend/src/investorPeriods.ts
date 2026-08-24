export type InvestorPeriod = { key: string; label: string; days: number };

function ytdDays() {
  const now = new Date();
  const start = new Date(now.getFullYear(), 0, 1);
  return Math.max(30, Math.ceil((now.getTime() - start.getTime()) / 86_400_000) + 1);
}

export function investorPeriods(): InvestorPeriod[] {
  return [
    { key: "1m", label: "1 M", days: 31 },
    { key: "3m", label: "3 M", days: 92 },
    { key: "6m", label: "6 M", days: 183 },
    { key: "ytd", label: "YTD", days: ytdDays() },
    { key: "1y", label: "1 ÅR", days: 365 },
    { key: "3y", label: "3 ÅR", days: 1095 },
  ];
}
