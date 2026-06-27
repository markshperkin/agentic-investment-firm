function humanize(key: string): string {
  return key
    .replace(/_/g, " ")
    .replace(/\bpct\b/gi, "%")
    .replace(/\bid\b/gi, "ID")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function isPrimitive(v: unknown): boolean {
  return v === null || typeof v !== "object";
}

function Primitive({ v }: { v: unknown }) {
  if (v === null || v === undefined || v === "") return <span className="faint">—</span>;
  if (typeof v === "boolean") return <span>{v ? "yes" : "no"}</span>;
  if (typeof v === "number") return <span className="mono">{v}</span>;
  return <span>{String(v)}</span>;
}

function renderValue(v: unknown, depth: number) {
  if (isPrimitive(v)) return <div className="kv-val"><Primitive v={v} /></div>;
  if (Array.isArray(v)) return <ArrayView arr={v} depth={depth} />;
  return <Fields obj={v as Record<string, unknown>} depth={depth} />;
}

function ArrayView({ arr, depth }: { arr: unknown[]; depth: number }) {
  if (!arr.length) return <div className="kv-val faint">none</div>;
  if (arr.every(isPrimitive)) {
    return (
      <div className="kv-list">
        {arr.map((x, i) => (
          <div className="kv-item" key={i}>
            <span className="bullet">•</span>
            <span className="kv-val"><Primitive v={x} /></span>
          </div>
        ))}
      </div>
    );
  }
  return (
    <div className="kv-list">
      {arr.map((x, i) => (
        <div className="kv-block" key={i}>
          <div className="idx">#{i + 1}</div>
          {renderValue(x, depth + 1)}
        </div>
      ))}
    </div>
  );
}

function Fields({ obj, depth }: { obj: Record<string, unknown>; depth: number }) {
  const keys = Object.keys(obj);
  if (!keys.length) return <div className="kv-val faint">—</div>;
  return (
    <div className={depth === 0 ? "dv-fields" : "dv-fields dv-nest"}>
      {keys.map((k) => (
        <div className="kv" key={k}>
          <div className="kv-key">{humanize(k)}</div>
          {renderValue(obj[k], depth + 1)}
        </div>
      ))}
    </div>
  );
}

export default function DataView({ value }: { value: unknown }) {
  return <div className="dv">{renderValue(value, 0)}</div>;
}
