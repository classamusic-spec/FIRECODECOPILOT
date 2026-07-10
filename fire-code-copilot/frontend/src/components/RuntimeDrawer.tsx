/**
 * RuntimeDrawer — explicit local model lifecycle controls.
 *
 * Selecting a card stages the choice only. The user must confirm "Load selected"
 * before oMLX is started or any generator weights are loaded. Stopping releases the
 * managed oMLX service and its model memory.
 */
import { useEffect, useState } from "react";
import {
  ApiError,
  getRuntimeStatus,
  loadRuntimeModel,
  startRuntime,
  stopRuntime,
  type RuntimeModel,
  type RuntimeStatus,
} from "../lib/api";
import Drawer from "./Drawer";
import { CheckIcon, SparkIcon, StopIcon, WarningIcon } from "./icons";

interface Props {
  open: boolean;
  onClose: () => void;
  onRuntimeChange: (running: boolean, activeModel: string, message: string) => void;
}

function readableError(error: unknown): string {
  return error instanceof ApiError ? error.message : "Could not update the local model runtime.";
}

export default function RuntimeDrawer({ open, onClose, onRuntimeChange }: Props) {
  const [status, setStatus] = useState<RuntimeStatus | null>(null);
  const [selected, setSelected] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmLoad, setConfirmLoad] = useState(false);
  const [confirmStop, setConfirmStop] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = async () => {
    const next = await getRuntimeStatus();
    setStatus(next);
    setSelected((current) => current || next.active_model || next.models[0]?.id || "");
    return next;
  };

  useEffect(() => {
    if (!open) return;
    setError(null);
    setConfirmLoad(false);
    setConfirmStop(false);
    refresh().catch((e) => setError(readableError(e)));
  }, [open]);

  const selectedModel = status?.models.find((model) => model.id === selected) ?? null;

  async function handleStart() {
    setBusy(true);
    setError(null);
    try {
      await startRuntime();
      const next = await refresh();
      onRuntimeChange(true, next.active_model, "Local model server started. Choose a model, then load it explicitly.");
    } catch (e) {
      setError(readableError(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleLoad() {
    if (!selectedModel) return;
    if (!confirmLoad) {
      setConfirmLoad(true);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await loadRuntimeModel(selectedModel.id);
      const next = await refresh();
      setConfirmLoad(false);
      onRuntimeChange(true, result.active_model || next.active_model, result.message || `${selectedModel.label} is ready for new questions.`);
    } catch (e) {
      setError(readableError(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleStop() {
    if (!confirmStop) {
      setConfirmStop(true);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await stopRuntime();
      const next = await refresh();
      setConfirmStop(false);
      onRuntimeChange(false, next.active_model, result.message || "Local model server stopped.");
    } catch (e) {
      setError(readableError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Drawer
      open={open}
      onClose={onClose}
      label="Local model runtime"
      header={
        <>
          <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-navy-800 text-coral-400 ring-1 ring-white/10">
            <SparkIcon className="h-4 w-4" />
          </span>
          <div className="leading-tight">
            <h2 className="text-[15px] font-semibold tracking-tight text-white">Research engine</h2>
            <p className="text-xs text-steel-400">Select first, then explicitly load a local generator.</p>
          </div>
        </>
      }
    >
      <div className="space-y-5">
        <section className="glass-inset p-3">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-sm font-semibold text-white">Local model server</p>
              <p className="mt-0.5 text-xs text-steel-400">
                {status?.running ? "Online — models remain unloaded until you load one." : "Offline — no model memory is in use."}
              </p>
            </div>
            <span className={"inline-flex items-center gap-1.5 rounded-full border px-2 py-1 text-[10px] font-semibold uppercase tracking-wider " + (status?.running ? "border-verified-500/30 bg-verified-500/10 text-verified-700" : "border-critical-200 bg-critical-50 text-critical-700")}>
              <span className={"h-1.5 w-1.5 rounded-full " + (status?.running ? "bg-verified-500" : "bg-critical-600")} />
              {status?.running ? "Online" : "Offline"}
            </span>
          </div>
          {!status?.running && (
            <button
              type="button"
              onClick={handleStart}
              disabled={busy}
              className="mt-3 inline-flex items-center gap-2 rounded-lg border border-coral-500/40 bg-coral-500/10 px-3 py-2 text-xs font-semibold text-coral-100 transition hover:bg-coral-500/20 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <SparkIcon className="h-3.5 w-3.5" />
              Start local server
            </button>
          )}
        </section>

        <section>
          <div className="flex items-end justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold text-white">Model picker</h3>
              <p className="mt-1 text-xs leading-relaxed text-steel-400">Picking a card does not allocate memory. Loading is a separate, deliberate action.</p>
            </div>
          </div>
          <div className="mt-3 space-y-2" role="radiogroup" aria-label="Model to load">
            {(status?.models ?? []).map((model) => <ModelOption key={model.id} model={model} selected={model.id === selected} onSelect={() => { setSelected(model.id); setConfirmLoad(false); }} />)}
          </div>
        </section>

        {selectedModel && (
          <section className="rounded-xl border border-coral-500/25 bg-coral-500/[0.07] p-3">
            <div className="flex items-start gap-2 text-sm text-coral-100">
              <WarningIcon className="mt-0.5 h-4 w-4 shrink-0 text-coral-300" />
              <p><strong>{selectedModel.label}</strong> uses about {selectedModel.memory_gb.toFixed(1)} GB when loaded. The server stays idle until you confirm this action.</p>
            </div>
            <button
              type="button"
              onClick={handleLoad}
              disabled={busy || !selectedModel.available}
              className="mt-3 inline-flex items-center gap-2 rounded-lg bg-coral-500 px-3 py-2 text-xs font-semibold text-white shadow-glow-sm transition hover:bg-coral-400 disabled:cursor-not-allowed disabled:bg-steel-700 disabled:text-steel-400 disabled:shadow-none"
            >
              {confirmLoad ? <CheckIcon className="h-3.5 w-3.5" /> : <SparkIcon className="h-3.5 w-3.5" />}
              {confirmLoad ? `Confirm load ${selectedModel.label}` : `Load ${selectedModel.label}`}
            </button>
            {!selectedModel.available && <p className="mt-2 text-xs text-critical-700">This model is not present in the current oMLX model directory.</p>}
          </section>
        )}

        <section className="border-t border-white/10 pt-4">
          <h3 className="text-sm font-semibold text-white">Stop server</h3>
          <p className="mt-1 text-xs leading-relaxed text-steel-400">Stops managed oMLX and releases every loaded model from memory. The desktop app also requests this shutdown when it quits.</p>
          <button
            type="button"
            onClick={handleStop}
            disabled={busy || !status?.running}
            className="mt-3 inline-flex items-center gap-2 rounded-lg border border-critical-200 bg-critical-50 px-3 py-2 text-xs font-semibold text-critical-700 transition hover:bg-critical-600/15 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <StopIcon className="h-3.5 w-3.5" />
            {confirmStop ? "Confirm stop local server" : "Stop local server"}
          </button>
        </section>

        {error && <p role="alert" className="text-xs leading-relaxed text-critical-700">{error}</p>}
      </div>
    </Drawer>
  );
}

function ModelOption({ model, selected, onSelect }: { model: RuntimeModel; selected: boolean; onSelect: () => void }) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onSelect}
      className={"w-full rounded-xl border p-3 text-left transition " + (selected ? "border-coral-500/45 bg-coral-500/[0.10] shadow-glow-sm" : "border-white/10 bg-white/[0.03] hover:border-white/20 hover:bg-white/[0.05]")}
    >
      <div className="flex items-start gap-3">
        <span className={"mt-0.5 grid h-4 w-4 shrink-0 place-items-center rounded-full border " + (selected ? "border-coral-400" : "border-steel-500")}>
          {selected && <span className="h-2 w-2 rounded-full bg-coral-400" />}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-center justify-between gap-3">
            <span className="text-sm font-semibold text-white">{model.label}</span>
            <span className="font-mono text-[11px] text-steel-400">~{model.memory_gb.toFixed(1)} GB</span>
          </span>
          <span className="mt-1 block text-xs leading-relaxed text-steel-400">{model.description}</span>
          {!model.available && <span className="mt-1.5 inline-block text-[11px] font-medium text-critical-700">Not found in oMLX</span>}
        </span>
      </div>
    </button>
  );
}
