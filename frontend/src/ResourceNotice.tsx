import type { ReactNode } from "react";

type ResourceNoticeProps = {
  children: ReactNode;
  kind?: "error" | "loading" | "empty" | "stale";
};

export default function ResourceNotice({
  children,
  kind = "loading",
}: ResourceNoticeProps) {
  return (
    <div className={`resourceNotice ${kind}`} role={kind === "error" ? "alert" : "status"}>
      {children}
    </div>
  );
}
