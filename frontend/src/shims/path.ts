// ponytail: minimal path shim for live2d-renderer browser compat.
// Covers extname, dirname, join — the only three calls the library makes.

export function basename(p: string, ext?: string): string {
  const parts = p.replace(/\\/g, "/").split("/");
  let name = parts[parts.length - 1] || "";
  if (ext && name.endsWith(ext)) {
    name = name.slice(0, -ext.length);
  }
  return name;
}

export function dirname(p: string): string {
  const parts = p.replace(/\\/g, "/").split("/");
  parts.pop();
  return parts.join("/") || ".";
}

export function extname(p: string): string {
  const base = basename(p);
  const i = base.lastIndexOf(".");
  return i > 0 ? base.substring(i) : "";
}

export function join(...segments: string[]): string {
  return segments
    .map((s) => s.replace(/\\/g, "/"))
    .join("/")
    .replace(/\/+/g, "/");
}

export default { basename, dirname, extname, join };
