/**
 * 修补 live2d-renderer — 将 require("path") 替换为浏览器 shim。
 *
 * ponytail: live2d-renderer 在浏览器端不应依赖 Node path 模块。
 *           等上游修复后移除此脚本。添加时机: 上游不支持 ESM 时。
 */
'use strict';

const fs = require('fs');
const path = require('path');

const TARGET = path.resolve(
  __dirname,
  '../node_modules/live2d-renderer/build/renderer/Live2DCubismModel.js'
);

if (!fs.existsSync(TARGET)) {
  console.log('[patch-live2d] target not found, skipping');
  process.exit(0);
}

let content = fs.readFileSync(TARGET, 'utf-8');

// Already patched?
if (content.includes('ponytail: browser path shim')) {
  console.log('[patch-live2d] already patched ✓');
  process.exit(0);
}

// Replace require("path") with browser shim
const oldRequire = /const path_\d+\s*=\s*__importDefault\(require\("path"\)\);/;
if (!oldRequire.test(content)) {
  console.log('[patch-live2d] pattern not found (already fixed upstream?)');
  process.exit(0);
}

const SHIM = [
  '// ponytail: browser path shim replacing require("path")',
  'const path_1 = { default: {',
  '    basename: function basename(p, ext) { var parts = String(p).replace(/\\\\/g, "/").split("/"); var n = parts[parts.length - 1] || ""; if (ext && n.endsWith(ext)) n = n.slice(0, -ext.length); return n; },',
  '    dirname: function dirname(p) { var parts = String(p).replace(/\\\\/g, "/").split("/"); parts.pop(); return parts.join("/") || "."; },',
  '    extname: function extname(p) { var base = this.basename(p); var i = base.lastIndexOf("."); return i > 0 ? base.substring(i) : ""; },',
  '    join: function join() { var s = []; for (var i = 0; i < arguments.length; i++) s.push(String(arguments[i]).replace(/\\\\/g, "/")); return s.join("/").replace(/\\/+/g, "/"); },',
  '} };',
].join('\n');

content = content.replace(oldRequire, SHIM);
fs.writeFileSync(TARGET, content, 'utf-8');
console.log('[patch-live2d] patched ✓');
