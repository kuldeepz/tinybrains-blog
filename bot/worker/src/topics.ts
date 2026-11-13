// Mirror of agents/topics.py: same JSON shape in ops/topics.json. Pure functions (unit-tested).

export type Status = "idea" | "queued" | "in_progress" | "in_review" | "published" | "rejected";
export interface Topic {
  id: string; title: string; notes: string; status: Status; tags: string[]; source: string;
  created: string; updated: string; slug: string | null; pr: number | null; url: string | null;
  private_files: boolean; history: { at: string; status: Status }[];
}
export interface TopicsFile { version: number; next_id: number; topics: Topic[] }

const STOP = new Set("a an the of for and or to in on with how why what is are vs using your you from into at by".split(" "));
const now = () => new Date().toISOString().replace(/\.\d{3}Z$/, "Z");

export function words(s: string): Set<string> {
  return new Set((s.toLowerCase().match(/[a-z0-9]+/g) ?? []).filter((w) => !STOP.has(w) && w.length > 1));
}

export function similarity(a: string, b: string): number {
  const wa = words(a), wb = words(b);
  if (!wa.size || !wb.size) return 0;
  let inter = 0;
  for (const w of wa) if (wb.has(w)) inter++;
  return inter / (wa.size + wb.size - inter);
}

export function similar(f: TopicsFile, title: string, threshold = 0.6): Topic[] {
  return f.topics
    .filter((t) => t.status !== "rejected")
    .map((t) => [similarity(title, t.title), t] as const)
    .filter(([s]) => s >= threshold)
    .sort((x, y) => y[0] - x[0])
    .map(([, t]) => t);
}

export function addIdea(f: TopicsFile, title: string, notes = "", source = "telegram"): Topic {
  const id = `T${String(f.next_id).padStart(3, "0")}`;
  f.next_id += 1;
  const t: Topic = {
    id, title: title.trim().slice(0, 200), notes: notes.trim().slice(0, 1000), status: "idea", tags: [], source,
    created: now(), updated: now(), slug: null, pr: null, url: null, private_files: false,
    history: [{ at: now(), status: "idea" }],
  };
  f.topics.push(t);
  return t;
}

export function setStatus(t: Topic, status: Status): void {
  t.status = status;
  t.updated = now();
  t.history.push({ at: now(), status });
}

const ICON: Record<Status, string> = { in_review: "👀", in_progress: "🛠", queued: "⏳", idea: "💡", published: "✅", rejected: "🗑" };

export function summary(f: TopicsFile, only?: Status[]): string {
  const by = (s: Status) => f.topics.filter((t) => t.status === s);
  const head = `📚 ${f.topics.length} topics · ✅ ${by("published").length} published · 🛠 ${by("in_progress").length + by("queued").length} in progress · 👀 ${by("in_review").length} in review · 💡 ${by("idea").length} ideas`;
  const order: Status[] = only ?? ["in_review", "in_progress", "queued", "idea", "published"];
  const lines = [head];
  for (const s of order) {
    for (const t of by(s).slice(-20)) {
      const extra = t.url ? ` → ${t.url}` : t.pr ? ` (PR #${t.pr})` : "";
      lines.push(`${ICON[s]} ${t.id} ${t.title}${extra}`);
    }
  }
  return lines.join("\n");
}

export function parseCommand(text: string): { cmd: string; arg: string } | null {
  const m = text.match(/^\/([a-z_]+)(?:@\w+)?\s*([\s\S]*)$/i);
  return m ? { cmd: m[1].toLowerCase(), arg: m[2].trim() } : null;
}
