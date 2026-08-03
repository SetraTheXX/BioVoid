import { useEffect, useMemo, useRef, useState } from 'react';
import type { PluginUIContext } from 'molstar/lib/mol-plugin-ui/context.js';
import { Vec3 } from 'molstar/lib/mol-math/linear-algebra.js';
import { api } from '../services/api';
import type { Pocket } from '../types/api';
import 'molstar/lib/mol-plugin-ui/skin/dark.scss';

interface MolstarSpikeProps {
  pdbId?: string;
  runId?: string;
  pockets: Pocket[];
}

function pocketKey(pocket: Pocket, index: number): string {
  return String(pocket.id ?? pocket.pocket_id ?? pocket.rank ?? index + 1);
}

function pocketLabel(pocket: Pocket, index: number): string {
  return `P${pocketKey(pocket, index)}`;
}

export default function MolstarSpike({ pdbId, runId, pockets }: MolstarSpikeProps) {
  const targetRef = useRef<HTMLDivElement | null>(null);
  const pluginRef = useRef<PluginUIContext | null>(null);
  const [selectedKey, setSelectedKey] = useState<string>('');
  const [phase, setPhase] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle');
  const [error, setError] = useState<string | null>(null);

  const focusablePockets = useMemo(
    () => pockets.filter((pocket) => pocket.center?.length === 3),
    [pockets],
  );
  const selectedPocket = useMemo(
    () =>
      focusablePockets.find((pocket, index) => pocketKey(pocket, index) === selectedKey) ??
      focusablePockets[0],
    [focusablePockets, selectedKey],
  );

  useEffect(() => {
    const target = targetRef.current;
    if (!target || !pdbId || !runId) {
      setPhase('idle');
      return;
    }

    const structureId = pdbId;
    const analysisRunId = runId;
    const controller = new AbortController();
    let disposed = false;

    async function loadStructure() {
      setPhase('loading');
      setError(null);
      try {
        const structureText = await api.proteinStructure(structureId, analysisRunId, controller.signal);
        if (disposed) return;

        const [{ createPluginUI }, { renderReact18 }, { DefaultPluginUISpec }, { Color }] =
          await Promise.all([
            import('molstar/lib/mol-plugin-ui/index.js'),
            import('molstar/lib/mol-plugin-ui/react18.js'),
            import('molstar/lib/mol-plugin-ui/spec.js'),
            import('molstar/lib/mol-util/color/index.js'),
          ]);
        if (disposed || !targetRef.current) return;

        const plugin = await createPluginUI({
          target: targetRef.current,
          render: renderReact18,
          spec: DefaultPluginUISpec(),
        });
        if (disposed) {
          plugin.dispose();
          return;
        }
        pluginRef.current = plugin;

        const data = await plugin.builders.data.rawData({
          data: structureText,
          label: `${structureId.toUpperCase()} prepared structure`,
        });
        const trajectory = await plugin.builders.structure.parseTrajectory(data, 'pdb');
        await plugin.builders.structure.hierarchy.applyPreset(trajectory, 'default');
        plugin.canvas3d?.setProps({
          renderer: { backgroundColor: Color(0x101016) },
        });
        if (!disposed) setPhase('ready');
      } catch (loadError: unknown) {
        if (controller.signal.aborted || disposed) return;
        setError(loadError instanceof Error ? loadError.message : '3D structure could not be loaded');
        setPhase('error');
      }
    }

    void loadStructure();
    return () => {
      disposed = true;
      controller.abort();
      pluginRef.current?.dispose();
      pluginRef.current = null;
    };
  }, [pdbId, runId]);

  useEffect(() => {
    const center = selectedPocket?.center;
    const canvas3d = pluginRef.current?.canvas3d;
    if (phase !== 'ready' || !center || center.length !== 3 || !canvas3d) return;

    const target = Vec3.create(center[0], center[1], center[2]);
    const radius = Math.max(6, Math.cbrt(selectedPocket.volume ?? 100) * 2);
    canvas3d.camera.focus(target, radius, 250);
  }, [phase, selectedPocket]);

  const selectedIndex = selectedPocket ? focusablePockets.indexOf(selectedPocket) : -1;
  const center = selectedPocket?.center;

  return (
    <section className="molstar-spike" aria-label="Molecular 3D viewer spike">
      <div className="molstar-spike-header">
        <div>
          <div className="molstar-spike-title">Molecular 3D Workbench Spike</div>
          <div className="molstar-spike-subtitle">
            Prepared structure only; pocket coordinates are BioVoid measurements.
          </div>
        </div>
        {focusablePockets.length > 0 && (
          <label className="molstar-pocket-select">
            <span>Focus pocket</span>
            <select
              aria-label="Focus pocket in molecular viewer"
              value={selectedPocket ? pocketKey(selectedPocket, selectedIndex) : ''}
              onChange={(event) => setSelectedKey(event.target.value)}
            >
              {focusablePockets.map((pocket, index) => (
                <option key={pocketKey(pocket, index)} value={pocketKey(pocket, index)}>
                  {pocketLabel(pocket, index)}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      <div className="molstar-spike-meta" aria-live="polite">
        <span>{pdbId?.toUpperCase() ?? 'No structure'} · {phase}</span>
        {center && (
          <span>
            {selectedPocket ? pocketLabel(selectedPocket, selectedIndex) : 'Pocket'} center&nbsp;
            ({center.map((value) => value.toFixed(2)).join(', ')} Å)
          </span>
        )}
      </div>
      {!pdbId || !runId ? (
        <div className="molstar-spike-empty">A completed analysis run is required to open the prepared structure.</div>
      ) : (
        <div ref={targetRef} className="molstar-spike-canvas" role="img" aria-label="Interactive molecular structure viewer" />
      )}
      {phase === 'loading' && <div className="molstar-spike-status">Loading the verified prepared structure…</div>}
      {phase === 'error' && <div className="molstar-spike-error">Viewer unavailable: {error}</div>}
      <div className="molstar-spike-footnote">
        Experimental UI spike. It does not change canonical ranking, scores, or evaluator inputs.
      </div>
    </section>
  );
}
