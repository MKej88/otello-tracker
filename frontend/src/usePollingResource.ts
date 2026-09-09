import { useEffect, useState } from "react";
import { fetchPreloadedJson } from "./navigationDataPreload";
import {
  getCachedDashboardComponentForUrl,
  subscribeDashboardRevalidation,
} from "./dashboardBootstrapFetch";
import { subscribePageResumeRefresh } from "./pageResumeRefresh";

export type PollingResourceState<T> = {
  data: T | null;
  refreshFailed: boolean;
  lastUpdatedAt: Date | null;
};

export function usePollingResource<T>(
  url: string,
  intervalMs: number,
  usePreloadedInitial = false,
): PollingResourceState<T> {
  const [data, setData] = useState<T | null>(() => (
    usePreloadedInitial ? getCachedDashboardComponentForUrl<T>(url) : null
  ));
  const [refreshFailed, setRefreshFailed] = useState(false);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<Date | null>(null);

  useEffect(() => {
    let active = true;
    let inFlight = false;
    let firstLoad = true;
    let controller: AbortController | null = null;

    const load = async (forceFresh = false) => {
      if (inFlight) return;
      inFlight = true;
      const currentController = new AbortController();
      controller = currentController;

      try {
        let result: T;
        if (firstLoad && usePreloadedInitial && !forceFresh) {
          result = await fetchPreloadedJson<T>(url);
        } else {
          const response = await fetch(url, {
            signal: currentController.signal,
            cache: forceFresh ? "no-store" : "default",
          });
          if (!response.ok) {
            throw new Error(`Polling API-feil: ${response.status}`);
          }
          result = await response.json() as T;
        }
        firstLoad = false;
        if (!active) return;
        setData(result);
        setRefreshFailed(false);
        setLastUpdatedAt(new Date());
      } catch (error) {
        if (!active) return;
        if (error instanceof DOMException && error.name === "AbortError") return;
        setRefreshFailed(true);
      } finally {
        if (controller === currentController) controller = null;
        inFlight = false;
      }
    };

    void load();
    const unsubscribeRevalidation = subscribeDashboardRevalidation<T>(url, (result) => {
      if (!active) return;
      setData(result);
      setRefreshFailed(false);
      setLastUpdatedAt(new Date());
    });
    const timer = window.setInterval(() => { void load(); }, intervalMs);
    const unsubscribePageResume = subscribePageResumeRefresh(() => {
      void load(true);
    });
    return () => {
      active = false;
      window.clearInterval(timer);
      unsubscribePageResume();
      unsubscribeRevalidation?.();
      controller?.abort();
    };
  }, [url, intervalMs, usePreloadedInitial]);

  return { data, refreshFailed, lastUpdatedAt };
}
