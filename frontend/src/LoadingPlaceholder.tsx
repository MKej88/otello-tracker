type LoadingPlaceholderProps = {
  variant?: "text" | "number" | "content";
  label: string;
  className?: string;
};

export default function LoadingPlaceholder({
  variant = "content",
  label,
  className = "",
}: LoadingPlaceholderProps) {
  const classes = ["loadingPlaceholder", `loadingPlaceholder--${variant}`, className]
    .filter(Boolean)
    .join(" ");

  return (
    <span className={classes} aria-busy="true" role="status">
      <span className="loadingPlaceholderShape" aria-hidden="true" />
      <span className="visuallyHidden">{label}</span>
    </span>
  );
}
