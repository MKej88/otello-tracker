/**
 * Request-scoped diagnostic events from Node's built-in Undici transport.
 * Timing is intentionally transport-only: it is not an inference of Worker CPU,
 * CDN processing, DNS or TLS individually.
 *
 * No request or response headers, remote addresses or tokens are recorded.
 */
import { channel } from "node:diagnostics_channel";
import { performance } from "node:perf_hooks";

export function cloudflareColo(cfRay) {
  const match = typeof cfRay === "string"
    ? /-([A-Za-z]{3})$/.exec(cfRay.trim()) : null;
  return match ? match[1].toUpperCase() : null;
}

export function phaseDurations(points, startedAt) {
  const { createdAt, sentAt, receivedAt } = points;
  const between = (a, b) => Number.isFinite(a) && Number.isFinite(b) && b >= a
    ? Math.round(b - a) : null;
  return {
    fetchToRequestMs: between(startedAt, createdAt),
    requestToSendMs: between(createdAt, sentAt),
    sendToHeadersMs: between(sentAt, receivedAt),
  };
}

export function watchUndiciRequest(target, now = () => performance.now()) {
  const url = new URL(target);
  const expectedPath = url.pathname + url.search;
  let active = null;
  let createdAt = null;
  let sentAt = null;
  let receivedAt = null;

  function onCreate({ request }) {
    if (String(request?.origin) !== url.origin || request?.path !== expectedPath) return;
    active = request;
    createdAt = now();
    sentAt = null;
    receivedAt = null;
  }
  function onSend({ request }) {
    if (request === active) sentAt = now();
  }
  function onHeaders({ request }) {
    if (request === active) receivedAt = now();
  }
  const listeners = [
    [channel("undici:request:create"), onCreate],
    [channel("undici:client:sendHeaders"), onSend],
    [channel("undici:request:headers"), onHeaders],
  ];
  for (const [name, callback] of listeners) name.subscribe(callback);
  let closed = false;
  return {
    snapshot(startedAt) {
      return phaseDurations({ createdAt, sentAt, receivedAt }, startedAt);
    },
    close() {
      if (closed) return;
      closed = true;
      for (const [name, callback] of listeners) name.unsubscribe(callback);
    },
  };
}
