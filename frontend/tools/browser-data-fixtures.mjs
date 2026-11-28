// Browser-only synthetic scenarios. Never import this module in frontend/src.
export const HISTORY_PATH = "/api/dashboard/discount-history?days=365&max_points=72";
export const BUYBACK_PATH = "/api/buybacks/dashboard";
export const BRAZIL_PATH = "/api/brazil/dashboard";
export const BUYBACK_FIXTURE_DATE = "2026-08-17";

export function richHistoryFixture() {
  return {
    estimated: {
      ready: true, from: "2026-08-11", to: "2026-08-13",
      observation_count: 3, chart_point_count: 3,
      points: [
        {date: "2026-08-11", nav_per_share: 20, otec_price: 17, discount_pct: 15},
        {date: "2026-08-12", nav_per_share: 20, otec_price: 16, discount_pct: 20},
        {date: "2026-08-13", nav_per_share: 20, otec_price: 15, discount_pct: 25},
      ],
      statistics: {
        count: 3, current_discount_pct: 25, average_discount_pct: 20,
        median_discount_pct: 20, p10_discount_pct: 16, p90_discount_pct: 24,
        minimum_discount_pct: 15, minimum_discount_date: "2026-08-11",
        maximum_discount_pct: 25, maximum_discount_date: "2026-08-13",
        current_percentile: 100 * 2.5 / 3,
      },
      note: "Syntetiske testdata – ikke markedsdata.",
    },
  };
}

export function richBrazilFixture() {
  const date = "2026-08-13";
  const definitions = [
    ["selic", "Styringsrente", "%", 15, 14.75],
    ["ipca_12m", "Inflasjon", "%", 4.5, 4.6],
    ["ibc_br", "Økonomisk aktivitet", "%", 2.3, 2.1],
    ["ibc_services", "Tjenesteaktivitet", "%", 2.1, 2.0],
    ["brl_nok", "BRL/NOK", "NOK", 1.92, 1.9],
  ];
  const metrics = Object.fromEntries(definitions.map(([key,label,unit,value,previous_value]) => [key, {
    key,label,unit,value,previous_value,date,source:"Syntetisk testkilde",
    change:value-previous_value, change_1m_pct:100*(value/previous_value-1),
    series:[{date:"2026-07-13",value:previous_value},{date,value}],
  }]));
  const estimates = {selic:[14.5,12],ipca:[4.5,4],gdp:[2.3,2.1],usd_brl:[5.4,5.3]};
  const values = Object.fromEntries(Object.entries(estimates).map(([key, pair]) => [key,
    Object.fromEntries([2026,2027].map((year,i) => [String(year), {median:pair[i],survey_date:date,respondents:50}]))
  ]));
  const points_by_year = Object.fromEntries([2026,2027].map((year,i) => [String(year),
    Object.fromEntries(["selic","ipca","gdp"].map(key => [key,{
      year,current:estimates[key][i],previous:estimates[key][i]+0.25,change:-0.25,change_bp:-25,
      current_survey_date:date,previous_survey_date:"2026-07-13",
    }]))
  ]));
  const driver = {tone:"neutral",label:"Nøytral",summary:"Syntetisk testgrunnlag"};
  return {
    ready:true,as_of_date:date,generated_at:date+"T12:00:00Z",metrics,
    focus:{ready:true,values,focus_meta:{ref_date:date,current_year:2026,next_year:2027}},
    focus_trend:{ready:true,comparison_years:[2026,2027],comparisons:{"30d":{ready:true,ref_date:"2026-07-13",points_by_year}}},
    investor_summary:{tone:"neutral",headline:"Syntetisk makrobilde",drivers:{valuation:driver,operations:driver,nav_fx:driver},
      rate_path:{current:15,current_year_estimate:14.5,next_year_estimate:12,expected_change_to_current_year_bp:-50,expected_change_to_next_year_bp:-300,expected_change_current_to_next_year_bp:-250}},
    calendar:[{date:"2026-08-20",name:"Testpublisering",kind:"TEST",source:"Syntetisk testkilde",source_url:"https://example.test/fixture",importance:"Høy",bemobi_impact:"Syntetiske testdata",expectation:{label:"Test",value:4.5,unit:"%"}}],
    latest_high_importance_release:{date,name:"Testinflasjon",importance:"Høy",actual:"4,50 %",forecast:"4,60 %",surprise:-0.1},
    sources:[{name:"Syntetisk testkilde",url:"https://example.test/fixture"}],
  };
}

export function fixtureOrigin(baseUrl) {
  const url = new URL(baseUrl);
  if (url.protocol !== "http:" || !["127.0.0.1","localhost","[::1]"].includes(url.hostname)) {
    throw new Error("Datarike nettlesertester krever lokal Worker.");
  }
  return url.origin;
}

// Serialized only into a fresh local test document using Chrome DevTools.
function installFixtures(origin, payloads) {
  if (location.origin !== origin) return;
  const original = window.fetch.bind(window);
  window.__otelloTestFixtureHits = {};
  window.fetch = async (input, init) => {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url, location.origin);
    const method = String(init?.method ?? (input instanceof Request ? input.method : "GET")).toUpperCase();
    const path = url.pathname + url.search;
    if (url.origin === origin && method === "GET" && Object.hasOwn(payloads, path)) {
      window.__otelloTestFixtureHits[path] = (window.__otelloTestFixtureHits[path] ?? 0) + 1;
      return Response.json(payloads[path]);
    }
    return original(input, init);
  };
}

export function fixtureScript(baseUrl, buyback) {
  const origin = fixtureOrigin(baseUrl);
  if (buyback?.ready !== true || !buyback.program) throw new Error("Testdatabasen mangler aktivt tilbakekjøpsprogram.");
  const payloads = {[HISTORY_PATH]:richHistoryFixture(),[BUYBACK_PATH]:buyback,[BRAZIL_PATH]:richBrazilFixture()};
  return "(" + installFixtures.toString() + ")(" + JSON.stringify(origin) + "," + JSON.stringify(payloads) + ");";
}
