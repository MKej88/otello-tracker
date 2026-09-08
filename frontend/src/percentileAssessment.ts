export type PercentileAssessment = {
  label: string;
  explanation: string;
};

const missingAssessment = (periodLabel: string): PercentileAssessment => ({
  label: "Historisk plassering mangler",
  explanation: `Kan ikke vurderes for perioden ${periodLabel}.`,
});

export function percentileAssessment(
  percentile?: number | null,
  periodLabel = "valgt periode",
): PercentileAssessment {
  if (
    percentile == null
    || !Number.isFinite(percentile)
    || percentile < 0
    || percentile > 100
  ) {
    return missingAssessment(periodLabel);
  }

  const roundedPercentile = Math.round(percentile);

  if (percentile <= 10) {
    return {
      label: "Svært lav rabatt",
      explanation: `Rabatten er blant de 10 % laveste i perioden ${periodLabel}.`,
    };
  }
  if (percentile <= 25) {
    return {
      label: "Lav historisk rabatt",
      explanation: `Bare ${roundedPercentile} % av observasjonene i perioden ${periodLabel} har hatt lavere rabatt.`,
    };
  }
  if (percentile <= 40) {
    return {
      label: "Under normalen",
      explanation: `Rabatten er lavere enn normalt i perioden ${periodLabel}.`,
    };
  }
  if (percentile <= 60) {
    return {
      label: "Rundt normalen",
      explanation: `Rabatten ligger omtrent midt i det historiske intervallet for perioden ${periodLabel}.`,
    };
  }
  if (percentile <= 75) {
    return {
      label: "Over normalen",
      explanation: `Rabatten er høyere enn normalt i perioden ${periodLabel}.`,
    };
  }
  if (percentile <= 90) {
    return {
      label: "Høy historisk rabatt",
      explanation: `Bare ${Math.round(100 - percentile)} % av observasjonene i perioden ${periodLabel} har hatt høyere rabatt.`,
    };
  }
  return {
    label: "Svært høy rabatt",
    explanation: `Rabatten er blant de 10 % høyeste i perioden ${periodLabel}.`,
  };
}
