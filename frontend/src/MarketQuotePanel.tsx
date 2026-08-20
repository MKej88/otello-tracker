import { useEffect, useState } from "react";
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
  };
  volume?: {
    latest?: number | null;
    latest_date?: string | null;
    average_20d?: number | null;
    average_sessions?: number | null;
    unit?: string | null;
    basis?: string | null;
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
  };
};

const AUTO_REFRESH_MS = 2 * 60 * 1000;

function price(value: number | null | undefined, currency?: string | null) {
  if (value == null || !Number.isFinite(value)) return "–";
  const formatted = value.toLocaleString("nb-NO", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return currency === "BRL" ? `R$ ${formatted}` : currency === "NOK" ? `${formatted} kr` : formatted;
}

function volume(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "–";
  return Math.round(value).toLocaleString("nb-NO");
}

function shortDate(input?: string | null) {
  if (!input) return "–";
  const [year, month, day] = input.slice(0, 10).split("-");
  return year && month && day ? `${day}.${month}.${year}` : input;
}

function updated(input?: string | null) {
  if (!input) return "–";
  const parsed = new Date(input);
  if (Number.isNaN(parsed.getTime())) return input;
  return parsed.toLocaleString("nb-NO", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Europe/Oslo"
  });
}

function sessionBasisLabel(quote: Quote) {
  if (quote.session?.basis === "EXCHANGE_SESSION_SUMMARY") return "Børssammendrag";
  if (quote.session?.basis === "OBSERVED_TRADES") return "Observerte Euronext-handler";
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
  return (
    <article className="card marketQuoteCard">
      <div className="marketQuoteHeader">
        <div>
          <span className="label">{title}</span>
          <div className="marketQuotePrice">{price(quote.last, currency)}</div>
          <small>{quote.last_price_type === "CLOSE" ? "Siste sluttkurs" : "Siste handel"} · {quote.source ?? "–"}</small>
        </div>
        <div className="marketQuoteUpdated">
          <span>Sist oppdatert</span>
          <strong>{updated(quote.last_updated_at)}</strong>
          <small>Handelsdato {shortDate(quote.trading_date)}</small>
        </div>
      </div>

      <div className="marketQuoteStats">
        <div><span>Åpning</span><strong>{price(quote.session?.open, currency)}</strong></div>
        <div><span>Dagens lav</span><strong>{price(quote.session?.low, currency)}</strong></div>
        <div><span>Dagens høy</span><strong>{price(quote.session?.high, currency)}</strong></div>
        <div>
          <span>Siste sluttkurs</span>
          <strong>{price(quote.last_close?.price, currency)}</strong>
          <small>{shortDate(quote.last_close?.date)}</small>
        </div>
        <div>
          <span>Siste volum</span>
          <strong>{volume(quote.volume?.latest)}</strong>
          <small>{shortDate(quote.volume?.latest_date)}</small>
        </div>
        <div>
          <span>Snittvolum</span>
          <strong>{volume(quote.volume?.average_20d)}</strong>
          <small>{quote.volume?.average_sessions ?? 0} sesjoner</small>
        </div>
        <div className="marketQuoteRange">
          <span>52-ukers lav / høy</span>
          <strong>{price(quote.range_52w?.low, currency)} <i>→</i> {price(quote.range_52w?.high, currency)}</strong>
          <small>{quote.range_52w?.sessions ?? 0} handelssesjoner</small>
        </div>
      </div>

      <div className="marketQuoteFootnote">
        <span>{sessionBasisLabel(quote)}</span>
        {quote.symbol === "BMOB3" && (quote.volume?.average_sessions ?? 0) < 20 && (
          <span>BMOB3-volum bygges opp fra offisiell B3 COTAHIST.</span>
        )}
      </div>
    </article>
  );
}

export default function MarketQuotePanel() {
  const [data, setData] = useState<Payload | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    const load = () => {
      fetch("/api/market/quotes")
        .then((response) => {
          if (!response.ok) throw new Error("Kurs-API feilet");
          return response.json() as Promise<Payload>;
        })
        .then((payload) => {
          if (!active) return;
          setData(payload);
          setFailed(false);
        })
        .catch(() => {
          if (!active) return;
          setFailed(true);
        });
    };
    load();
    const timer = window.setInterval(load, AUTO_REFRESH_MS);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  return (
    <section className="marketQuoteSection">
      <div className="marketQuoteSectionHeader">
        <div><span className="label">Markedsdata</span><h2>Kurser og handelsdata</h2></div>
        {failed && <span className="pill muted">Viser sist hentet</span>}
      </div>
      <div className="marketQuoteGrid">
        <QuoteCard quote={data?.symbols?.OTEC} title="OTEC" />
        <QuoteCard quote={data?.symbols?.BMOB3} title="Bemobi / BMOB3" />
      </div>
      {data?.methodology?.range_52w && <p className="marketQuoteMethod">{data.methodology.range_52w}</p>}
    </section>
  );
}
