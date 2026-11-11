"""The single-page setup UI served by `ustc-bb-mcp ui` (no build step, no CDN)."""

PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>USTC BB 作业提醒 · 邮箱绑定</title>
<style>
  :root{
    --bg:#f4f6fb; --panel:#ffffff; --ink:#101828; --muted:#667085; --line:#e5e8f0;
    --accent:#1058d0; --accent-weak:#eaf1ff; --ok:#0f8a5f; --ok-weak:#e8f7f0;
    --warn:#b4531a; --warn-weak:#fdf1e6; --shadow:0 1px 2px rgba(16,24,40,.05),0 12px 32px -12px rgba(16,24,40,.16);
  }
  @media (prefers-color-scheme: dark){
    :root{ --bg:#0e1117; --panel:#161b24; --ink:#e8ecf4; --muted:#92a0b5; --line:#242c39;
      --accent:#6ea8ff; --accent-weak:#17253c; --ok:#4ec99a; --ok-weak:#12281f;
      --warn:#e0a06a; --warn-weak:#2a2117; --shadow:0 1px 2px rgba(0,0,0,.4),0 16px 40px -16px rgba(0,0,0,.7); }
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
    font:15px/1.6 system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
    -webkit-font-smoothing:antialiased;padding:32px 20px 56px}
  .wrap{max-width:960px;margin:0 auto}
  header{display:flex;align-items:center;gap:12px;margin-bottom:22px;flex-wrap:wrap}
  .mark{width:34px;height:34px;border-radius:10px;background:var(--accent);color:#fff;
    display:grid;place-items:center;font-weight:700;font-size:15px;letter-spacing:.5px}
  h1{font-size:19px;margin:0;font-weight:650;letter-spacing:-.2px}
  .sub{color:var(--muted);font-size:13px;margin:1px 0 0}
  .pill{margin-left:auto;display:inline-flex;align-items:center;gap:7px;padding:6px 12px;border-radius:999px;
    font-size:12.5px;font-weight:600;background:var(--warn-weak);color:var(--warn);border:1px solid transparent}
  .pill.on{background:var(--ok-weak);color:var(--ok)}
  .dot{width:7px;height:7px;border-radius:50%;background:currentColor}
  main{display:grid;grid-template-columns:minmax(0,1.55fr) minmax(0,1fr);gap:18px;align-items:start}
  @media (max-width:820px){ main{grid-template-columns:1fr} }
  .card{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:20px 22px;box-shadow:var(--shadow)}
  .card + .card{margin-top:18px}
  .step{display:flex;gap:10px;align-items:baseline;margin:0 0 14px}
  .num{flex:none;width:21px;height:21px;border-radius:50%;background:var(--accent-weak);color:var(--accent);
    font-size:12px;font-weight:700;display:grid;place-items:center}
  .step h2{font-size:14.5px;margin:0;font-weight:650}
  .step p{margin:2px 0 0;color:var(--muted);font-size:12.5px}
  .providers{display:grid;grid-template-columns:1fr 1fr;gap:10px}
  @media (max-width:520px){ .providers{grid-template-columns:1fr} }
  .prov{border:1.5px solid var(--line);border-radius:12px;padding:13px 14px;cursor:pointer;
    background:transparent;text-align:left;color:inherit;font:inherit;transition:.15s ease;position:relative}
  .prov:hover{border-color:var(--muted)}
  .prov[aria-pressed="true"]{border-color:var(--accent);background:var(--accent-weak)}
  .prov b{display:block;font-size:14px;font-weight:640}
  .prov span{display:block;color:var(--muted);font-size:12px;margin-top:2px}
  .tick{position:absolute;top:11px;right:12px;color:var(--accent);font-size:13px;opacity:0}
  .prov[aria-pressed="true"] .tick{opacity:1}
  label.field{display:block;margin-top:14px}
  label.field > span{display:block;font-size:12.5px;font-weight:600;color:var(--muted);margin-bottom:6px}
  .inputrow{position:relative}
  .inputrow input{padding-right:60px}
  input{width:100%;padding:11px 13px;border-radius:10px;border:1.5px solid var(--line);
    background:var(--bg);color:var(--ink);font:inherit;font-size:14px;transition:.15s}
  input:focus{outline:none;border-color:var(--accent);background:var(--panel)}
  .reveal{position:absolute;right:8px;top:50%;transform:translateY(-50%);border:none;background:transparent;
    color:var(--muted);font-size:12px;font-weight:600;cursor:pointer;padding:4px 6px;border-radius:6px}
  .reveal:hover{color:var(--accent)}
  .hint{margin-top:10px;padding:10px 12px;border-radius:10px;background:var(--accent-weak);color:var(--accent);
    font-size:12.5px;display:flex;gap:8px}
  .hint b{font-weight:650}
  .actions{display:flex;gap:10px;margin-top:18px;flex-wrap:wrap}
  button.btn{border-radius:10px;padding:11px 18px;font:inherit;font-size:14px;font-weight:600;cursor:pointer;
    border:1.5px solid transparent;transition:.15s}
  .primary{background:var(--accent);color:#fff}
  .primary:hover{filter:brightness(1.07)}
  .ghost{background:transparent;color:var(--ink);border-color:var(--line)}
  .ghost:hover{border-color:var(--muted)}
  button.btn:disabled{opacity:.55;cursor:not-allowed}
  dl{margin:0;display:grid;grid-template-columns:auto 1fr;gap:9px 14px;font-size:13px}
  dt{color:var(--muted)}
  dd{margin:0;text-align:right;font-variant-numeric:tabular-nums;word-break:break-all}
  .side h3{font-size:13px;margin:0 0 12px;font-weight:650;color:var(--muted);letter-spacing:.3px;text-transform:uppercase}
  .log{margin-top:14px;font-size:12.5px;color:var(--muted);min-height:18px;white-space:pre-wrap}
  .log.ok{color:var(--ok)} .log.err{color:var(--warn)}
  .safe{margin-top:18px;border-top:1px dashed var(--line);padding-top:14px;font-size:12px;color:var(--muted)}
  .safe b{color:var(--ink);font-weight:600}
  .toast{position:fixed;left:50%;bottom:28px;transform:translate(-50%,20px);opacity:0;pointer-events:none;
    background:var(--ink);color:var(--panel);padding:11px 18px;border-radius:10px;font-size:13.5px;
    transition:.25s;box-shadow:var(--shadow);max-width:90vw}
  .toast.show{opacity:1;transform:translate(-50%,0)}
  .toast.err{background:var(--warn)}
  footer{max-width:960px;margin:22px auto 0;color:var(--muted);font-size:12px;text-align:center}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="mark">BB</div>
    <div>
      <h1>作业提醒 · 邮箱绑定</h1>
      <p class="sub">绑定一次，之后新作业和临近截止会发到你的邮箱</p>
    </div>
    <div class="pill" id="pill"><span class="dot"></span><span id="pillText">读取中</span></div>
  </header>

  <main>
    <div>
      <section class="card">
        <div class="step"><span class="num">1</span><div><h2>选择发信邮箱</h2>
          <p>用你自己的邮箱给自己发提醒，不需要额外的服务器</p></div></div>
        <div class="providers" id="providers"></div>

        <div class="step" style="margin-top:22px"><span class="num">2</span><div><h2>填写账号与凭据</h2>
          <p>网页登录密码不能用于发信，需要用可随时撤销的专用凭据</p></div></div>
        <label class="field"><span>邮箱地址</span>
          <input id="address" type="email" autocomplete="username" spellcheck="false" placeholder="选好服务商后填写">
        </label>
        <label class="field"><span id="credLabel">客户端专用密码 / 授权码</span>
          <div class="inputrow">
            <input id="secret" type="password" autocomplete="new-password" spellcheck="false" placeholder="粘贴专用凭据">
            <button class="reveal" id="reveal" type="button">显示</button>
          </div>
        </label>
        <div class="hint" id="hint"><span>ℹ️</span><span id="hintText">选择合适的服务商后，这里会显示获取凭据的路径。</span></div>

        <div class="actions">
          <button class="btn primary" id="saveTest">保存并发送测试邮件</button>
          <button class="btn ghost" id="saveOnly">只保存</button>
        </div>
      </section>
    </div>

    <div class="side">
      <section class="card">
        <h3>当前状态</h3>
        <dl>
          <dt>发件地址</dt><dd id="sAddr">未绑定</dd>
          <dt>发信服务</dt><dd id="sHost">—</dd>
          <dt>凭据存储</dt><dd id="sStore">系统凭据库</dd>
          <dt>追踪中的作业</dt><dd id="sTracked">0</dd>
          <dt>已提醒的截止</dt><dd id="sReminded">0</dd>
        </dl>
        <div class="log" id="log">等待操作</div>
      </section>

      <section class="card">
        <h3>立即检查一次</h3>
        <p style="margin:0 0 12px;font-size:12.5px;color:var(--muted)">
          读取 Blackboard 作业并与本地记录比对，有新增或 24 小时内截止的作业就发邮件。</p>
        <button class="btn ghost" id="check" style="width:100%">运行一次检查</button>
        <div class="safe">
          <b>密码只进系统凭据库。</b>页面仅监听 127.0.0.1 并需要本次启动的随机令牌，
          关闭终端即可失效；不会把密码写进任何文件或日志。
        </div>
      </section>
    </div>
  </main>
  <footer>ustc-bb-mcp · 本页面由本机进程临时提供，不联网、不上传任何数据</footer>
</div>
<div class="toast" id="toast"></div>

<script>
const TOKEN = new URLSearchParams(location.search).get("t") || "";
let state = {providers: [], provider: "ustc"};

function toast(msg, bad){
  const el = document.getElementById("toast");
  el.textContent = msg; el.className = "toast show" + (bad ? " err" : "");
  clearTimeout(el._t); el._t = setTimeout(() => el.className = "toast", 3200);
}
function log(msg, kind){
  const el = document.getElementById("log");
  el.textContent = msg; el.className = "log" + (kind ? " " + kind : "");
}
async function api(path, body){
  const res = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: {"Content-Type":"application/json", "X-Token": TOKEN},
    body: body === undefined ? undefined : JSON.stringify(body)
  });
  const data = await res.json().catch(() => ({message: "响应无法解析"}));
  if(!res.ok) throw new Error(data.message || ("HTTP " + res.status));
  return data;
}
function renderProviders(){
  const box = document.getElementById("providers");
  box.innerHTML = "";
  state.providers.forEach(p => {
    const b = document.createElement("button");
    b.type = "button"; b.className = "prov";
    b.setAttribute("aria-pressed", String(p.key === state.provider));
    b.innerHTML = `<b>${p.label}</b><span>${p.host}</span><span class="tick">✓</span>`;
    b.onclick = () => {
      state.provider = p.key;
      document.getElementById("address").placeholder = p.placeholder;
      document.getElementById("hintText").innerHTML =
        `在 <b>${p.hint}</b> 生成${p.credential}，填写后立即生效`;
      document.getElementById("credLabel").textContent = p.credential;
      renderProviders();
    };
    box.appendChild(b);
  });
}
function renderStatus(d){
  const on = d.configured;
  document.getElementById("pill").className = "pill" + (on ? " on" : "");
  document.getElementById("pillText").textContent = on ? "已绑定" : "未绑定";
  document.getElementById("sAddr").textContent = d.address || "未绑定";
  document.getElementById("sHost").textContent = d.address ? `${d.label} · ${d.host}:${d.port}` : "—";
  document.getElementById("sTracked").textContent = d.tracked;
  document.getElementById("sReminded").textContent = d.reminded;
}
async function load(){
  try{
    const d = await api("/api/status");
    state.providers = d.providers; state.provider = d.provider || "ustc";
    renderProviders();
    const p = d.providers.find(x => x.key === state.provider);
    if(p){
      document.getElementById("address").placeholder = p.placeholder;
      document.getElementById("credLabel").textContent = p.credential;
      document.getElementById("hintText").innerHTML =
        `在 <b>${p.hint}</b> 生成${p.credential}`;
    }
    if(d.address) document.getElementById("address").value = d.address;
    renderStatus(d);
    log("已连接本机服务", "ok");
  }catch(e){ log("无法连接本机服务：" + e.message, "err"); }
}
async function save(withTest){
  const address = document.getElementById("address").value.trim();
  const secret = document.getElementById("secret").value.trim();
  if(!address || !secret){ toast("请填写邮箱地址和凭据", true); return; }
  const buttons = [document.getElementById("saveTest"), document.getElementById("saveOnly")];
  buttons.forEach(b => b.disabled = true);
  log(withTest ? "正在绑定并发送测试邮件…" : "正在保存…");
  try{
    const d = await api("/api/bind", {address, password: secret});
    document.getElementById("secret").value = "";
    const s = await api("/api/status"); renderStatus(s);
    if(withTest){
      log("已绑定，正在发送测试邮件到 " + d.mail_address + " …");
      const r = await api("/api/test", {});
      log(`已绑定 ${d.mail_address}，测试邮件已投递（${r.host}:${r.port}）。请查收收件箱与垃圾邮件。`, "ok");
      toast("测试邮件已发送");
    }else{
      log(`已绑定 ${d.mail_address}（${d.label}）`, "ok"); toast("已保存");
    }
  }catch(e){ log(e.message, "err"); toast(e.message, true); }
  finally{ buttons.forEach(b => b.disabled = false); }
}
document.getElementById("saveTest").onclick = () => save(true);
document.getElementById("saveOnly").onclick = () => save(false);
document.getElementById("reveal").onclick = () => {
  const i = document.getElementById("secret");
  const show = i.type === "password";
  i.type = show ? "text" : "password";
  document.getElementById("reveal").textContent = show ? "隐藏" : "显示";
};
document.getElementById("check").onclick = async () => {
  const b = document.getElementById("check");
  b.disabled = true; log("正在读取 Blackboard 作业…");
  try{
    const r = await api("/api/check", {});
    log(`检查完成：共 ${r.assignments_checked} 个作业，新增 ${r.new_assignments} 个，`
        + `24 小时内截止 ${r.due_soon} 个，${r.mail_sent ? "邮件已发送" : "本次无需发信"}`,
        r.mail_sent ? "ok" : "");
    const s = await api("/api/status"); renderStatus(s);
  }catch(e){ log(e.message, "err"); }
  finally{ b.disabled = false; }
};
load();
</script>
</body>
</html>
"""
