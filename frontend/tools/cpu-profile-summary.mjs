/** Summarise a Chrome sampling profile without storing source, raw URLs or arguments. */
export function summarizeCpuProfile(profile, expectedOrigin) {
  const nodeFrames = new Map((profile?.nodes || []).map((node) => [node.id, node.callFrame]));
  const buckets = new Map();
  const samples = profile?.samples || [];
  const deltas = profile?.timeDeltas || [];
  let attributedSamples = 0;
  for (let index = 0; index < samples.length; index++) {
    const frame = nodeFrames.get(samples[index]);
    if (!frame?.url) continue;
    let url;
    try { url = new URL(frame.url); } catch { continue; }
    if (url.origin !== expectedOrigin || !url.pathname.endsWith(".js")) continue;
    const path = url.pathname;
    const rawName = String(frame.functionName || "(anonymous)");
    const functionName = /^[\w$ .<>:-]{1,80}$/.test(rawName) ? rawName : "(anonymous)";
    const key = path + "|" + functionName;
    const item = buckets.get(key) || { path, functionName, samples: 0, estimatedCpuMs: 0 };
    item.samples++;
    item.estimatedCpuMs += Math.max(0, Number(deltas[index]) || 0) / 1000;
    buckets.set(key, item);
    attributedSamples++;
  }
  return {
    totalSamples: samples.length,
    attributedSamples,
    topFunctions: [...buckets.values()]
      .sort((a, b) => b.estimatedCpuMs - a.estimatedCpuMs || b.samples - a.samples)
      .slice(0, 6)
      .map((item) => ({ ...item, estimatedCpuMs: Math.round(item.estimatedCpuMs) })),
  };
}
