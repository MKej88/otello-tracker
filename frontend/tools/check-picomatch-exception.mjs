// Temporary, explicitly scoped waiver for an *unpatched* dev-only advisory.
//
// Audit remains mandatory for all other vulnerabilities (including transitive
// effects not caused by this advisory). The waiver expires automatically.
// GHSA-fc5q-39xc-vjpf: https://github.com/advisories/GHSA-fc5q-39xc-vjpf
import { readFileSync } from "node:fs";

const EXPIRES_AT = Date.parse("2026-12-16T00:00:00Z");
const ADVISORY = "https://github.com/advisories/GHSA-fc5q-39xc-vjpf";
const TRANSITIVE = new Set(["picomatch", "fdir", "tinyglobby", "vite", "@vitejs/plugin-react"]);

function reject(reason) {
  console.error("Npm security exception refused:", reason);
  process.exit(1);
}

if (Date.now() >= EXPIRES_AT) reject("temporary waiver expired");
let report;
try {
  report = JSON.parse(readFileSync(0, "utf8"));
} catch {
  reject("npm audit did not return valid JSON");
}
if (!report?.vulnerabilities || report?.error) {
  reject("npm audit report is incomplete");
}
const vulnerable = Object.entries(report.vulnerabilities).filter(
  ([, detail]) => ["high", "critical"].includes(detail?.severity),
);
if (vulnerable.length === 0) reject("no high/critical advisory to waive");
if (!vulnerable.some(([name]) => name === "picomatch")) reject("picomatch advisory missing");

const causes = [];
for (const [name, item] of vulnerable) {
  if (!TRANSITIVE.has(name)) reject("other high/critical issue: " + name);
  for (const via of item.via ?? []) {
    if (typeof via === "string") {
      if (!TRANSITIVE.has(via)) reject("unexpected transitive advisory: " + via);
    } else {
      const url = String(via?.url ?? "").replace(/\/$/, "");
      if (name !== "picomatch" || url !== ADVISORY) {
        reject("unrelated advisory: " + (url || name));
      }
      causes.push(url);
    }
  }
}
if (causes.length !== 1) reject("expected precisely one known advisory");

const lock = JSON.parse(readFileSync(new URL("../package-lock.json", import.meta.url), "utf8"));
for (const name of TRANSITIVE) {
  const node = lock.packages?.["node_modules/" + name];
  if (!node || node.dev !== true) reject("dependency not dev-only in lock: " + name);
}
if (lock.packages?.["node_modules/picomatch"]?.version !== "4.0.7") {
  reject("picomatch version differs from reviewed risk assessment");
}
console.log(
  "Temporary dev-only exception for GHSA-fc5q-39xc-vjpf (picomatch 4.0.7). " +
  "All other high/critical advisories still fail. Waiver expires 2026-12-16.",
);
