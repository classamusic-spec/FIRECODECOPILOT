/**
 * LibraryDrawer — the code-book Library + setup panel:
 *   - a setup checklist (backend reachable, model configured, books found, index built),
 *   - every PDF in the books folder with EDITABLE manifest fields (book / edition / collection /
 *     CT-amendment flag) saved to code_books/books.yaml,
 *   - indexing with LIVE progress (SSE from POST /ingest/stream) instead of a silent blocking call.
 *
 * Presentational + self-fetching: opens → loads /health and /books; App only owns `open`.
 */
import { useEffect, useState } from "react";
import type { BookEntry, Health, IngestEvent } from "../lib/api";
import { getBooks, getHealth, ingestStream, saveBooksManifest } from "../lib/api";
import { BookIcon, CheckIcon, WarningIcon } from "./icons";
import Drawer from "./Drawer";

interface Props {
  open: boolean;
  onClose: () => void;
  /** Called after an ingest run so App can refresh the edition selector. */
  onIndexed?: () => void;
}

type Draft = Pick<BookEntry, "book" | "edition" | "collection" | "is_amendment_doc">;

export default function LibraryDrawer({ open, onClose, onIndexed }: Props) {
  const [health, setHealth] = useState<Health | null>(null);
  const [healthErr, setHealthErr] = useState(false);
  const [books, setBooks] = useState<BookEntry[]>([]);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [saving, setSaving] = useState(false);
  const [savedTick, setSavedTick] = useState(false);
  const [ingesting, setIngesting] = useState(false);
  const [progress, setProgress] = useState<string[]>([]);
  const [filesDone, setFilesDone] = useState(0);
  const [filesTotal, setFilesTotal] = useState(0);

  // (Re)load everything each time the drawer opens.
  useEffect(() => {
    if (!open) return;
    let alive = true;
    getHealth()
      .then((h) => alive && (setHealth(h), setHealthErr(false)))
      .catch(() => alive && setHealthErr(true));
    refreshBooks();
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  function refreshBooks() {
    getBooks()
      .then((r) => {
        setBooks(r.books);
        setDrafts(Object.fromEntries(r.books.map((b) => [
          b.file,
          { book: b.book, edition: b.edition, collection: b.collection,
            is_amendment_doc: b.is_amendment_doc },
        ])));
      })
      .catch(() => setBooks([]));
  }

  function setField(file: string, field: keyof Draft, value: string | boolean) {
    setDrafts((prev) => ({ ...prev, [file]: { ...prev[file], [field]: value } }));
  }

  async function handleSave() {
    setSaving(true);
    try {
      await saveBooksManifest(drafts);
      setSavedTick(true);
      setTimeout(() => setSavedTick(false), 2000);
      refreshBooks();
    } catch {
      /* keep edits; the user can retry */
    } finally {
      setSaving(false);
    }
  }

  async function handleIngest(force: boolean) {
    setIngesting(true);
    setProgress([]);
    setFilesDone(0);
    setFilesTotal(0);
    const log = (line: string) => setProgress((prev) => [...prev.slice(-30), line]);
    try {
      await ingestStream(force, (ev: IngestEvent) => {
        if (ev.type === "start") setFilesTotal(ev.files ?? 0);
        else if (ev.type === "file" && ev.status === "skipped") {
          setFilesDone((n) => n + 1);
          log(`⏭  ${ev.file} — unchanged, skipped`);
        } else if (ev.type === "file" && ev.status === "indexing") log(`⏳ ${ev.file} — indexing…`);
        else if (ev.type === "file_done") {
          setFilesDone((n) => n + 1);
          log(`✅ ${ev.file} — ${ev.chunks} chunks → ${ev.collection}`);
        } else if (ev.type === "removed") log(`🗑  ${ev.file} — purged (file removed)`);
        else if (ev.type === "error") log(`⚠️ ${ev.message}`);
        else if (ev.type === "done") log("Done.");
      });
      refreshBooks();
      onIndexed?.();
    } catch (e) {
      log(`⚠️ Indexing failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setIngesting(false);
    }
  }

  const indexedChunks = books.reduce((n, b) => n + b.chunks, 0);
  const pct = filesTotal > 0 ? Math.round((filesDone / filesTotal) * 100) : 0;

  return (
    <Drawer
      open={open}
      onClose={onClose}
      label="Code-book library"
      header={
        <>
          <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-navy-800 text-coral-400 ring-1 ring-white/10">
            <BookIcon className="h-4 w-4" />
          </span>
          <div className="leading-tight">
            <h2 className="text-[15px] font-semibold tracking-tight text-white">Library</h2>
            <p className="text-xs text-steel-400">Your code books, editions, and the index</p>
          </div>
        </>
      }
    >
      {/* Setup checklist — the at-a-glance "is everything wired up?" row. */}
      <section className="mb-4 space-y-1.5">
        <ChecklistRow ok={!healthErr && Boolean(health?.ok)}
                      label={healthErr ? "Backend unreachable — is the engine running?" : "Backend running"} />
        <ChecklistRow ok={Boolean(health)}
                      label={health ? `Model: ${health.generation_provider} · ${health.model}` : "Model provider"} />
        <ChecklistRow ok={books.length > 0}
                      label={books.length ? `${books.length} code book${books.length === 1 ? "" : "s"} found` : "No PDFs in your code-books folder yet"} />
        <ChecklistRow ok={indexedChunks > 0}
                      label={indexedChunks ? `Index built — ${indexedChunks.toLocaleString()} chunks` : "Not indexed yet — run indexing below"} />
      </section>

      {/* Books table: manifest fields are editable; Save writes books.yaml. */}
      {books.length > 0 && (
        <section className="space-y-2">
          {books.map((b) => {
            const d = drafts[b.file];
            if (!d) return null;
            return (
              <div key={b.file} className="glass-inset p-3">
                <div className="flex items-center justify-between gap-2">
                  <p className="truncate font-mono text-xs text-steel-200">{b.file}</p>
                  <span className={"shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider " +
                    (b.indexed ? "bg-verified-500/15 text-verified-700" : "bg-white/10 text-steel-400")}>
                    {b.indexed ? `indexed · ${b.chunks}` : "not indexed"}
                  </span>
                </div>
                <div className="mt-2 grid grid-cols-2 gap-1.5 sm:grid-cols-3">
                  <LabeledInput label="Book" value={d.book} onChange={(v) => setField(b.file, "book", v)} />
                  <LabeledInput label="Edition" value={d.edition} onChange={(v) => setField(b.file, "edition", v)} />
                  <LabeledInput label="Collection" value={d.collection} onChange={(v) => setField(b.file, "collection", v)} />
                </div>
                <label className="mt-2 flex items-center gap-2 text-xs text-steel-300">
                  <input
                    type="checkbox"
                    checked={d.is_amendment_doc}
                    onChange={(e) => setField(b.file, "is_amendment_doc", e.target.checked)}
                    className="h-3.5 w-3.5 accent-coral-500"
                  />
                  Connecticut amendment document (its text governs over the model code)
                </label>
              </div>
            );
          })}

          <div className="flex flex-wrap items-center gap-2 pt-1">
            <button
              type="button"
              onClick={handleSave}
              disabled={saving || ingesting}
              className="rounded-lg bg-coral-500 px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-coral-400 disabled:opacity-50"
            >
              {saving ? "Saving…" : savedTick ? "Saved ✓" : "Save book settings"}
            </button>
            <button
              type="button"
              onClick={() => handleIngest(false)}
              disabled={ingesting}
              className="rounded-lg border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs font-semibold text-steel-200 transition-colors hover:border-coral-500/40 disabled:opacity-50"
            >
              Index new / changed
            </button>
            <button
              type="button"
              onClick={() => handleIngest(true)}
              disabled={ingesting}
              className="rounded-lg border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs font-semibold text-steel-200 transition-colors hover:border-coral-500/40 disabled:opacity-50"
            >
              Re-index everything
            </button>
          </div>
        </section>
      )}

      {/* Live indexing progress. */}
      {(ingesting || progress.length > 0) && (
        <section className="mt-4">
          {filesTotal > 0 && (
            <div className="mb-2 h-1.5 overflow-hidden rounded-full bg-white/10">
              <div className="h-full rounded-full bg-coral-500 transition-all duration-300"
                   style={{ width: `${pct}%` }} />
            </div>
          )}
          <div className="glass-inset scroll-thin max-h-44 space-y-0.5 overflow-auto p-2.5 font-mono text-[11px] leading-relaxed text-steel-300">
            {progress.map((line, i) => <div key={i}>{line}</div>)}
            {ingesting && <div className="text-steel-500">working…</div>}
          </div>
        </section>
      )}
    </Drawer>
  );
}

function ChecklistRow({ ok, label }: { ok: boolean; label: string }) {
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className={"grid h-5 w-5 shrink-0 place-items-center rounded-full " +
        (ok ? "bg-verified-500/15 text-verified-700" : "bg-coral-500/15 text-coral-300")}>
        {ok ? <CheckIcon className="h-3 w-3" /> : <WarningIcon className="h-3 w-3" />}
      </span>
      <span className={ok ? "text-steel-200" : "text-coral-200"}>{label}</span>
    </div>
  );
}

function LabeledInput({ label, value, onChange }: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="block">
      <span className="mb-0.5 block text-[10px] font-semibold uppercase tracking-wider text-steel-500">{label}</span>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg border border-white/10 bg-navy-950/60 px-2 py-1.5 text-xs text-steel-100 focus:border-coral-500/50 focus:outline-none"
      />
    </label>
  );
}
