import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(new URL("../src/ConsensusPage.tsx", import.meta.url), "utf8");
const styles = readFileSync(new URL("../src/consensus-page.css", import.meta.url), "utf8");

test("quarter broker headings use a linked name and one non-breaking date row", () => {
  assert.match(page, /className="consensusBrokerName"/);
  assert.match(page, /className="consensusBrokerDate"/);
  assert.match(page, /compactDateLabel\(broker\.verifiedDate\)/);
  assert.doesNotMatch(page, /<small>Offentlig (?:artikkel|sammendrag)<\/small>/);
  assert.match(page, /Klikk på meglernavnet for kilden/);
});

test("broker table keeps columns readable and allows horizontal scroll", () => {
  assert.match(styles, /\.consensusBrokerTable\s*\{[^}]*min-width:\s*780px;/s);
  assert.match(styles, /\.consensusBrokerTable thead th\s*\{[^}]*white-space:\s*nowrap;/s);
  assert.match(styles, /\.consensusBrokerName\s*\{[^}]*white-space:\s*nowrap;/s);
  assert.match(styles, /\.consensusBrokerDate\s*\{[^}]*white-space:\s*nowrap;/s);
  assert.match(styles, /\.consensusTableWrap\s*\{[^}]*overflow-x:\s*auto;/s);
  assert.match(styles, /@media \(min-width: 1700px\)/);
});

test("Q3 consensus shows one short footnote instead of detailed source prose", () => {
  const start = page.indexOf('<p className="consensusNote">Klikk på meglernavnet for kilden.');
  assert.ok(start >= 0);
  const end = page.indexOf('            </>', start);
  assert.ok(end > start);
  const notes = page.slice(start, end);
  assert.equal((notes.match(/className="consensusNote"/g) ?? []).length, 1);
  assert.match(notes, /Snittet vekter meglerhus likt \(n = antall\)/);
  assert.match(notes, /\* = beregnet verdi/);
  assert.match(notes, /Ordinært og justert nettoresultat holdes adskilt/);
  assert.doesNotMatch(notes, /nextQuarter\?\.note|Offentlig sammendrag|Hold markøren/);
});
