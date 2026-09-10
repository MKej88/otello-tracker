import assert from "node:assert/strict";
import test from "node:test";

import { subscribePageResumeRefresh } from "../src/pageResumeRefresh.ts";

class FakeEventTarget extends EventTarget {
  visibilityState: DocumentVisibilityState = "hidden";
}

test("oppdaterer når en skjult side blir synlig igjen", () => {
  const pageWindow = new FakeEventTarget();
  const pageDocument = new FakeEventTarget();
  let refreshCount = 0;

  const unsubscribe = subscribePageResumeRefresh(
    () => { refreshCount += 1; },
    pageWindow,
    pageDocument,
  );

  pageDocument.dispatchEvent(new Event("visibilitychange"));
  assert.equal(refreshCount, 0);

  pageDocument.visibilityState = "visible";
  pageDocument.dispatchEvent(new Event("visibilitychange"));
  assert.equal(refreshCount, 1);

  unsubscribe();
  pageDocument.dispatchEvent(new Event("visibilitychange"));
  assert.equal(refreshCount, 1);
});

test("oppdaterer når nettleseren gjenoppretter siden fra hurtigminnet", () => {
  const pageWindow = new FakeEventTarget();
  const pageDocument = new FakeEventTarget();
  let refreshCount = 0;

  subscribePageResumeRefresh(
    () => { refreshCount += 1; },
    pageWindow,
    pageDocument,
  );

  const normalPageShow = new Event("pageshow");
  Object.defineProperty(normalPageShow, "persisted", { value: false });
  const restoredPageShow = new Event("pageshow");
  Object.defineProperty(restoredPageShow, "persisted", { value: true });
  pageWindow.dispatchEvent(normalPageShow);
  pageWindow.dispatchEvent(restoredPageShow);

  assert.equal(refreshCount, 1);
});
