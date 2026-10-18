import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";

for (const [opening, closing] of [
  ["<script>", "</script>"],
  ["<SCRIPT>", "</SCRIPT>"],
  ["<script>", "</script\t\n bar>"],
]) {
  test(`CSP validates exact script bytes: ${JSON.stringify(closing)}`, () => {
    const directory = mkdtempSync(join(tmpdir(), "inline-csp-"));
    const script = "\nconsole.log('preload');\n";
    const hash = createHash("sha256").update(script).digest("base64");
    try {
      writeFileSync(join(directory, "index.html"), `${opening}${script}${closing}`);
      writeFileSync(join(directory, "_headers"), `/*\n  Content-Security-Policy: script-src 'self' 'sha256-${hash}'\n`);
      const run = () => spawnSync(process.execPath, ["tools/check-inline-csp.mjs", directory], { encoding: "utf8" });
      assert.equal(run().status, 0);
      writeFileSync(join(directory, "index.html"), `${opening}${script}changed${closing}`);
      const rejected = run();
      assert.notEqual(rejected.status, 0);
      assert.match(rejected.stderr, /Inline script blocked by CSP/);
    } finally {
      rmSync(directory, { recursive: true, force: true });
    }
  });
}
