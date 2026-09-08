export type DataClassificationType = "reported" | "calculated" | "estimated";

const labels: Record<DataClassificationType, string> = {
  reported: "Rapportert",
  calculated: "Beregnet",
  estimated: "Estimert",
};

export default function DataClassification({
  type,
}: {
  type: DataClassificationType;
}) {
  return (
    <span className={`dataClassification dataClassification--${type}`}>
      {labels[type]}
    </span>
  );
}
