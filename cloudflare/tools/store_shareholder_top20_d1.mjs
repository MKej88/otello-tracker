import crypto from "node:crypto";
import fs from "node:fs/promises";
import process from "node:process";

const INPUT_PATH = process.env.TOP20_OUTPUT || "/tmp/otec-top20.json";
const SOURCE_KIND = "EURONEXT_OMS";
const EXPECTED_ROWS = 20;

function required(name) {
  const value = String(process.env[name] || "").trim();
  if (!value) throw new Error(`Mangler miljøvariabel ${name}`);
  return value;
}

function osloDate(now = new Date()) {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/Oslo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(now);
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

function clean(value) {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function canonicalRows(rows) {
  return rows.map((row, index) => ({
    rank: index + 1,
    shareholder_name: clean(row.shareholder_name),
    country: clean(row.country) || null,
    shares: Number(row.shares),
    ownership_pct:
      row.ownership_pct == null || row.ownership_pct === "" ? null : String(row.ownership_pct),
    account_type: clean(row.account_type) || null,
  }));
}

function positionKey(row) {
  return [
    clean(row.shareholder_name).toLocaleLowerCase("en"),
    Number(row.shares),
    clean(row.country).toLocaleUpperCase("en"),
    clean(row.account_type).toLocaleUpperCase("en"),
  ].join("|");
}

function validateRows(rows) {
  if (!Array.isArray(rows) || rows.length !== EXPECTED_ROWS) {
    throw new Error(`Forventet ${EXPECTED_ROWS} rader, fant ${Array.isArray(rows) ? rows.length : 0}`);
  }
  const positions = rows.map(positionKey);
  if (new Set(positions).size !== EXPECTED_ROWS) throw new Error("Dupliserte Top 20-posisjoner");
  if (rows.some((row, index) => row.rank !== index + 1 || !Number.isInteger(row.shares) || row.shares <= 0)) {
    throw new Error("Ugyldig rangering eller aksjetall");
  }
  const pctSum = rows.reduce((sum, row) => sum + (row.ownership_pct == null ? 0 : Number(row.ownership_pct)), 0);
  if (pctSum > 100.5) throw new Error(`Ugyldig sum eierandeler: ${pctSum}`);
}

const accountId = required("CLOUDFLARE_ACCOUNT_ID");
const databaseId = required("CLOUDFLARE_D1_DATABASE_ID");
const apiToken = required("CLOUDFLARE_API_TOKEN");
const apiUrl = `https://api.cloudflare.com/client/v4/accounts/${accountId}/d1/database/${databaseId}/query`;

async function d1(body) {
  const response = await fetch(apiUrl, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  const text = await response.text();
  let payload;
  try {
    payload = JSON.parse(text);
  } catch {
    throw new Error(`D1 svarte HTTP ${response.status} med ugyldig JSON: ${text.slice(0, 500)}`);
  }
  if (!response.ok || payload.success === false || (payload.errors || []).length) {
    throw new Error(`D1-feil HTTP ${response.status}: ${JSON.stringify(payload.errors || payload).slice(0, 1200)}`);
  }
  const results = Array.isArray(payload.result) ? payload.result : [];
  if (results.some((result) => result && result.success === false)) {
    throw new Error(`D1-spørring feilet: ${JSON.stringify(results).slice(0, 1200)}`);
  }
  return payload;
}

async function query(sql, params = []) {
  const payload = await d1({ sql, params });
  return payload.result?.[0]?.results || [];
}

const capture = JSON.parse(await fs.readFile(INPUT_PATH, "utf8"));
const rows = canonicalRows(capture.rows || []);
validateRows(rows);

const targetDate = String(process.env.TOP20_DATE || osloDate()).slice(0, 10);
if (!/^\d{4}-\d{2}-\d{2}$/.test(targetDate)) throw new Error(`Ugyldig TOP20_DATE: ${targetDate}`);
const sourceUrl = clean(capture.source_url) || "https://ir.oms.no/component/shareholders?lang=en&token=opera";
const method = clean(capture.method) || "GITHUB_PLAYWRIGHT";
const canonical = JSON.stringify(rows);
const contentHash = crypto.createHash("sha256").update(canonical).digest("hex");

const shareCounts = await query(
  "SELECT total_shares, treasury_shares, outstanding_shares FROM otello_share_counts ORDER BY effective_from DESC, id DESC LIMIT 1"
);
if (!shareCounts.length) throw new Error("Mangler otello_share_counts i produksjons-D1");
const shareCount = shareCounts[0];

const runUrl =
  process.env.GITHUB_SERVER_URL && process.env.GITHUB_REPOSITORY && process.env.GITHUB_RUN_ID
    ? `${process.env.GITHUB_SERVER_URL}/${process.env.GITHUB_REPOSITORY}/actions/runs/${process.env.GITHUB_RUN_ID}`
    : null;
const notes = JSON.stringify({
  content_sha256: contentHash,
  extraction_method: method,
  capture_run_url: runUrl,
  permission_basis: "PROJECT_OWNER_CONFIRMED_PERMISSION_2026-08-19",
  captured_at: capture.captured_at || new Date().toISOString(),
  row_count: EXPECTED_ROWS,
});

const batch = [
  {
    sql: "DELETE FROM shareholder_snapshots WHERE snapshot_date=? AND source_kind=?",
    params: [targetDate, SOURCE_KIND],
  },
  {
    sql: `INSERT INTO shareholder_snapshots(
      snapshot_date, source_url, source_kind, total_issued_shares,
      treasury_shares, outstanding_shares, notes
    ) VALUES (?, ?, ?, CAST(? AS INTEGER), CAST(? AS INTEGER), CAST(? AS INTEGER), ?)`,
    params: [
      targetDate,
      sourceUrl,
      SOURCE_KIND,
      String(shareCount.total_shares),
      String(shareCount.treasury_shares),
      String(shareCount.outstanding_shares),
      notes,
    ],
  },
];

for (const row of rows) {
  batch.push({
    sql: `INSERT INTO shareholder_snapshot_rows(
      snapshot_id, rank, shareholder_name, country, shares, ownership_pct, account_type
    )
    SELECT id, CAST(? AS INTEGER), ?, NULLIF(?, ''), CAST(? AS INTEGER), NULLIF(?, ''), NULLIF(?, '')
    FROM shareholder_snapshots
    WHERE snapshot_date=? AND source_kind=?
    LIMIT 1`,
    params: [
      String(row.rank),
      row.shareholder_name,
      row.country || "",
      String(row.shares),
      row.ownership_pct || "",
      row.account_type || "",
      targetDate,
      SOURCE_KIND,
    ],
  });
}

await d1({ batch });

const verification = await query(
  `SELECT s.snapshot_date, COUNT(r.id) AS row_count
   FROM shareholder_snapshots s
   LEFT JOIN shareholder_snapshot_rows r ON r.snapshot_id=s.id
   WHERE s.snapshot_date=? AND s.source_kind=?
   GROUP BY s.id, s.snapshot_date`,
  [targetDate, SOURCE_KIND]
);
if (verification.length !== 1 || Number(verification[0].row_count) !== EXPECTED_ROWS) {
  throw new Error(`Top 20 ble ikke lagret komplett: ${JSON.stringify(verification)}`);
}

console.log(
  JSON.stringify({
    stored: true,
    snapshot_date: targetDate,
    rows: EXPECTED_ROWS,
    method,
    content_sha256: contentHash,
  })
);