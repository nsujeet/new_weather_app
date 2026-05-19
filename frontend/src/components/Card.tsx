interface CardProps {
  title: string;
  children: React.ReactNode;
  className?: string;
}

export default function Card({ title, children, className = "" }: CardProps) {
  return (
    <div
      className={className}
      style={{
        background: "var(--wa-surface)",
        border: "1px solid var(--wa-border)",
        borderRadius: "12px",
        overflow: "hidden",
        marginBottom: "12px",
      }}
    >
      <div style={{
        padding: "10px 16px",
        borderBottom: "1px solid var(--wa-border)",
        background: "var(--wa-surface-2)",
      }}>
        <h2 style={{ fontSize: "12px", fontWeight: 700, color: "var(--wa-text-dim)", textTransform: "uppercase", letterSpacing: "0.06em", margin: 0 }}>
          {title}
        </h2>
      </div>
      <div style={{ padding: "16px" }}>{children}</div>
    </div>
  );
}
