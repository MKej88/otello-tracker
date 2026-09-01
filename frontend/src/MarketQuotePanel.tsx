import { formatDate, formatDateTime } from "./uiFormat";
import { usePollingResource } from "./usePollingResource";
import "./market-quote-panel.css";

type Quote = {
  ready: boolean;
  symbol: string;
  currency?: string | null;
  source?: string | null;
  last?: number | null;
  last_price_type?: string | null;
  last_updated_at?: string | null;
  trading_date?: string | null;
  session?: {
    open?: number | null;
    low?: number | null;
    high?: number | null;
    basis?: string | null;
  };
  last_close?: {
    price?: number | null;
    date?: string | null;
    source?: string | null;
    basis?: string | null;
  };
  volume?: {
    latest?: number | null;
    latest_date?: string | null;
    average_3m?: number | null;
    average_sessions?: number | null;
    latest_above_average?: boolean | null;
    unit?: string | null;
    basis?: string | null;
    source?: string | null;
    provisional?: boolean | null;
  };
  range_52w?: {
    low?: number | null;
    high?: number | null;
    sessions?: number | null;
    basis?: string | null;
  };
};

type Payload = {
  ready: boolean;
  symbols?: Record<string, Quote>;
  methodology?: {
    average_volume?: string;
    range_52w?: string;
    otec_session?: string;
    otec_close?: string;
  };
};

const AUTO_REFRESH_MS = 2 * 60 * 1000;

function price(value: number | null | undefined, currency?: string | null) {
  if (value == null || !Number.isFinite(value)) return "–";
  const formatted = value.toLocaleString("nb-NO", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  if (currency === "BRL") return `R$ ${formatted}`;
  if (currency === "NOK") return `${formatted} kr`;
  if (currency === "USD") return `US$ ${formatted}`;
  return formatted;
}

function volume(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "–";
  return Math.round(value).toLocaleString("nb-NO");
}

function sessionBasisLabel(quote: Quote) {
  if (quote.session?.basis === "EXCHANGE_SESSION_SUMMARY") return "Børssammendrag";
  if (quote.session?.basis === "OBSERVED_TRADES") return "Observerte Euronext-handler";
  if (quote.session?.basis === "CLOSE_ONLY") return "Kun sluttkurs lagret";
  return "Lagrede markedsdata";
}

function QuoteCard({ quote, title }: { quote?: Quote; title: string }) {
  if (!quote?.ready) {
    return (
      <article className="card marketQuoteCard marketQuoteUnavailable">
        <span className="label">{title}</span>
        <strong>Kursdata mangler</strong>
      </article>
    );
  }

  const currency = quote.currency;
  const latestAboveAverage = quote.volume?.latest_above_average;
  const yahooIntradayVolume =
    quote.symbol === "BMOB3" &&
    quote.volume?.provisional === true &&
    quote.volume?.source === "YAHOO_FINANCE";
  return (
    <article className="card marketQuoteCard">
      <div className="marketQuoteHeader">
        <div>
          <span className="label">{title}</span>
          <div className="marketQuotePrice">{price(quote.last, currency)}</div>
          <small>
            {quote.last_price_type === "CLOSE" ? "Siste sluttkurs" : "Siste handel"} ·{" "}
            {quote.source ?? "–"}
          </small>
        </div>
        <div className="marketQuoteUpdated">
          <span>
            Sist oppdatert:{" "}
            {quote.last_price_type === "CLOSE"
              ? "Tidspunkt for sluttkurs"
              : "Tidspunkt for siste handel"}
          </span>
          <strong>{formatDateTime(quote.last_updated_at)}</strong>
          <small>
            {quote.last_price_type === "CLOSE"
              ? `Kursdato ${formatDate(quote.trading_date)}`
              : "Oppdateres ved neste 30-minutters innhenting"}
          </small>
        </div>
      </div>

      <div className="marketQuoteStats">
        <div>
          <span>Åpning</span>
          <strong>{price(quote.session?.open, currency)}</strong>
        </div>
        <div>
          <span>Dagens lav</span>
          <strong>{price(quote.session?.low, currency)}</strong>
        </div>
        <div>
          <span>Dagens høy</span>
          <strong>{price(quote.session?.high, currency)}</strong>
        </div>
        <div>
          <span>Siste sluttkurs</span>
          <strong>{price(quote.last_close?.price, currency)}</strong>
          <small>{formatDate(quote.last_close?.date)}</small>
        </div>
        <div>
          <span>{yahooIntradayVolume ? "Dagens volum" : "Siste volum"}</span>
          <strong>{volume(quote.volume?.latest)}</strong>
          <small>{formatDate(quote.volume?.latest_date)}</small>
          {yahooIntradayVolume && <small>Foreløpig · Yahoo Finance</small>}
          {latestAboveAverage != null && (
            <small>
              {yahooIntradayVolume
                ? latestAboveAverage
                  ? "Høyere enn 3 mnd snitt hittil i dag"
                  : "Ikke høyere enn 3 mnd snitt hittil i dag"
                : latestAboveAverage
                  ? "Høyere enn 3 mnd snitt"
                  : "Ikke høyere enn 3 mnd snitt"}
            </small>
          )}
        </div>
        <div>
          <span>3 mnd snittvolum</span>
          <strong>{volume(quote.volume?.average_3m)}</strong>
          <small>{quote.volume?.average_sessions ?? 0} sesjoner</small>
        </div>
        <div className="marketQuoteRange">
          <span>52-ukers lav / høy</span>
          <strong>
            {price(quote.range_52w?.low, currency)} <i>→</i>{" "}
            {price(quote.range_52w?.high, currency)}
          </strong>
          <small>{quote.range_52w?.sessions ?? 0} handelssesjoner</small>
        </div>
      </div>

      <div className="marketQuoteFootnote">
        <span>{sessionBasisLabel(quote)}</span>
        {quote.symbol === "OTEC" && (
          <span>
            OTEC sjekkes hvert 30. minutt. Uendret tidspunkt betyr at Euronext
            ikke har rapportert en nyere handel.
          </span>
        )}
        {quote.symbol === "OTEC" &&
          quote.last_close?.basis === "COMPLETED_SESSION_LAST_TRADE" && (
            <span>OTEC sluttkurs = siste handel i siste fullførte Euronext-dag.</span>
          )}
        {quote.symbol === "BMOB3" && yahooIntradayVolume && (
          <span>
            Dagens volum er foreløpig fra Yahoo Finance. 3 mnd snittvolum bygges kun
            fra offisiell B3 COTAHIST.
          </span>
        )}
        {quote.symbol === "BMOB3" &&
          !yahooIntradayVolume &&
          (quote.volume?.average_sessions ?? 0) < 63 && (
            <span>BMOB3-volum bygges opp fra offisiell B3 COTAHIST.</span>
          )}
        {quote.symbol === "LIF" && (
          <span>
            Life360 bruker Yahoo Finance. Under ordinær NASDAQ-handel oppdateres
            kursen ved 30-minutters cron; etter stenging vises sluttkursen med
            NASDAQs ordinære stengetid.
          </span>
        )}
      </div>
    </article>
  );
}

export default function MarketQuotePanel() {
  const { data, refreshFailed: failed } = usePollingResource<Payload>(
    "/api/market/quotes",
    AUTO_REFRESH_MS,
    true,
  );

  return (
    <section className="marketQuoteSection">
      <div className="marketQuoteSectionHeader">
        <div>
          <span className="label">Markedsdata</span>
          <h2>Kurser og handelsdata</h2>
        </div>
        {failed && <span className="pill muted">Viser sist hentet</span>}
      </div>
      <div className="marketQuoteGrid">
        <QuoteCard quote={data?.symbols?.OTEC} title="OTEC" />
        <QuoteCard quote={data?.symbols?.BMOB3} title="Bemobi / BMOB3" />
        <QuoteCard quote={data?.symbols?.LIF} title="Life360 / LIF" />
      </div>
      {data?.methodology?.range_52w && (
        <p className="marketQuoteMethod">{data.methodology.range_52w}</p>
      )}
    </section>
  );
}