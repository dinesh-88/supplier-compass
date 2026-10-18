import { Fragment, type ReactNode } from "react";

/**
 * Minimal Markdown → React elements (headings, lists, tables, bold, italic, code, links).
 * Never uses innerHTML, so model or file text cannot inject markup.
 */
export default function Markdown({ text, onLink }: { text: string; onLink?: (href: string) => void }) {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  let key = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i++;
      continue;
    }
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h) {
      const level = h[1].length;
      const content = inline(h[2], onLink);
      blocks.push(level <= 1 ? <h1 key={key++}>{content}</h1> : level === 2 ? <h2 key={key++}>{content}</h2> : <h3 key={key++}>{content}</h3>);
      i++;
      continue;
    }
    if (/^\s*\|.*\|\s*$/.test(line) && i + 1 < lines.length && /^\s*\|?[\s:-]+\|[\s|:-]*$/.test(lines[i + 1])) {
      const header = cells(line);
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) rows.push(cells(lines[i++]));
      blocks.push(
        <table key={key++}>
          <thead>
            <tr>{header.map((c, j) => <th key={j}>{inline(c, onLink)}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((r, ri) => (
              <tr key={ri}>{r.map((c, j) => <td key={j}>{inline(c, onLink)}</td>)}</tr>
            ))}
          </tbody>
        </table>,
      );
      continue;
    }
    if (/^\s*([-*]|\d+\.)\s+/.test(line)) {
      const ordered = /^\s*\d+\./.test(line);
      const items: string[] = [];
      while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*([-*]|\d+\.)\s+/, ""));
        i++;
      }
      const lis = items.map((it, j) => <li key={j}>{inline(it, onLink)}</li>);
      blocks.push(ordered ? <ol key={key++}>{lis}</ol> : <ul key={key++}>{lis}</ul>);
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|\s*([-*]|\d+\.)\s+|\s*\|)/.test(lines[i])) para.push(lines[i++]);
    if (!para.length) para.push(lines[i++]);
    blocks.push(<p key={key++}>{inline(para.join(" "), onLink)}</p>);
  }
  return <div className="prose-plain">{blocks}</div>;
}

function cells(row: string): string[] {
  return row.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
}

const TOKEN = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)\s]+\)|(?<!\w)_[^_]+_(?!\w)|(?<![\w*])\*[^*\s][^*]*\*(?![\w*]))/g;

function inline(text: string, onLink?: (href: string) => void): ReactNode {
  const parts = text.split(TOKEN);
  return parts.map((p, i) => {
    if (!p) return null;
    if (p.startsWith("**") && p.endsWith("**")) return <strong key={i}>{p.slice(2, -2)}</strong>;
    if (p.startsWith("`") && p.endsWith("`")) return <code key={i}>{p.slice(1, -1)}</code>;
    const link = p.match(/^\[([^\]]+)\]\(([^)\s]+)\)$/);
    if (link) {
      const href = link[2];
      if (!/^https?:\/\//i.test(href)) return <Fragment key={i}>{link[1]}</Fragment>;
      return (
        <a key={i} href={href} target="_blank" rel="noopener noreferrer nofollow" className="text-accent underline" onClick={() => onLink?.(href)}>
          {link[1]}
        </a>
      );
    }
    if ((p.startsWith("_") && p.endsWith("_")) || (p.startsWith("*") && p.endsWith("*") && p.length > 2)) return <em key={i}>{p.slice(1, -1)}</em>;
    return <Fragment key={i}>{p}</Fragment>;
  });
}
