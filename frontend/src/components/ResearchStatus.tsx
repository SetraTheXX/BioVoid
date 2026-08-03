import type { MotionSummary } from '../types/api';

interface ResearchStatusProps {
  validationStatus?: string;
  canonicalEligible?: boolean;
  motionStatus?: string;
  motion?: MotionSummary;
  compact?: boolean;
}

function statusCopy(validationStatus: string | undefined, canonicalEligible: boolean | undefined) {
  if (canonicalEligible) {
    return {
      label: 'Pipeline canonical eligibility: eligible',
      tone: 'var(--accent)',
      detail: 'Eligible within the recorded BioVoid pipeline contract; this is not experimental validation.',
    };
  }
  if (validationStatus === 'recovery_unvalidated' || validationStatus === 'unknown') {
    return {
      label: 'Research status: unvalidated prototype output',
      tone: 'var(--warn)',
      detail: 'This run is not a benchmark result or experimental confirmation.',
    };
  }
  return {
    label: `Research status: ${validationStatus ?? 'unknown'}`,
    tone: 'var(--warn)',
    detail: 'Read the run provenance before interpreting this output.',
  };
}

export default function ResearchStatus({
  validationStatus,
  canonicalEligible,
  motionStatus,
  motion,
  compact = false,
}: ResearchStatusProps) {
  const copy = statusCopy(validationStatus, canonicalEligible);
  const resolvedMotionStatus = motionStatus ?? motion?.status ?? 'NOT_ELIGIBLE';
  const qualityCounts = motion?.quality_counts ?? {};
  const accepted = motion?.frames_accepted ?? qualityCounts.ACCEPTED;
  const acceptedWithWarnings =
    motion?.frames_accepted_with_warnings ?? qualityCounts.ACCEPTED_WITH_WARNINGS;
  const rejected = motion?.frames_rejected ?? qualityCounts.REJECTED;
  const hasFrameEvidence =
    [accepted, acceptedWithWarnings, rejected].some((value) => typeof value === 'number');

  return (
    <div
      role="status"
      aria-label="Research validation status"
      style={{
        padding: compact ? '8px 10px' : '12px 14px',
        border: '1px solid var(--border)',
        background: 'var(--surface2)',
        color: copy.tone,
        fontSize: compact ? 11 : 12,
      }}
    >
      <strong>{copy.label}</strong>
      <div style={{ marginTop: 4, color: 'var(--text2)', fontSize: 11 }}>{copy.detail}</div>
      <div style={{ marginTop: 6, color: 'var(--warn)', fontSize: 11 }}>
        Motion layer: {resolvedMotionStatus}; it does not change the canonical ranking.
      </div>
      <div style={{ marginTop: 4, color: 'var(--text2)', fontSize: 11 }}>
        Frame quality:{' '}
        {resolvedMotionStatus === 'NOT_ELIGIBLE'
          ? 'not run'
          : hasFrameEvidence
            ? `accepted ${accepted ?? 0}, warnings ${acceptedWithWarnings ?? 0}, rejected ${rejected ?? 0}`
          : 'not recorded'}
      </div>
    </div>
  );
}
