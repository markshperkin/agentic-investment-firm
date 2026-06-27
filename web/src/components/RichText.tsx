import { Fragment, ReactNode } from "react";

// Render **bold** spans within a line.
function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? (
      <strong key={i}>{part.slice(2, -2)}</strong>
    ) : (
      <Fragment key={i}>{part}</Fragment>
    ),
  );
}

// Lightweight renderer for the freeform risk reasoning: paragraphs + numbered items
// + **bold**, no markdown dependency. Handles both newline-separated and inline
// "1. ... 2. ..." numbering.
export default function RichText({ text }: { text: string }) {
  let blocks = text.split(/\n+/).map((s) => s.trim()).filter(Boolean);
  if (blocks.length <= 1) {
    blocks = text.split(/(?=\d+\.\s+\*\*)/).map((s) => s.trim()).filter(Boolean);
  }
  return (
    <div className="rich">
      {blocks.map((b, i) => {
        const m = b.match(/^(\d+)\.\s+([\s\S]*)$/);
        if (m) {
          return (
            <div className="rich-item" key={i}>
              <span className="rich-num">{m[1]}</span>
              <div className="rich-body">{inline(m[2])}</div>
            </div>
          );
        }
        return <p className="rich-p" key={i}>{inline(b)}</p>;
      })}
    </div>
  );
}
