import { useEffect, useState } from 'react';

interface Props {
  label: string;
  value: string | number;
  icon?: string;
}

function animateValue(
  start: number,
  end: number,
  duration: number,
  setter: (v: number) => void,
  decimals: number
) {
  const startTime = performance.now();
  function tick(now: number) {
    const elapsed = now - startTime;
    const progress = Math.min(elapsed / duration, 1);
    const eased = 1 - Math.pow(1 - progress, 2);
    const current = start + (end - start) * eased;
    const rounded = decimals > 0 ? Math.round(current * Math.pow(10, decimals)) / Math.pow(10, decimals) : Math.round(current);
    setter(rounded);
    if (progress < 1) requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}

export default function KpiCard({ label, value, icon }: Props) {
  const strVal = String(value);
  const num = parseFloat(strVal);
  const isNumeric = !Number.isNaN(num);
  const decimals = strVal.includes('.') ? (strVal.split('.')[1]?.length ?? 3) : 0;
  const [display, setDisplay] = useState(0);

  useEffect(() => {
    if (!isNumeric) return;
    animateValue(0, num, 600, setDisplay, decimals);
  }, [value]);

  const displayStr = isNumeric
    ? decimals > 0
      ? display.toFixed(decimals)
      : String(Math.round(display))
    : strVal;

  return (
    <div
      style={{
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: 8,
        padding: 16,
        textAlign: 'center',
        animation: 'fadeUp 0.3s ease both',
      }}
    >
      {icon && <div style={{ fontSize: 22, marginBottom: 4 }}>{icon}</div>}
      <div
        style={{
          fontSize: 26,
          fontWeight: 800,
          color: 'var(--accent)',
          fontFamily: "'JetBrains Mono', 'Fira Code', Consolas, monospace",
        }}
      >
        {displayStr}
      </div>
      <div
        style={{
          fontSize: 10,
          color: 'var(--text2)',
          textTransform: 'uppercase',
          letterSpacing: 1.5,
          marginTop: 4,
        }}
      >
        {label}
      </div>
    </div>
  );
}
