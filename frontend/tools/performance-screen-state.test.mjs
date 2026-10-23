import test from "node:test";
import assert from "node:assert/strict";
import { screenState } from "./performance-screen-state.mjs";

const routes = [
  { label: "Oversikt", heading: "Otello investoroversikt", hash: "#oversikt", selector: ".overviewNavCard h2", kind: "price" },
];
function fakeDoc({ price = "21 kr", notice = "", error = false } = {}) {
  const headline = { textContent: "Otello investoroversikt" };
  const marker = { textContent: price, querySelector: () => null };
  const selectors = [];
  const doc = {
    // A read here would silently alter the timing experiment.
    body: { get innerText() { throw new Error("Layout-forcing innerText read"); } },
    querySelector(selector) {
      selectors.push(selector);
      if (selector === ".investorTopbar h1") return headline;
      if (selector === ".overviewNavCard h2") return marker;
      if (selector === ".resourceNoticeError" && error) return { textContent: notice };
      if (selector.includes(".brazilError") && error) return { textContent: notice };
      return null;
    },
    querySelectorAll() { return notice ? [{ textContent: notice }] : []; },
  };
  return { doc, selectors };
}

test("ready marker uses narrow DOM reads, never body.innerText", () => {
  const { doc } = fakeDoc();
  const status = screenState(routes, doc, { hash: "#oversikt" });
  assert.equal(status.ready, true);
  assert.equal(status.error, false);
});
test("known fetch error remains detectable without traversing the whole page", () => {
  const { doc } = fakeDoc({ notice: "Kunne ikke hente investordata." });
  const status = screenState(routes, doc, { hash: "#oversikt" });
  assert.equal(status.error, true);
});
test("placeholder does not count as loaded price", () => {
  const { doc } = fakeDoc({ price: "—" });
  const status = screenState(routes, doc, { hash: "#oversikt" });
  assert.equal(status.ready, false);
});
