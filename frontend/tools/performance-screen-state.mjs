/** Lightweight route-state probe injected only into synthetic Chrome. */
export function screenState(routeDefinitions, doc = document, currentLocation = location) {
  const route = routeDefinitions.find((item) => item.hash === currentLocation.hash.toLowerCase());
  const heading = doc.querySelector(".investorTopbar h1")?.textContent?.trim();
  const marker = route ? doc.querySelector(route.selector) : null;
  let ready = Boolean(route && marker && heading === route.heading);
  if (ready && route.kind === "price") {
    ready = marker.textContent.includes("kr") && !marker.querySelector(".loadingPlaceholder");
  }
  if (ready && route.kind === "news") {
    ready = !doc.querySelector(".loadingPlaceholderNews, .loadingPlaceholderCalendar");
  }
  if (ready && route.kind === "quality") {
    ready = !doc.querySelector(".qualityTrustLead small")?.textContent?.trim().endsWith("–");
  }
  // Avoid document.body.innerText: it can trigger style/layout work on every
  // MutationObserver frame, making synthetic Chrome appear slower than users.
  const error = Boolean(doc.querySelector(".brazilError, .resourceNoticeError")) ||
    [...doc.querySelectorAll(".investorMainV2 [role='alert'], .investorMainV2 .resourceNotice")]
      .some((item) => /Kunne ikke hente (?:investordata|NAV-historikk|Bemobi-data|konsensusdata|NAV-sammensetningen)\./
        .test(item.textContent || ""));
  return {
    ready, error, label: route?.label || null, heading,
    headingMatches: Boolean(route && heading === route.heading),
    markerFound: Boolean(marker),
    loading: Boolean(doc.querySelector(".loadingPlaceholderPage, .loadingPlaceholder, .loadingPlaceholderNews")),
    unavailable: Boolean(doc.querySelector(".fxError, .bemobiNotice, .brazilError, .resourceNoticeError")),
  };
}
