import DataClassification, {
  type DataClassificationType,
} from "./DataClassification";

const classifications: Array<{
  type: DataClassificationType;
  description: string;
}> = [
  {
    type: "reported",
    description:
      "Tall som er direkte hentet fra selskap, børs eller annen identifisert ekstern kilde.",
  },
  {
    type: "calculated",
    description:
      "Tall som OtelloTracker matematisk beregner på bakgrunn av rapporterte eller markedsbaserte data.",
  },
  {
    type: "estimated",
    description:
      "Tall som bygger på antakelser om fremtidige forhold, scenarioer eller andre skjønnsmessige forutsetninger.",
  },
];

export default function MethodologyPage() {
  return (
    <article className="investorPage methodologyPage">
      <section className="card methodologyIntro">
        <span className="label">ÅPENHET</span>
        <h2>Metode og transparens</h2>
        <p>
          Her beskrives hvem som står bak OtelloTracker, hvilke interesser som
          finnes, og hvordan informasjonen på nettstedet skal forstås.
        </p>
      </section>

      <section className="card methodologySection">
        <h2>Om OtelloTracker</h2>
        <p>
          OtelloTracker er et uavhengig analyse- og informasjonsverktøy utviklet
          for å gjøre det enklere å følge Otello Corporation ASA og selskapets
          investering i Bemobi Mobile Tech S.A.
        </p>
        <p>
          Nettstedet er ikke tilknyttet, godkjent av eller utarbeidet på vegne
          av Otello Corporation ASA, Bemobi Mobile Tech S.A. eller deres
          rådgivere.
        </p>
        <p><strong>OtelloTracker er utviklet og drevet av Mads Kristensen.</strong></p>
      </section>

      <section className="card methodologySection methodologyConflict">
        <span className="label">INTERESSEKONFLIKT</span>
        <h2>Økonomisk interesse</h2>
        <p>
          Personen bak OtelloTracker eier aksjer i Otello Corporation ASA og
          har derfor en økonomisk interesse i utviklingen i selskapets aksjekurs
          og verdien av Otellos investering i Bemobi.
        </p>
        <p>
          Dette kan innebære en interessekonflikt som brukere av nettstedet bør
          være oppmerksomme på ved vurdering av analyser, beregninger og
          kommentarer på nettstedet.
        </p>
      </section>

      <section className="card methodologySection">
        <h2>Informasjonen på nettstedet</h2>
        <p>
          OtelloTracker benytter offentlig tilgjengelig informasjon fra blant
          annet selskapsrapporter, børsmeldinger, markedsdata og andre offentlig
          tilgjengelige kilder.
        </p>
        <p>
          Nettstedet kan også inneholde egne beregninger, modeller, estimater,
          scenarioanalyser og vurderinger.
        </p>
        <p>
          Selv om det legges vekt på korrekt informasjon, kan data være
          forsinkede, ufullstendige eller inneholde feil. Brukere bør kontrollere
          vesentlig informasjon mot originalkilden.
        </p>
      </section>

      <section className="card methodologySection">
        <h2>Ikke investeringsrådgivning</h2>
        <p>
          Informasjonen på OtelloTracker er generell informasjon og analyse og
          er ikke personlig investeringsrådgivning.
        </p>
        <p>
          Innholdet tar ikke hensyn til den enkelte brukers økonomiske situasjon,
          investeringsmål, risikotoleranse eller andre individuelle forhold.
        </p>
        <p>
          Investeringer i aksjer innebærer risiko, og historisk avkastning er
          ingen garanti for fremtidig avkastning.
        </p>
      </section>

      <section className="card methodologySection">
        <h2>Hvordan tall klassifiseres</h2>
        <div className="classificationGrid">
          {classifications.map((classification) => (
            <div key={classification.type}>
              <DataClassification type={classification.type} />
              <p>{classification.description}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="card methodologySection">
        <h2>Kilder og oppdateringer</h2>
        <p>
          Kilder skal så langt det er praktisk mulig fremgå ved det aktuelle
          datapunktet, analysen eller beregningen.
        </p>
        <p>
          Markedsdata og beregninger kan ha forskjellig oppdateringsfrekvens.
          Tidspunkt eller dato for siste oppdatering skal derfor fremgå der dette
          er relevant.
        </p>
        <p>
          Ved motstrid mellom informasjon på OtelloTracker og informasjon fra
          originalkilden skal originalkilden legges til grunn.
        </p>
      </section>

      <section className="card methodologySection">
        <h2>Endringer i metodikk</h2>
        <p>
          Beregninger, modeller og metodikk på OtelloTracker kan endres over tid
          når datagrunnlaget forbedres eller nettstedet videreutvikles.
        </p>
        <p>
          Ved vesentlige metodiske endringer bør dette fremgå på den aktuelle
          siden eller i denne metodebeskrivelsen.
        </p>
      </section>
    </article>
  );
}
