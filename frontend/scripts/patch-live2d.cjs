/**
 * 修补 live2d-renderer（构建产物 build/renderer/*.js，postinstall 自动执行，全部幂等）。
 *
 * Patch 1 — browser path shim: require("path") 在浏览器端不存在。
 * Patch 2 — motion 缓存键修复: load() 用组索引存键（且同组内互相覆盖），
 *           startMotion() 用动作索引查 → 永远 cache miss → 每次起动作
 *           全量重解析 motion3.json。randomMotion 自动续播时形成
 *           每帧 ~90ms + 每秒几十 MB 分配的死循环（2026-07 FPS 崩溃根因）。
 *
 * ponytail: 等上游修复后移除此脚本。
 */
'use strict';

const fs = require('fs');
const path = require('path');

const BUILD_DIR = path.resolve(__dirname, '../node_modules/live2d-renderer/build/renderer');

if (!fs.existsSync(BUILD_DIR)) {
  console.log('[patch-live2d] live2d-renderer not found, skipping');
  process.exit(0);
}

// ── Patch 1: browser path shim (Live2DCubismModel.js) ──────────

const MODEL_JS = path.join(BUILD_DIR, 'Live2DCubismModel.js');
{
  let content = fs.readFileSync(MODEL_JS, 'utf-8');
  if (content.includes('ponytail: browser path shim')) {
    console.log('[patch-live2d] path shim already patched ✓');
  } else {
    const oldRequire = /const path_\d+\s*=\s*__importDefault\(require\("path"\)\);/;
    if (!oldRequire.test(content)) {
      console.log('[patch-live2d] path shim pattern not found (already fixed upstream?)');
    } else {
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
      fs.writeFileSync(MODEL_JS, content, 'utf-8');
      console.log('[patch-live2d] path shim patched ✓');
    }
  }
}

// ── Patch 2: motion 缓存键修复 (MotionController.js) ────────────

const MC_JS = path.join(BUILD_DIR, 'MotionController.js');
{
  let content = fs.readFileSync(MC_JS, 'utf-8');
  if (content.includes('ponytail: motion cache key fix')) {
    console.log('[patch-live2d] motion cache key already patched ✓');
  } else {
    const oldBlock =
      'const name = `${group}_${i}`;\n' +
      '                for (let i = 0; i < motionBuffers.length; i++) {\n' +
      '                    const motionBuffer = motionBuffers[i];';
    const newBlock =
      '// ponytail: motion cache key fix — 键改为 组名_动作索引，与 startMotion 查询一致\n' +
      '                for (let i = 0; i < motionBuffers.length; i++) {\n' +
      '                    const name = `${group}_${i}`;\n' +
      '                    const motionBuffer = motionBuffers[i];';
    if (content.includes(oldBlock)) {
      content = content.replace(oldBlock, newBlock);
      fs.writeFileSync(MC_JS, content, 'utf-8');
      console.log('[patch-live2d] motion cache key patched ✓');
    } else {
      console.error('[patch-live2d] motion cache key pattern NOT FOUND — 库版本变了？');
      process.exitCode = 1;
    }
  }
}
