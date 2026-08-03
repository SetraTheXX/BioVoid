interface ErrorNoticeProps {
  message: string;
  correlationId?: string | null;
  compact?: boolean;
  detail?: string;
  className?: string;
}

export default function ErrorNotice({
  message,
  correlationId,
  compact = false,
  detail,
  className,
}: ErrorNoticeProps) {
  return (
    <div
      role="alert"
      className={className}
      style={{
        padding: compact ? 8 : 12,
        background: 'rgba(255,68,85,.1)',
        border: '1px solid var(--danger)',
        borderRadius: 6,
        color: 'var(--danger)',
        fontSize: 12,
      }}
    >
      <strong>Request failed:</strong> {message}
      {detail && <div style={{ marginTop: 4, color: 'var(--text2)' }}>{detail}</div>}
      {correlationId && (
        <div style={{ marginTop: 4, color: 'var(--text2)', fontSize: 10 }}>
          Request ID: <code>{correlationId}</code>
        </div>
      )}
    </div>
  );
}
