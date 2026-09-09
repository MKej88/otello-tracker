type PageLifecycleTarget = {
  addEventListener: (type: string, listener: EventListener) => void;
  removeEventListener: (type: string, listener: EventListener) => void;
};

type VisibilityTarget = PageLifecycleTarget & {
  visibilityState: DocumentVisibilityState;
};

/** Refresh data when a suspended or backgrounded page becomes active again. */
export function subscribePageResumeRefresh(
  refresh: () => void,
  pageWindow: PageLifecycleTarget = window,
  pageDocument: VisibilityTarget = document,
): () => void {
  const handlePageShow: EventListener = (event) => {
    if ("persisted" in event && event.persisted === true) refresh();
  };
  const handleVisibilityChange: EventListener = () => {
    if (pageDocument.visibilityState === "visible") refresh();
  };

  pageWindow.addEventListener("pageshow", handlePageShow);
  pageDocument.addEventListener("visibilitychange", handleVisibilityChange);

  return () => {
    pageWindow.removeEventListener("pageshow", handlePageShow);
    pageDocument.removeEventListener("visibilitychange", handleVisibilityChange);
  };
}
