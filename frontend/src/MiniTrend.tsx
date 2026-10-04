type MiniTrendProps = {
  values: readonly number[];
  className?: string;
};

const WIDTH = 120;
const HEIGHT = 30;
const PADDING = 2;

export default function MiniTrend({ values, className = "" }: MiniTrendProps) {
  const validValues = values.filter(Number.isFinite);
  if (validValues.length < 2) return null;

  const minimum = Math.min(...validValues);
  const maximum = Math.max(...validValues);
  const range = maximum - minimum;
  const plotHeight = HEIGHT - PADDING * 2;
  const points = validValues.map((value, index) => {
    const x = PADDING + (index / (validValues.length - 1)) * (WIDTH - PADDING * 2);
    const y = range === 0
      ? HEIGHT / 2
      : PADDING + ((maximum - value) / range) * plotHeight;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  }).join(" ");

  return (
    <svg
      aria-hidden="true"
      className={`miniTrend ${className}`.trim()}
      focusable="false"
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
    >
      <polyline points={points} />
    </svg>
  );
}
