import { StrictMode, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

type Mode = "mp3_only" | "transcript_only" | "video_only" | "triple" | "markdown";
type QueueItem = { id: string; url: string; addedAt: string };
type Progress = { status?: string; total_count?: number; completed_count?: number; skipped_count?: number; processed_count?: number; current_index?: number; current_title?: string; current_url?: string; error?: string };
type HistoryItem = { video_name?: string; url?: string; platform?: string; source_type?: string; downloaded_at?: string; file_path?: string; transcript?: string };

const QUEUE_KEY = "textforge.linkQueue.v1";
const recentKey = "textforge.recentUrls";
const modes: Array<{ id: Mode; label: string; detail: string }> = [
  { id: "mp3_only", label: "Ses indir", detail: "M4A" },
  { id: "transcript_only", label: "Transkript", detail: "M4A + metin" },
  { id: "video_only", label: "Video indir", detail: "MP4" },
  { id: "triple", label: "Üçlü indir", detail: "MP4 + M4A + metin" },
  { id: "markdown", label: "Web'i Markdown'a çevir", detail: "sayfa metni" },
];

function id() { return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`; }
function operationId() { return `op-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`; }
function extractUrls(text: string) {
  const candidates = text.match(/https?:\/\/[^\s<>'"`]+/gi) ?? [];
  return candidates.map(value => value.replace(/[),.;!?]+$/, "")).filter(value => {
    try { new URL(value); return true; } catch { return false; }
  });
}
function validUrl(url: string) { try { new URL(url); return true; } catch { return false; } }
function statusLabel(status?: string) {
  return ({ starting: "Başlıyor", ready: "Liste hazırlanıyor", waiting: "Bekliyor", downloading: "İndiriliyor", downloaded: "İndirildi", converting: "Sese dönüştürülüyor", transcribing: "Transkript hazırlanıyor", skipped: "Atlandı", completed: "Tamamlandı", cancelled: "Durduruldu", error: "Hata" } as Record<string, string>)[status ?? ""] ?? "Hazır";
}
function platform(url: string) {
  try {
    const host = new URL(url).hostname.toLowerCase();
    if (host.includes("youtube") || host === "youtu.be") return "YouTube";
    if (host.includes("instagram")) return "Instagram";
    if (host === "x.com" || host.endsWith(".x.com")) return "X";
  } catch { /* invalid input is handled by the composer */ }
  return "Web";
}

function App() {
  const [queue, setQueue] = useState<QueueItem[]>(() => {
    try { const saved = JSON.parse(localStorage.getItem(QUEUE_KEY) ?? "[]"); return Array.isArray(saved) ? saved : []; } catch { return []; }
  });
  const [draft, setDraft] = useState("");
  const [mode, setMode] = useState<Mode>("transcript_only");
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<Progress>({});
  const [message, setMessage] = useState("Linkleri yapıştır; sıraya otomatik ekleyelim.");
  const [log, setLog] = useState<string[]>([]);
  const [gpu, setGpu] = useState("Sistem kontrolü");
  const [draggedId, setDraggedId] = useState<string | null>(null);
  const activeOperation = useRef<string | null>(null);
  const eventSource = useRef<EventSource | null>(null);

  useEffect(() => { localStorage.setItem(QUEUE_KEY, JSON.stringify(queue)); }, [queue]);
  useEffect(() => {
    fetch("/status").then(response => response.json()).then(data => setGpu(data.gpu ? "GPU aktif" : "CPU modu")).catch(() => setGpu("Durum alınamadı"));
    return () => eventSource.current?.close();
  }, []);
  useEffect(() => {
    if (!activeOperation.current || !busy) return;
    const timer = window.setInterval(async () => {
      try {
        const response = await fetch(`/progress?operation_id=${encodeURIComponent(activeOperation.current ?? "")}`);
        if (response.ok) setProgress(await response.json());
      } catch { /* The final request reports actionable errors. */ }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [busy]);

  const addUrls = (raw: string) => {
    const urls = extractUrls(raw);
    if (!urls.length) { setMessage("Geçerli bir http veya https linki bulunamadı."); return; }
    const known = new Set(queue.map(item => item.url));
    const newItems = urls.reduce<QueueItem[]>((items, url) => {
      if (known.has(url)) return items;
      known.add(url);
      items.push({ id: id(), url, addedAt: new Date().toISOString() });
      return items;
    }, []);
    const duplicates = urls.length - newItems.length;
    if (!newItems.length) { setMessage("Bu linklerin tamamı zaten sırada."); return; }
    setQueue(previous => [...previous, ...newItems]);
    setDraft("");
    setMessage(`${newItems.length} link sıraya eklendi${duplicates ? `, ${duplicates} tekrar atlandı` : ""}.`);
  };
  const onPaste = (event: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const pasted = event.clipboardData.getData("text");
    const urls = extractUrls(pasted);
    if (urls.length) { event.preventDefault(); addUrls(pasted); }
  };
  const remove = (itemId: string) => setQueue(previous => previous.filter(item => item.id !== itemId));
  const move = (from: number, to: number) => setQueue(previous => {
    const next = [...previous]; const [item] = next.splice(from, 1); next.splice(to, 0, item); return next;
  });
  const rememberUrls = (urls: string[]) => {
    const prior = (() => { try { return JSON.parse(localStorage.getItem(recentKey) ?? "[]"); } catch { return []; } })() as string[];
    localStorage.setItem(recentKey, JSON.stringify([...urls, ...prior.filter(url => !urls.includes(url))].slice(0, 10)));
  };
  const startLogs = (op: string) => {
    eventSource.current?.close(); setLog([]);
    const source = new EventSource(`/logs/stream?operation_id=${encodeURIComponent(op)}`);
    source.onmessage = event => setLog(previous => [...previous.slice(-199), event.data]);
    eventSource.current = source;
  };
  const runQueue = async () => {
    if (!queue.length || busy) return;
    const op = operationId(); activeOperation.current = op; setBusy(true); setProgress({ status: "starting", total_count: queue.length, completed_count: 0 }); startLogs(op);
    const urls = queue.map(item => item.url); rememberUrls(urls); setMessage(`${queue.length} link işlenmek üzere kuyruğa alındı.`);
    try {
      const response = await fetch("/queue_process", { method: "POST", headers: { "Content-Type": "application/json", "X-Operation-Id": op }, body: JSON.stringify({ urls, mode }) });
      const data = await response.json();
      if (!response.ok || data.error) throw new Error(data.error ?? "Kuyruk işlenemedi.");
      const failed = Number(data.failed_count ?? 0);
      setProgress({ status: data.status === "cancelled" ? "cancelled" : "completed", total_count: data.total_count ?? queue.length, completed_count: data.completed_count ?? 0, skipped_count: data.skipped_count ?? 0, processed_count: data.processed_count ?? queue.length });
      const firstFailure = (data.results ?? []).find((item: { status?: string }) => item.status === "error") as { error?: string } | undefined;
      setMessage(data.status === "cancelled"
        ? "İşlem durduruldu."
        : `${data.completed_count ?? 0} link tamamlandı${failed ? `, ${failed} link hata verdi${firstFailure?.error ? `: ${firstFailure.error}` : ""}` : ""}.`);
    } catch (error) { const text = error instanceof Error ? error.message : "Kuyruk işlenemedi."; setProgress({ status: "error", error: text }); setMessage(text); }
    finally { eventSource.current?.close(); eventSource.current = null; activeOperation.current = null; setBusy(false); }
  };
  const cancel = async () => {
    if (!activeOperation.current) return;
    await fetch("/cancel", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ operation_id: activeOperation.current }) });
    setMessage("Durdurma isteği gönderildi.");
  };
  const processed = progress.processed_count ?? progress.completed_count ?? 0;
  const total = progress.total_count ?? queue.length;
  const percent = total ? Math.min(100, Math.round((processed / total) * 100)) : 0;
  const selectedMode = modes.find(item => item.id === mode)!;

  return <main className="app-shell">
    <header className="topbar"><a className="logo" href="/">TEXT<span>FORGE</span></a><nav><a className="nav-link active" href="/">Kuyruk</a><a className="nav-link" href="/history_page">Geçmiş</a></nav><div className="system"><i className={gpu === "GPU aktif" ? "online" : ""} />{gpu}</div></header>
    <section className="hero"><div><p className="kicker">MEDYA İŞ AKIŞI</p><h1>Linklerini yapıştır.<br/><em>Sırayla işleyelim.</em></h1><p className="lead">YouTube, Instagram, X ve web bağlantılarını tek tek veya toplu olarak ekle. Kuyruktaki sıra, işleme sırası olur.</p></div><div className="hero-stats"><strong>{queue.length}</strong><span>bekleyen link</span><small>Tekrarlanan linkler otomatik atlanır</small></div></section>
    <section className="workspace">
      <div className="composer card"><div className="card-heading"><div><p className="eyebrow">01 / EKLE</p><h2>Link kutusu</h2></div><span className="shortcut">⌘ / CTRL + V</span></div><textarea value={draft} onChange={event => setDraft(event.target.value)} onPaste={onPaste} placeholder="Bir veya daha fazla link yapıştır..." aria-label="Linkleri yapıştır"/><div className="composer-footer"><span>Her satırda bir link veya serbest metin içinden URL.</span><button className="button secondary" onClick={() => addUrls(draft)}>Sıraya ekle <b>→</b></button></div></div>
      <aside className="settings card"><p className="eyebrow">02 / İŞLEM</p><h2>Ne üretelim?</h2><div className="mode-list">{modes.map(item => <button key={item.id} className={`mode ${mode === item.id ? "selected" : ""}`} onClick={() => setMode(item.id)}><span><b>{item.label}</b><small>{item.detail}</small></span><i /></button>)}</div><button className="button primary run" disabled={!queue.length || busy} onClick={runQueue}>{busy ? statusLabel(progress.status) : `${queue.length} linki ${selectedMode.label.toLowerCase()}`}<b>→</b></button>{busy && <button className="button stop" onClick={cancel}>İşlemi durdur</button>}</aside>
    </section>
    <section className="queue card"><div className="queue-header"><div><p className="eyebrow">03 / SIRA</p><h2>İşleme kuyruğu</h2></div>{queue.length > 0 && <button className="text-button" onClick={() => { setQueue([]); setMessage("Kuyruk temizlendi."); }}>Tümünü temizle</button>}</div>{queue.length === 0 ? <div className="empty"><div>↳</div><strong>Kuyruk boş</strong><span>Linkleri yukarıdaki alana yapıştırdığında burada sıralanır.</span></div> : <ol>{queue.map((item, index) => <li key={item.id} draggable={!busy} onDragStart={() => setDraggedId(item.id)} onDragOver={event => event.preventDefault()} onDrop={() => { const from = queue.findIndex(entry => entry.id === draggedId); if (from >= 0) move(from, index); setDraggedId(null); }} className={draggedId === item.id ? "dragging" : ""}><span className="rank">{String(index + 1).padStart(2, "0")}</span><span className="handle" aria-hidden="true">⠿</span><span className="item-url"><b>{platform(item.url)}</b><span title={item.url}>{item.url}</span></span><button className="remove" onClick={() => remove(item.id)} disabled={busy} aria-label={`${item.url} linkini kaldır`}>×</button></li>)}</ol>}</section>
    <section className={`progress card ${busy || progress.status === "completed" || progress.status === "error" ? "visible" : ""}`}><div><p className="eyebrow">CANLI DURUM</p><h2>{statusLabel(progress.status)}</h2></div><div className="progress-numbers"><strong>{progress.completed_count ?? 0}</strong><span>/ {total}</span></div><div className="track"><i style={{ width: `${percent}%` }} /></div><p>{progress.current_title || progress.current_url || message}{progress.error ? ` · ${progress.error}` : ""}</p></section>
    <section className="logs card"><div className="queue-header"><div><p className="eyebrow">CANLI KAYIT</p><h2>İşlem akışı</h2></div><button className="text-button" onClick={() => setLog([])}>Temizle</button></div><pre>{log.length ? log.join("\n") : "> Kuyruk başladığında Python işlem kayıtları burada görünür."}</pre></section>
  </main>;
}

function History() {
  const [items, setItems] = useState<HistoryItem[]>([]); const [error, setError] = useState("");
  useEffect(() => { fetch("/history?limit=100").then(async response => { const data = await response.json(); if (!response.ok) throw new Error(data.error ?? "Geçmiş alınamadı."); setItems(data.items ?? []); }).catch(reason => setError(reason.message)); }, []);
  return <main className="app-shell"><header className="topbar"><a className="logo" href="/">TEXT<span>FORGE</span></a><nav><a className="nav-link" href="/">Kuyruk</a><a className="nav-link active" href="/history_page">Geçmiş</a></nav></header><section className="history-head"><p className="kicker">İŞLEM KAYITLARI</p><h1>Geçmiş</h1><p>{items.length} son kayıt gösteriliyor.</p></section><section className="history-list card">{error ? <div className="empty"><strong>{error}</strong></div> : !items.length ? <div className="empty"><strong>Henüz kayıt yok</strong></div> : items.map((item, index) => <article key={`${item.url}-${index}`}><span>{String(index + 1).padStart(2, "0")}</span><div><b>{item.video_name || item.url || "İsimsiz kayıt"}</b><p>{item.platform || "media"} · {item.source_type || ""} · {item.downloaded_at || ""}</p></div>{item.file_path && <code>{item.file_path}</code>}</article>)}</section></main>;
}

createRoot(document.getElementById("root")!).render(<StrictMode>{location.pathname === "/history_page" ? <History /> : <App />}</StrictMode>);
