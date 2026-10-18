import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

// Validate deployment files after all HTML build transforms.
const directory = resolve(process.argv[2] ?? "dist");
const html = readFileSync(resolve(directory, "index.html"), "utf8");
const headers = readFileSync(resolve(directory, "_headers"), "utf8");
const policies = [...headers.matchAll(/^\s*Content-Security-Policy:\s*(.+)$/gim)];
if (!policies.length) throw new Error("Missing Content-Security-Policy in _headers");

for (const [, policy] of policies) {
  const directive = policy.split(";").map((part) => part.trim())
    .find((part) => /^script-src\s/.test(part));
  if (!directive) throw new Error("Missing script-src directive");
  const sources = new Set(directive.split(/\s+/).slice(1));
  if (sources.has("'unsafe-inline'")) {
    throw new Error("Inline scripts must use explicit CSP hashes, not unsafe-inline");
  }
  for (const [, attributes, script] of html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script\b[^>]*>/gi)) {
    if (/\bsrc\s*=/i.test(attributes)) continue;
    const hash = `sha256-${createHash("sha256").update(script).digest("base64")}`;
    if (!sources.has(`'${hash}'`)) {
      throw new Error(`Inline script blocked by CSP. Review the script and update frontend/public/_headers with '${hash}'.`);
    }
  }
}
console.log("Inline scripts match the deployment Content-Security-Policy.");
