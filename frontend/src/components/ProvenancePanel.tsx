import { useState } from 'react';
import type { AnalysisResult, JsonObject, PreparationSummary } from '../types/api';

interface ProvenancePanelProps {
  runId?: string;
  preparedSha256?: string;
  analysisContract?: AnalysisResult['analysis_contract'];
  preparation?: PreparationSummary;
  provenance?: JsonObject;
  rankingContract?: string;
  compact?: boolean;
}

function valueOrUnknown(value: string | undefined | null): string {
  return value?.trim() || 'unknown';
}

function stringValue(value: unknown): string {
  return typeof value === 'string' && value.trim() ? value : 'unknown';
}

function shortHash(value: string | undefined): string {
  if (!value) return 'unknown';
  return value.length > 20 ? `${value.slice(0, 12)}…${value.slice(-8)}` : value;
}

export default function ProvenancePanel({
  runId,
  preparedSha256,
  analysisContract,
  preparation,
  provenance,
  rankingContract,
  compact = false,
}: ProvenancePanelProps) {
  const [copied, setCopied] = useState<string | null>(null);
  const source = preparation?.source;
  const rows = [
    { label: 'Run ID', value: valueOrUnknown(runId), copyValue: runId },
    {
      label: 'Source',
      value: valueOrUnknown(source?.provider ?? preparation?.source_provider),
    },
    {
      label: 'Representation',
      value: valueOrUnknown(source?.representation ?? preparation?.representation),
    },
    {
      label: 'Assembly',
      value: valueOrUnknown(source?.assembly_id ?? preparation?.assembly_id),
    },
    { label: 'Chains', value: preparation?.selected_chains?.join(', ') || 'automatic/manifest' },
    {
      label: 'Preparation policy',
      value: valueOrUnknown(
        analysisContract?.preparation_policy_version ??
          preparation?.preparation_policy_version ??
          preparation?.policy_version,
      ),
    },
    { label: 'Detector', value: valueOrUnknown(analysisContract?.detector_version) },
    { label: 'Scoring contract', value: valueOrUnknown(analysisContract?.scoring_contract_version) },
    { label: 'Ranking contract', value: valueOrUnknown(rankingContract ?? analysisContract?.ranking_contract) },
    {
      label: 'Verified benchmark',
      value: stringValue(provenance?.verified_benchmark_manifest) === 'unknown'
        ? 'not recorded'
        : stringValue(provenance?.verified_benchmark_manifest),
    },
    {
      label: 'Input SHA-256',
      value: shortHash(stringValue(provenance?.input_sha256 ?? preparation?.hashes?.input_sha256)),
      copyValue: stringValue(provenance?.input_sha256 ?? preparation?.hashes?.input_sha256),
    },
    {
      label: 'Prepared SHA-256',
      value: shortHash(preparedSha256 ?? stringValue(provenance?.prepared_sha256 ?? preparation?.hashes?.prepared_sha256)),
      copyValue: preparedSha256 ?? stringValue(provenance?.prepared_sha256 ?? preparation?.hashes?.prepared_sha256),
    },
    {
      label: 'Preparation config SHA-256',
      value: shortHash(stringValue(provenance?.preparation_config_sha256)),
      copyValue: stringValue(provenance?.preparation_config_sha256),
    },
    {
      label: 'Detector config SHA-256',
      value: shortHash(stringValue(provenance?.detector_config_sha256)),
      copyValue: stringValue(provenance?.detector_config_sha256),
    },
    {
      label: 'Code identity SHA-256',
      value: shortHash(stringValue(provenance?.code_identity_sha256)),
      copyValue: stringValue(provenance?.code_identity_sha256),
    },
    {
      label: 'Environment identity SHA-256',
      value: shortHash(stringValue(provenance?.environment_identity_sha256)),
      copyValue: stringValue(provenance?.environment_identity_sha256),
    },
  ];

  async function copyValue(label: string, value?: string) {
    if (!value || value === 'unknown' || !navigator.clipboard) return;
    try {
      await navigator.clipboard.writeText(value);
      setCopied(label);
      window.setTimeout(() => setCopied(null), 1200);
    } catch {
      setCopied(null);
    }
  }

  return (
    <section
      aria-label="Run provenance"
      style={{
        border: '1px solid var(--border)',
        background: 'var(--surface2)',
        padding: compact ? 10 : 12,
        fontSize: 11,
      }}
    >
      <div style={{ color: 'var(--accent)', fontWeight: 700, marginBottom: 8 }}>Run provenance</div>
      <dl className="provenance-grid">
        {rows.map(({ label, value, copyValue: rawValue }) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd title={rawValue && rawValue !== 'unknown' ? rawValue : value}>
              <span>{value}</span>
              {rawValue && rawValue !== 'unknown' && (
                <button
                  type="button"
                  aria-label={`Copy ${label}`}
                  title={`Copy ${label}`}
                  onClick={() => void copyValue(label, rawValue)}
                  style={{
                    marginLeft: 6,
                    padding: '1px 4px',
                    border: '1px solid var(--border)',
                    background: 'transparent',
                    color: 'var(--text2)',
                    borderRadius: 4,
                    fontSize: 10,
                    cursor: 'pointer',
                  }}
                >
                  {copied === label ? 'ok' : 'copy'}
                </button>
              )}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
