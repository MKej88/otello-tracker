import { lazy, Suspense, useEffect, useState } from "react";

const ReportStatusMount = lazy(() => import("./ReportStatusPanel"));
const RuntimeStatusMount = lazy(() => import("./RuntimeStatusPanel"));

export default function DeferredDiagnostics() {
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let timer: number | null = null;
    const schedule = () => {
      timer = window.setTimeout(() => setReady(true), 4000);
    };

    if (document.readyState === "complete") schedule();
    else window.addEventListener("load", schedule, { once: true });

    return () => {
      window.removeEventListener("load", schedule);
      if (timer != null) window.clearTimeout(timer);
    };
  }, []);

  if (!ready) return null;
  return (
    <Suspense fallback={null}>
      <ReportStatusMount />
      <RuntimeStatusMount />
    </Suspense>
  );
}
