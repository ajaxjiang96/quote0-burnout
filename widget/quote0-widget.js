// quote0-widget.js — JSBox iOS 桌面小组件
// 显示和 Quote/0 墨水屏完全同步的 Codex + Claude + DeepSeek/OpenCode 用量数据
// 改下面 CONFIG 的值即可使用

// ═══════════════════════ CONFIG ═══════════════════════
const CODEX_TOKEN  = "";  // ~/.codex/auth.json → tokens.access_token
const CODEX_ACCT   = "";  // ~/.codex/auth.json → tokens.account_id（可选）
const CLAUDE_TOKEN = "";  // ~/.claude/.credentials.json → claudeAiOauth.accessToken
const DEEPSEEK_KEY = "";  // DeepSeek API key（sk-...）
const DS_MODEL = "deepseek-v4-flash";  // 计价模型：deepseek-v4-flash / deepseek-v4-pro
const OPENCODE_KEY = "";  // OpenCode Go 用量 API key（第二面板，优先于 DeepSeek）
// ══════════════════════════════════════════════════════

// DeepSeek 官方价目（百万 tokens，缓存未命中输入 / 输出；来源 api-docs.deepseek.com，2026-08 抓取）
// 高峰时段 UTC 01:00–04:00、06:00–10:00（北京时间 9:00–12:00、14:00–18:00），其余为谷时 ×0.5
const DS_PRICES = {
  "deepseek-v4-flash": {
    USD: { in: { peak: 0.44, off: 0.22 },  out: { peak: 1.32, off: 0.66 } },
    CNY: { in: { peak: 3.0,  off: 1.5 },   out: { peak: 9.0,  off: 4.5 } }
  },
  "deepseek-v4-pro": {
    USD: { in: { peak: 1.32, off: 0.66 },  out: { peak: 3.96, off: 1.98 } },
    CNY: { in: { peak: 9.0,  off: 4.5 },   out: { peak: 27.0, off: 13.5 } }
  }
};
// 多模态模型（2026-08-21 上线）：与 v4-flash 同价（图片转 token，≤384 tokens/张）
DS_PRICES["deepseek-v4-flash-vision-exp"] = DS_PRICES["deepseek-v4-flash"];

function dsWindow(currency) {
  const now = new Date();
  const h = now.getUTCHours();
  const peak = (h >= 1 && h < 4) || (h >= 6 && h < 10);
  // 下次切换时间（UTC）：峰段 1-4→04:00、6-10→10:00；谷段 0-1→01:00、4-6→06:00、10-24→次日01:00
  let endH, endD, next;
  if (h >= 1 && h < 4)      { endH = 4;  endD = 0; next = "OFF"; }
  else if (h >= 4 && h < 6) { endH = 6;  endD = 0; next = "PEAK"; }
  else if (h >= 6 && h < 10){ endH = 10; endD = 0; next = "OFF"; }
  else if (h >= 10)         { endH = 1;  endD = 1; next = "PEAK"; }
  else                      { endH = 1;  endD = 0; next = "PEAK"; }
  const ends = new Date(now);
  ends.setUTCHours(endH, 0, 0, 0);
  if (endD) ends.setUTCDate(ends.getUTCDate() + 1);
  const mins = Math.max(0, Math.round((ends - now) / 60000));
  const cd = mins >= 60 ? Math.floor(mins / 60) + "h" + pad(mins % 60) + "m" : mins + "m";

  const p = DS_PRICES[DS_MODEL] || DS_PRICES["deepseek-v4-flash"];
  const cur = p[currency] || p.USD;
  const key = peak ? "peak" : "off";
  return { label: peak ? "PEAK" : "OFF", in: cur.in[key], out: cur.out[key], next: next, cd: cd };
}

// ── 数据获取 ──────────────────────────────────────────

function getCodex() {
  try {
    const headers = {
      "Authorization": "Bearer " + CODEX_TOKEN,
      "Accept": "application/json"
    };
    if (CODEX_ACCT) headers["ChatGPT-Account-Id"] = CODEX_ACCT;

    const r = $http.get({
      url: "https://chatgpt.com/backend-api/wham/usage",
      header: headers,
      timeout: 8
    });
    if (r.error) return { ok: false, msg: "请求失败" };

    const d = r.data;
    const rl = d.rate_limit || {};
    const p = rl.primary_window || {};
    const s = rl.secondary_window || {};
    return {
      ok: true,
      sUsed: p.used_percent || 0,
      sReset: p.reset_at || null,
      lUsed: s.used_percent || 0,
      lReset: s.reset_at || null
    };
  } catch (e) { return { ok: false, msg: String(e) }; }
}

function getClaude() {
  if (!CLAUDE_TOKEN) return { ok: false, msg: "无 token" };
  try {
    const r = $http.get({
      url: "https://api.anthropic.com/api/oauth/usage",
      header: {
        "Authorization": "Bearer " + CLAUDE_TOKEN,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "anthropic-beta": "oauth-2025-04-20",
        "User-Agent": "claude-code/2.1.0"
      },
      timeout: 8
    });
    if (r.error) return { ok: false, msg: "请求失败" };

    const s = r.data.five_hour || {};
    const w = r.data.seven_day || r.data.seven_day_oauth_apps || {};
    return {
      ok: true,
      sUsed: s.utilization || 0,
      sReset: s.resets_at || null,
      lUsed: w.utilization || 0,
      lReset: w.resets_at || null
    };
  } catch (e) { return { ok: false, msg: String(e) }; }
}

function getDeepSeek() {
  if (!DEEPSEEK_KEY) return { ok: false, msg: "无 key" };
  try {
    const r = $http.get({
      url: "https://api.deepseek.com/user/balance",
      header: { "Authorization": "Bearer " + DEEPSEEK_KEY, "Accept": "application/json" },
      timeout: 8
    });
    if (r.error) return { ok: false, msg: "请求失败" };

    const infos = r.data.balance_infos || [];
    const usd = infos.find(x => x.currency === "USD") || infos[0];
    if (!usd) return { ok: false, msg: "无余额" };

    const curr = usd.currency || "USD";
    return {
      ok: true,
      balance: usd.total_balance || 0,
      symbol: curr === "CNY" ? "¥" : curr === "EUR" ? "€" : "$",
      currency: curr,
      avail: r.data.is_available !== false
    };
  } catch (e) { return { ok: false, msg: String(e) }; }
}

// OpenCode Go（OpenCode Zen "Go" 订阅）：dollar 限额 $12/5h、$30/周、$60/月
function getOpenCode() {
  if (!OPENCODE_KEY) return { ok: false, msg: "无 key" };
  try {
    const r = $http.get({
      url: "https://opencode.ai/zen/go/v1/usage",
      header: { "Authorization": "Bearer " + OPENCODE_KEY, "Accept": "application/json", "User-Agent": "quote0-widget" },
      timeout: 8
    });
    if (r.error) return { ok: false, msg: "请求失败" };
    const u = (r.data && r.data.usage) || {};
    const roll = u.rolling || {};
    const wk = u.weekly || {};
    const mo = u.monthly || {};
    return { ok: true, used: roll.percent || 0, reset: roll.resetsAt || null, wkUsed: wk.percent || null, wkReset: wk.resetsAt || null, moUsed: mo.percent || null, moReset: mo.resetsAt || null };
  } catch (e) { return { ok: false, msg: String(e) }; }
}

// ── 工具函数 ──────────────────────────────────────────

function fmtTime(ts) {
  if (!ts) return "";
  const resetMs = typeof ts === "string" ? Date.parse(ts) : ts * 1000;
  const secs = Math.max(0, Math.floor((resetMs - Date.now()) / 1000));
  if (secs <= 0) return "now";
  const d = Math.floor(secs / 86400);
  const h = Math.floor((secs % 86400) / 3600);
  const m = Math.floor((secs % 3600) / 60);
  if (d > 0) return d + "d" + h + "h";
  if (h > 0) return m > 0 ? h + "h" + pad(m) + "m" : h + "h";
  return m + "m";
}

function pad(n) { return n < 10 ? "0" + n : String(n); }

function pctBar(used, w) {
  const rem = 100 - used;
  const fill = Math.round(rem / 100 * w);
  let s = "";
  for (let i = 0; i < fill; i++) s += "█";
  for (let i = fill; i < w; i++) s += "░";
  return s;
}

function cxStatus(u) {
  if (u >= 90) return "●";
  if (u >= 70) return "◐";
  return "○";
}

function dsStatus(b, a) {
  if (!a || b < 3) return "●";
  if (b < 10) return "◐";
  return "○";
}

// ── Widget 渲染 ───────────────────────────────────────

$widget.setTimeline(function(ctx) {
  const cx = getCodex();
  const cl = getClaude();
  const ds = getDeepSeek();
  const oc = getOpenCode();
  // 第二面板：优先 OpenCode Go，回退 DeepSeek
  const useOc = oc.ok;
  const useDs = ds.ok && !useOc;
  const family = ctx.family;  // 0=small, 1=medium, 2=large

  const now = new Date();
  const timeStr = pad(now.getHours()) + ":" + pad(now.getMinutes());

  // 根据 widget 大小调整参数
  const compact = family === 0;
  const fSize  = compact ? 9 : 10;
  const sSize  = compact ? 7 : 8;
  const lh     = compact ? 12 : 14;
  const barW   = compact ? 8 : 12;

  const rows = [];

  // 标题行：时间 + 状态（第二面板显示 O 或 D 其一）
  const cxBadge = cx.ok ? cxStatus(cx.sUsed) : "✕";
  const clBadge = cl.ok ? cxStatus(cl.sUsed) : "✕";
  const secondBadge = useOc ? cxStatus(oc.used)
                            : (useDs ? dsStatus(ds.balance, ds.avail) : "✕");
  const secondTag = useOc ? "O" : (useDs ? "D" : " ");
  rows.push({ text: "C " + cxBadge + "  Cl " + clBadge + "  " + secondTag + " " + secondBadge + "  " + timeStr, size: sSize });

  if (cx.ok) {
    const sr = 100 - cx.sUsed;
    const lr = 100 - cx.lUsed;
    rows.push({ text: "5h " + pctBar(cx.sUsed, barW) + " " + sr.toFixed(0) + "% " + fmtTime(cx.sReset), size: fSize });
    rows.push({ text: "Wk " + pctBar(cx.lUsed, barW) + " " + lr.toFixed(0) + "% " + fmtTime(cx.lReset), size: fSize });
  } else {
    rows.push({ text: "Codex: " + (cx.msg || "error"), size: fSize });
  }

  // 分隔
  rows.push({ text: "—".repeat(compact ? 14 : 20), size: sSize });

  if (cl.ok) {
    const sr = 100 - cl.sUsed;
    const lr = 100 - cl.lUsed;
    rows.push({ text: "C5 " + pctBar(cl.sUsed, barW) + " " + sr.toFixed(0) + "% " + fmtTime(cl.sReset), size: fSize });
    rows.push({ text: "CW " + pctBar(cl.lUsed, barW) + " " + lr.toFixed(0) + "% " + fmtTime(cl.lReset), size: fSize });
  } else {
    rows.push({ text: "Claude: " + (cl.msg || "error"), size: fSize });
  }

  if (useOc) {
    rows.push({ text: "—".repeat(compact ? 14 : 20), size: sSize });
    const or_ = 100 - oc.used;
    rows.push({ text: "OC  5h " + pctBar(oc.used, barW) + " " + or_.toFixed(0) + "% " + fmtTime(oc.reset), size: fSize });
    if (oc.wkUsed != null) {
      const ow_ = 100 - oc.wkUsed;
      rows.push({ text: "    Wk " + pctBar(oc.wkUsed, barW) + " " + ow_.toFixed(0) + "% " + fmtTime(oc.wkReset), size: fSize });
    }
    if (oc.moUsed != null) {
      const om_ = 100 - oc.moUsed;
      rows.push({ text: "    Mo " + pctBar(oc.moUsed, barW) + " " + om_.toFixed(0) + "% " + fmtTime(oc.moReset), size: fSize });
    }
  } else if (useDs) {
    rows.push({ text: "—".repeat(compact ? 14 : 20), size: sSize });
    const w = dsWindow(ds.currency);
    rows.push({ text: ds.symbol + ds.balance.toFixed(2) + "  " + w.label + " " + ds.symbol + w.in.toFixed(2) + "  " + w.cd, size: fSize + 4 });
    rows.push({ text: "in " + ds.symbol + w.in.toFixed(2) + "  out " + ds.symbol + w.out.toFixed(2) + "  " + w.next + " in " + w.cd, size: sSize });
  }

  const padX = 6;
  const padY = 4;

  const views = rows.map(function(row, i) {
    return {
      type: "label",
      props: {
        text: row.text,
        font: $font("Menlo", row.size),
        textColor: $color("#000"),
        align: $align.left,
        frame: $rect(padX, padY + i * lh, ctx.displaySize.width - padX * 2, lh)
      }
    };
  });

  return {
    type: "view",
    props: {
      bgcolor: $color("#fff"),
      frame: $rect(0, 0, ctx.displaySize.width, padY * 2 + rows.length * lh)
    },
    views: views
  };
});
