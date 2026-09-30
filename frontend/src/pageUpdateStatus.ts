import { createContext, createElement, useContext, useEffect, type ReactNode } from "react";
import { freshnessStatus, type FreshnessCadence } from "./dataFreshness";

export type PageUpdate = {
  timestamp?: string | null;
  cadence: FreshnessCadence;
  label?: string;
  warning?: string | null;
};

const PageUpdateContext = createContext<((update: PageUpdate) => void) | null>(null);
export { pageUpdateLabel } from "./pageUpdateFormat";

export function PageUpdateProvider({
  children,
  onUpdate,
}: {
  children: ReactNode;
  onUpdate: (update: PageUpdate) => void;
}) {
  return createElement(PageUpdateContext.Provider, { value: onUpdate }, children);
}

/** Rapporter tidspunktet som allerede finnes i sidens eget datagrunnlag. */
export function usePageUpdate(
  timestamp: string | null | undefined,
  cadence: FreshnessCadence,
  options?: { label?: string; warning?: string | null },
) {
  const reportUpdate = useContext(PageUpdateContext);
  const label = options?.label;
  const warning = options?.warning;

  useEffect(() => {
    reportUpdate?.({ timestamp, cadence, label, warning });
  }, [cadence, reportUpdate, timestamp, label, warning]);
}

export function pageUpdateIsStale(update: PageUpdate | null, now = new Date()) {
  if (update?.warning) return true;
  if (!update?.timestamp) return false;
  return freshnessStatus(update.cadence, update.timestamp, now) === "stale";
}
