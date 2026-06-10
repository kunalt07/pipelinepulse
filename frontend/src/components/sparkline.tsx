"use client";

type Props = {
  values: number[];
  width?: number;
  height?: number;
  color?: string;
  fillColor?: string;
};

export function Sparkline({
  values,
  width = 80,
  height = 24,
  color = "hsl(var(--success))",
  fillColor,
}: Props) {
  if (values.length < 2) {
    return <div style={{ width, height }} className="opacity-30" />;
  }

  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;

  const stepX = width / (values.length - 1);
  const points = values.map((v, i) => {
    const x = i * stepX;
    const y = height - ((v - min) / range) * (height - 2) - 1;
    return [x, y] as const;
  });

  const linePath = points
    .map(([x, y], i) => `${i === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`)
    .join(" ");

  const areaPath = `${linePath} L ${width} ${height} L 0 ${height} Z`;
  const gradientId = `spark-${Math.random().toString(36).slice(2, 9)}`;
  const fill = fillColor ?? color;

  return (
    <svg width={width} height={height} className="block">
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={fill} stopOpacity="0.7" />
          <stop offset="100%" stopColor={fill} stopOpacity="0.15" />
        </linearGradient>
      </defs>
      <path d={areaPath} fill={`url(#${gradientId})`} />
      <path d={linePath} stroke={color} strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
