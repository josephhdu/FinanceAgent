import { marked } from "marked";
import DOMPurify from "dompurify";

// Render untrusted markdown (model replies) safely: parse to HTML, then sanitize
// so a reply can never inject <script>/onerror/etc. Same defense as the original
// vanilla UI, now a typed module.
export function mdSafe(md: string): string {
  const html = marked.parse(md || "", { async: false }) as string;
  return DOMPurify.sanitize(html);
}
