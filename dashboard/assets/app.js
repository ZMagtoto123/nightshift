/* NIGHTSHIFT — vanilla JS, no build step, no frameworks.
   Data sources:
     - state/*.json + tasks.json  via raw.githubusercontent (CORS-open)
     - workflow runs              via api.github.com (public repos work tokenless)
     - control (dispatch/commit)  via api.github.com + your token            */

(() => {
  "use strict";

  const $ = (s) => document.querySelector(s);
  const QS = new URLSearchParams(location.search);
  const DEMO = QS.has("demo");

  /* ---------------- store / repo detection ---------------- */

  const LS = {
    get token() { return localStorage.getItem("ns_token") || ""; },
    set token(v) { v ? localStorage.setItem("ns_token", v) : localStorage.removeItem("ns_token"); },
    get repo() { return localStorage.getItem("ns_repo") || detectRepo(); },
    set repo(v) { localStorage.setItem("ns_repo", v.trim()); },
  };

  // github.io URLs encode owner/repo:  owner.github.io/repo/...  (project)
  // or owner.github.io/                (user site -> repo = owner.github.io)
  function detectRepo() {
    const h = location.hostname;
    if (h === "localhost" || h === "127.0.0.1" || h === "") return "";
    if (!h.endsWith(".github.io")) return "";
    const owner = h.slice(0, -".github.io".length);
    const seg = location.pathname.split("/").filter(Boolean)[0];
    return seg ? `${owner}/${seg}` : `${owner}/${h}`;
  }

  /* ---------------- api helpers ---------------- */

  async function api(path, opts = {}) {
    const headers = Object.assign({ Accept: "application/vnd.github+json" }, opts.headers || {});
    if (LS.token) headers.Authorization = `Bearer ${LS.token}`;
    const r = await fetch(`https://api.github.com${path}`, { ...opts, headers });
    if (!r.ok) {
      const body = await r.text().catch(() => "");
      const err = new Error(`${r.status} ${r.statusText}${body ? ` — ${body.slice(0, 140)}` : ""}`);
      err.status = r.status;
      throw err;
    }
    return r.status === 204 ? null : r.json();
  }

  async function rawFile(path) {
    const url = `https://raw.githubusercontent.com/${LS.repo}/HEAD/${path}?t=${Date.now()}`;
    const r = await fetch(url);
    if (!r.ok) throw Object.assign(new Error(`raw ${r.status}`), { status: r.status });
    return r.text();
  }

  async function dispatch(eventType, payload) {
    if (DEMO) throw new Error("demo mode — nothing is dispatched");
    if (!LS.token) throw new Error("no token — open settings");
    if (!LS.repo) throw new Error("no repo — open settings");
    return api(`/repos/${LS.repo}/dispatches`, {
      method: "POST",
      body: JSON.stringify({ event_type: eventType, client_payload: payload }),
    });
  }

  /* ---------------- small utils ---------------- */

  const fmtMoney = (v) =>
    v === null || v === undefined || isNaN(Number(v)) ? "—"
      : "$" + Number(v).toLocaleString("en-US", { maximumFractionDigits: 0 });

  const relTime = (iso) => {
    const ms = Date.now() - new Date(iso).getTime();
    if (isNaN(ms)) return "?";
    const m = Math.floor(ms / 60000);
    if (m < 1) return "just now";
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ${m % 60}m ago`;
    return `${Math.floor(h / 24)}d ${h % 24}h ago`;
  };

  const duration = (a, b) => {
    const s = Math.max(0, (new Date(b) - new Date(a)) / 1000);
    return s < 90 ? `${Math.round(s)}s` : `${Math.round(s / 60)}m`;
  };

  let toastTimer;
  function toast(msg, kind = "") {
    const el = $("#toast");
    el.textContent = msg;
    el.className = `toast show ${kind}`;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("show"), 4200);
  }

  async function guard(fn, okMsg) {
    try {
      await fn();
      if (okMsg) toast(okMsg, "good");
    } catch (e) {
      toast(e.message || String(e), "err");
    }
  }

  /* ---------------- masthead / clock / linking ---------------- */

  setInterval(() => {
    $("#utcClock").textContent =
      new Date().toISOString().slice(11, 19) + " UTC";
  }, 1000);

  function paintLink() {
    const repo = LS.repo;
    const chip = $("#repoChip");
    chip.textContent = repo || "not linked";
    chip.className = "chip" + (repo ? " linked" : "");
    $("#firstRun").classList.toggle("hidden", !!repo && !QS.has("demo") || DEMO);
  }

  /* ---------------- engine panel ---------------- */

  function setLed(state) { $("#ledLive").dataset.state = state; }

  async function loadStatus() {
    if (DEMO) { renderStatus(DEMO_DATA.status); return; }
    try {
      renderStatus(JSON.parse(await rawFile("state/status.json")));
    } catch (e) {
      setLed("off");
      $("#lastTick").textContent = "waiting for first cloud tick";
    }
  }

  const stat = (label, value, cls = "mid") =>
    `<div class="stat"><label>${label}</label><div class="${cls}">${value}</div></div>`;

  function renderStatus(s) {
    const ageMin = (Date.now() - new Date(s.ts).getTime()) / 60000;
    setLed(ageMin < 50 ? "ok" : ageMin < 120 ? "stale" : "bad");
    $("#lastTick").textContent = `last scheduler pass ${relTime(s.ts)}`;
    const ran = s.ran || [];
    const okCount = ran.filter((r) => r.ok).length;
    $("#statRow").innerHTML =
      stat("pipelines", s.checked ?? "—") +
      stat("ran this pass", ran.length) +
      stat("results", ran.length ? `${okCount}/${ran.length} ok` : "idle",
        "mid " + (ran.length ? (okCount === ran.length ? "good" : "bad") : "")) +
      stat("health", "OK", "good");
    renderActivity(s);
  }

  function renderActivity(s) {
    const t = $("#activityTable");
    const ran = s.ran || [];
    if (ran.length) {
      let html = `<thead><tr><th>pipeline</th><th>task</th><th>result</th><th>when</th></tr></thead><tbody>`;
      for (const r of ran) {
        html += `<tr><td>${r.pipeline ?? "?"}</td><td>${r.task ?? "?"}</td>
          <td class="${r.ok ? "pos-side" : "neg-side"}">${r.ok ? "ok" : "fail"}</td>
          <td>${relTime(s.ts)}</td></tr>`;
      }
      t.innerHTML = html + "</tbody>";
      return;
    }
    t.innerHTML = `<tbody><tr><td class="empty">no activity yet — schedules fire on their cron, flows run on demand</td></tr></tbody>`;
  }

  /* ---------------- runs panel ---------------- */

  const STATE_WORD = { success: "ok", failure: "bad", cancelled: "skip", skipped: "skip", timed_out: "bad" };

  async function loadRuns() {
    const list = $("#runsList");
    if (DEMO) { renderRuns(DEMO_DATA.runs); return; }
    try {
      const data = await api(`/repos/${LS.repo}/actions/runs?per_page=12`);
      renderRuns(data.workflow_runs || []);
    } catch (e) {
      list.innerHTML = `<div class="empty">runs unavailable (${e.status || ""} ${e.message})${
        !LS.token ? " — for a private repo, add a token in settings" : ""}</div>`;
    }
  }

  function renderRuns(runs) {
    const list = $("#runsList");
    list.innerHTML = "";
    $("#runsMeta").textContent = `${runs.length} recent`;
    if (!runs.length) { list.innerHTML = `<div class="empty">no runs yet — run <strong>bot</strong> once from the Actions tab</div>`; return; }
    for (const r of runs) {
      const kind = STATE_WORD[r.conclusion] || "busy";
      const state = r.status === "completed" ? (r.conclusion || "done") : r.status;
      const div = document.createElement("div");
      div.className = `row-item ${kind}`;
      div.innerHTML = `
        <span class="r-name">${r.name}</span>
        <span class="r-meta">${r.event} · ${relTime(r.run_started_at || r.created_at)} · ${duration(r.run_started_at || r.created_at, r.updated_at)}</span>
        <span class="r-state ${kind}">${state}</span>
        <a href="${r.html_url}" target="_blank" rel="noopener">open ↗</a>`;
      list.appendChild(div);
    }
  }

  /* ---------------- flows: no-code builder ---------------- */

  let LIB = {};
  let FLOWS = [];
  let curSteps = [];

  async function loadLibrary() {
    if (DEMO) { LIB = DEMO_DATA.library; return; }
    try {
      LIB = JSON.parse(await rawFile("actions/library.json"));
    } catch {
      LIB = {};
    }
  }

  async function loadFlows() {
    if (DEMO) { FLOWS = DEMO_DATA.flows; startBuilder(); return; }
    try {
      FLOWS = (JSON.parse(await rawFile("flows.json"))).flows || [];
    } catch {
      FLOWS = [];
    }
    startBuilder();
  }

  function startBuilder() {
    const sel = $("#flowSelect");
    sel.innerHTML = `<option value="">— choose a flow —</option>` +
      FLOWS.map((f) => `<option value="${f.name}">${f.name}</option>`).join("");
    if (!curSteps.length && FLOWS.length) editFlow(FLOWS[0].name);
    else if (!curSteps.length) newFlow();
  }

  function editFlow(name) {
    const f = FLOWS.find((x) => x.name === name);
    if (!f) return;
    $("#flowName").value = f.name;
    curSteps = JSON.parse(JSON.stringify(f.steps || []));
    renderSteps();
  }

  function newFlow() {
    $("#flowSelect").value = "";
    $("#flowName").value = "";
    curSteps = [];
    renderSteps();
  }

  let paletteIndex = null;
  function openPalette(i) {
    paletteIndex = i;
    const grid = $("#paletteGrid");
    grid.innerHTML = "";
    Object.entries(LIB).forEach(([name, spec]) => {
      const b = document.createElement("button");
      b.className = "palette-item";
      b.innerHTML = `<span class="pi-name">${name}</span>
        <span class="pi-desc">${spec.title || ""}</span>
        <span class="pi-where ${spec.where === "local" ? "local" : "cloud"}">${spec.where === "local" ? "your PC" : "cloud"}</span>`;
      b.onclick = () => {
        curSteps.splice(paletteIndex, 0, { action: name, params: {} });
        closePalette();
        renderSteps();
      };
      grid.appendChild(b);
    });
    $("#palette").classList.remove("hidden");
    $("#palette").scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
  function closePalette() { $("#palette").classList.add("hidden"); }
  $("#paletteClose").onclick = closePalette;

  const BLOCK_ICONS = {
    http_request: "⇄", download_file: "⤓", email_send: "✉", telegram_notify: "◈",
    youtube_upload: "▶", organize_folder: "▦", run_command: ">_", open_url: "↗",
    screenshot_folder: "▤", browser_job: "◉",
  };

  function renderSteps() {
    const box = $("#flowCanvas");
    box.innerHTML = "";
    if (!curSteps.length) {
      box.innerHTML = `<div class="empty">empty flow — hit ＋ add block and pick your first block</div>`;
      return;
    }
    curSteps.forEach((step, i) => {
      const spec = LIB[step.action] || { params: {}, where: "?", title: step.action };
      const isLocal = spec.where === "local";
      const card = document.createElement("div");
      card.className = `block-card ${isLocal ? "local-block" : "cloud-block"}`;
      card.innerHTML = `
        <div class="block-head">
          <span class="block-icon">${BLOCK_ICONS[step.action] || "□"}</span>
          <span class="block-title">${step.action}</span>
          <span class="block-tag">${isLocal ? "your pc" : "cloud"}</span>
          <span class="block-tools">
            <button class="btn ghost" data-up title="move up" ${i === 0 ? "disabled" : ""}>↑</button>
            <button class="btn ghost" data-down title="move down" ${i === curSteps.length - 1 ? "disabled" : ""}>↓</button>
            <button class="btn ghost" data-del title="remove">×</button>
          </span>
        </div>
        <div class="block-params"></div>
        <div class="block-outputs"><span class="lbl">outputs</span></div>`;

      card.querySelector("[data-del]").onclick = () => { curSteps.splice(i, 1); renderSteps(); };
      card.querySelector("[data-up]").onclick = () => {
        [curSteps[i - 1], curSteps[i]] = [curSteps[i], curSteps[i - 1]]; renderSteps();
      };
      card.querySelector("[data-down]").onclick = () => {
        [curSteps[i + 1], curSteps[i]] = [curSteps[i], curSteps[i + 1]]; renderSteps();
      };

      const pbox = card.querySelector(".block-params");
      Object.entries(spec.params || {}).forEach(([k, s]) => {
        const row = document.createElement("div");
        row.className = "prow";
        const val = curSteps[i].params?.[k] ?? s.default ?? "";
        const isJson = s.type === "json";
        row.innerHTML = `<label>${k}${s.required ? ' <span class="req">*</span>' : ""}</label>`;
        const input = document.createElement(isJson ? "textarea" : "input");
        if (isJson) input.value = typeof val === "string" ? val : JSON.stringify(val ?? {}, null, 0);
        else input.value = val;
        input.placeholder = s.hint || (isJson ? '{"key": "value"}' : "");
        input.dataset.param = k;
        row.appendChild(input);
        pbox.appendChild(row);
      });

      const obx = card.querySelector(".block-outputs");
      (spec.outputs || []).forEach((f) => {
        const chip = document.createElement("button");
        chip.className = "out-chip";
        chip.textContent = `{{step${i + 1}.${f}}}`;
        chip.title = "click to copy — paste into any later block's field";
        chip.onclick = () => {
          navigator.clipboard?.writeText(`{{step${i + 1}.${f}}}`);
          toast(`copied {{step${i + 1}.${f}}} — paste it in a later field`);
        };
        obx.appendChild(chip);
      });
      if (!spec.outputs?.length) obx.innerHTML += `<span class="note inline-note">no outputs</span>`;

      box.appendChild(card);
      if (i < curSteps.length - 1) {
        const conn = document.createElement("div");
        conn.className = "connector";
        box.appendChild(conn);
      }
    });
  }

  function collectFlow() {
    const name = $("#flowName").value.trim();
    if (!name) throw new Error("give the flow a name");
    const steps = curSteps.map((s, i) => {
      const box = $("#flowCanvas").querySelectorAll(".block-card")[i];
      const params = {};
      box.querySelectorAll("[data-param]").forEach((inp) => {
        let v = inp.value;
        if (inp.tagName === "TEXTAREA") {
          try { v = JSON.parse(v || "{}"); } catch { /* keep string */ }
        }
        params[inp.dataset.param] = v;
      });
      return { action: s.action, params };
    });
    return { name, steps };
  }

  function saveFlowsJson(updated) {
    const flows = FLOWS.slice();
    const idx = flows.findIndex((f) => f.name === updated.name);
    if (idx >= 0) flows[idx] = updated; else flows.push(updated);
    return JSON.stringify({ flows }, null, 2);
  }

  $("#flowAddStep").onclick = () => openPalette(curSteps.length);
  $("#flowNew").onclick = () => guard(() => { newFlow(); }, "blank flow — add blocks below");
  $("#flowSelect").onchange = (ev) => guard(() => { if (ev.target.value) editFlow(ev.target.value); });
  $("#flowRun").onclick = () => guard(async () => {
    const name = $("#flowName").value.trim();
    if (!name) throw new Error("give the flow a name first");
    await dispatch("run-task", { task: "flow", args: { flow: name } });
  }, "flow launched — watch runs / agent panel");

  $("#flowSave").onclick = () => guard(async () => {
    const flow = collectFlow();
    if (DEMO) throw new Error("demo mode — nothing is committed");
    if (!LS.token) throw new Error("no token — open settings");
    const cur = await api(`/repos/${LS.repo}/contents/flows.json`);
    await api(`/repos/${LS.repo}/contents/flows.json`, {
      method: "PUT",
      body: JSON.stringify({
        message: `flow: save ${flow.name} from nightshift`,
        content: btoa(unescape(encodeURIComponent(saveFlowsJson(flow)))),
        sha: cur.sha,
      }),
    });
    FLOWS = FLOWS.filter((f) => f.name !== flow.name).concat([flow]);
    startBuilder();
  }, "flow committed");

  /* ---------------- local agent panel ---------------- */

  async function loadAgent() {
    const el = $("#agentLog");
    if (DEMO) { renderAgent(DEMO_DATA.agentLog); return; }
    try {
      renderAgent(JSON.parse(await rawFile("state/agent_log.json")));
    } catch {
      el.innerHTML = `<div class="empty">no agent log yet — install the agent (card below) and run a local flow</div>`;
    }
  }

  function renderAgent(log) {
    const el = $("#agentLog");
    el.innerHTML = "";
    const rows = (log || []).slice(-8).reverse();
    rows.forEach((r) => {
      const div = document.createElement("div");
      div.className = `row-item ${r.ok ? "ok" : "bad"}`;
      div.innerHTML = `
        <span class="r-name">${r.action}</span>
        <span class="r-meta">${r.flow ?? ""} · ${relTime(r.ts)}${r.detail ? ` · ${String(r.detail).slice(0, 70)}` : ""}</span>
        <span class="r-state ${r.ok ? "ok" : "bad"}">${r.ok ? "ok" : "fail"}</span>`;
      el.appendChild(div);
    });
    if (!el.children.length) el.innerHTML = `<div class="empty">no jobs executed on your PC yet</div>`;
    const last = rows[0];
    if (last) {
      const age = (Date.now() - new Date(last.ts).getTime()) / 60000;
      setLed2(age < 60 ? "ok" : "stale");
      $("#agentMeta").textContent = `last job ${relTime(last.ts)}`;
    }
  }

  function setLed2(state) { $("#ledAgent").dataset.state = state; }

  /* ---------------- schedules panel ---------------- */

  async function loadPipelines() {
    const el = $("#schedList");
    if (DEMO) { renderPipelines(DEMO_DATA.pipelines); return; }
    try {
      const data = JSON.parse(await rawFile("pipelines.json"));
      renderPipelines(data.pipelines || []);
    } catch {
      el.innerHTML = `<div class="empty">pipelines.json not reachable yet</div>`;
    }
  }

  function renderPipelines(list) {
    const el = $("#schedList");
    el.innerHTML = "";
    if (!list.length) { el.innerHTML = `<div class="empty">no pipelines defined — add one in the PIPELINE panel</div>`; return; }
    for (const p of list) {
      const on = p.enabled !== false;
      const div = document.createElement("div");
      div.className = `row-item ${on ? "ok" : "skip"}`;
      div.innerHTML = `
        <span class="r-name">${p.name ?? "?"}</span>
        <span class="r-meta"><code>${p.cron ?? "?"}</code> → ${p.task ?? "?"}${
          p.args && Object.keys(p.args).length ? ` · ${JSON.stringify(p.args).slice(0, 80)}` : ""}</span>
        <span class="r-state ${on ? "ok" : "skip"}">${on ? "on" : "paused"}</span>`;
      el.appendChild(div);
    }
  }

  /* ---------------- tasks panel ---------------- */

  async function loadTasks() {
    const btns = $("#taskButtons");
    if (DEMO) {
      renderTaskButtons(DEMO_DATA.registry.tasks);
      renderTaskResults(DEMO_DATA.taskResults);
      return;
    }
    try {
      const reg = JSON.parse(await rawFile("tasks.json"));
      renderTaskButtons(reg.tasks || []);
    } catch {
      btns.innerHTML = `<div class="empty">tasks.json not reachable yet</div>`;
    }
    try {
      renderTaskResults(JSON.parse(await rawFile("state/tasks.json")));
    } catch {
      $("#taskResults").innerHTML = `<div class="empty">no task runs recorded yet</div>`;
    }
  }

  function renderTaskButtons(tasks) {
    const btns = $("#taskButtons");
    btns.innerHTML = "";
    tasks.filter((t) => t.type !== "browser").forEach((t) => {
      const b = document.createElement("button");
      b.className = "btn";
      b.textContent = t.name;
      b.title = t.description || "";
      b.onclick = () => guard(
        () => dispatch("run-task", { task: t.name, args: {} }),
        `task "${t.name}" launched — watch the runs panel`);
      btns.appendChild(b);
    });
    if (!btns.children.length) btns.innerHTML = `<div class="empty">no tasks defined</div>`;
  }

  function renderTaskResults(rows) {
    const el = $("#taskResults");
    el.innerHTML = "";
    (rows || []).slice(-8).reverse().forEach((r) => {
      const div = document.createElement("div");
      div.className = `row-item ${r.ok ? "ok" : "bad"}`;
      div.innerHTML = `
        <span class="r-name">${r.task}</span>
        <span class="r-meta">${relTime(r.started)}${r.seconds ? ` · ${r.seconds}s` : ""}${r.error ? ` · ${String(r.error).slice(0, 60)}` : ""}</span>
        <span class="r-state ${r.ok ? "ok" : "bad"}">${r.ok ? "ok" : "fail"}</span>`;
      el.appendChild(div);
    });
    if (!el.children.length) el.innerHTML = `<div class="empty">no task runs recorded yet</div>`;
  }

  /* ---------------- browser jobs ---------------- */

  let preset = "snapshot";
  $("#presetChips").addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-preset]");
    if (!b) return;
    preset = b.dataset.preset;
    $("#presetChips .on")?.classList.remove("on");
    b.classList.add("on");
  });

  $("#browserForm").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const url = $("#jobUrl").value.trim();
    if (!url) return;
    guard(
      () => dispatch("browser-job", { task: "browser", args: { url, preset, name: `dash-${preset}` } }),
      "browser job launched — screenshots land in the run's artifacts");
  });

  /* ---------------- pipeline editor ---------------- */

  let pipelineTarget = "tasks.json";
  function setPipelineTarget(t) {
    pipelineTarget = t;
    $("#ptTasks").classList.toggle("on", t === "tasks.json");
    $("#ptPipelines").classList.toggle("on", t === "pipelines.json");
    guard(loadPipeline);
  }
  $("#ptTasks").onclick = () => setPipelineTarget("tasks.json");
  $("#ptPipelines").onclick = () => setPipelineTarget("pipelines.json");

  async function loadPipeline() {
    try {
      $("#pipelineEditor").value = DEMO
        ? JSON.stringify(pipelineTarget === "tasks.json" ? DEMO_DATA.registry : { pipelines: DEMO_DATA.pipelines }, null, 2)
        : await rawFile(pipelineTarget);
    } catch (e) {
      $("#pipelineEditor").value = "";
      toast(`pipeline: can't read ${pipelineTarget} (${e.message})`, "err");
    }
  }

  $("#pipelineReload").onclick = () => guard(loadPipeline, "reloaded");

  $("#pipelineSave").onclick = () => guard(async () => {
    const content = $("#pipelineEditor").value;
    JSON.parse(content); // refuse to commit invalid JSON
    if (DEMO) throw new Error("demo mode — nothing is committed");
    if (!LS.token) throw new Error("no token — open settings");
    const cur = await api(`/repos/${LS.repo}/contents/${pipelineTarget}`);
    await api(`/repos/${LS.repo}/contents/${pipelineTarget}`, {
      method: "PUT",
      body: JSON.stringify({
        message: `pipeline: edit ${pipelineTarget} from nightshift`,
        content: btoa(unescape(encodeURIComponent(content))),
        sha: cur.sha,
      }),
    });
    await guard(loadTasks);
  }, "committed — new pipeline is live");

  /* ---------------- flow run shortcut is in the flows panel ---------------- */

  /* ---------------- settings drawer ---------------- */

  const drawer = $("#drawer");
  const openDrawer = () => {
    $("#repoInput").value = LS.repo || "";
    $("#tokenInput").value = LS.token;
    $("#linkStatus").textContent = LS.repo && LS.token ? "linked ✓" : LS.repo ? "repo set — token missing (control disabled)" : "not linked";
    drawer.classList.add("open");
    drawer.setAttribute("aria-hidden", "false");
  };
  const closeDrawer = () => { drawer.classList.remove("open"); drawer.setAttribute("aria-hidden", "true"); };

  $("#settingsBtn").onclick = openDrawer;
  $("#firstRunSettings").onclick = openDrawer;
  $("#drawerClose").onclick = closeDrawer;

  $("#saveSettings").onclick = () => {
    const repo = $("#repoInput").value.trim().replace(/^https?:\/\/github\.com\//i, "");
    if (repo && !/^[\w.-]+\/[\w.-]+$/.test(repo)) { toast("repo should look like owner/name", "err"); return; }
    LS.repo = repo;
    LS.token = $("#tokenInput").value.trim();
    paintLink();
    closeDrawer();
    refreshAll();
    toast(repo ? "linked — refreshing" : "cleared", "good");
  };

  $("#clearToken").onclick = () => {
    LS.token = "";
    $("#tokenInput").value = "";
    toast("token forgotten from this browser", "good");
  };

  /* ---------------- demo data ---------------- */

  const DEMO_DATA = {
    status: {
      ts: new Date().toISOString(), checked: 3,
      ran: [
        { pipeline: "daily-site-snapshot", task: "browser", ok: true },
        { pipeline: "hourly-uptime-watch", task: "browser", ok: true },
        { pipeline: "weekly-email-digest", task: "flow", ok: false },
      ],
    },
    registry: {
      version: 1,
      tasks: [
        { name: "flow", type: "script", description: "Run a flow from flows.json", run: ["python", "scripts/flow_runner.py", "--flow", "{flow}"] },
        { name: "browser", type: "browser", description: "Headless Chromium job" },
        { name: "script", type: "script", description: "Run a python file", run: ["python", "{path}"] },
      ],
    },
    pipelines: [
      { name: "daily-site-snapshot", cron: "30 13 * * 1-5", task: "browser", args: { url: "https://news.ycombinator.com", preset: "snapshot" }, enabled: true },
      { name: "hourly-uptime-watch", cron: "0 * * * *", task: "browser", args: { url: "https://github.com", preset: "uptime" }, enabled: true },
      { name: "morning-flow", cron: "0 8 * * 1-5", task: "flow", args: { flow: "morning-digest" }, enabled: true },
      { name: "sort-downloads-nightly", cron: "0 3 * * *", task: "flow", args: { flow: "sort-downloads" }, enabled: false },
    ],
    library: {
      http_request: { where: "any", title: "HTTP request (call any API)", outputs: ["status", "body"], params: { url: { type: "str", required: true }, method: { type: "str", default: "GET" } } },
      email_send: { where: "any", title: "Send an email (SMTP)", outputs: ["sent"], params: { to: { type: "str", required: true }, subject: { type: "str", required: true }, body: { type: "str", required: true } } },
      telegram_notify: { where: "any", title: "Send a Telegram message", outputs: ["sent"], params: { text: { type: "str", required: true } } },
      youtube_upload: { where: "local", title: "Upload a video file to YouTube", outputs: ["video_id", "url"], params: { file: { type: "str", required: true }, title: { type: "str", required: true }, privacy: { type: "str", default: "private" } } },
      organize_folder: { where: "local", title: "Organize a folder by file type", outputs: ["count"], params: { folder: { type: "str", required: true }, dry_run: { type: "str", default: "true" } } },
      run_command: { where: "local", title: "Run a shell command on your PC", outputs: ["exit", "stdout"], params: { command: { type: "str", required: true } } },
      open_url: { where: "local", title: "Open a URL / app on your PC", outputs: ["opened"], params: { url: { type: "str", required: true } } },
      browser_job: { where: "cloud", title: "Headless Chromium job", outputs: ["status"], params: { url: { type: "str", required: true } } },
      read_file: { where: "local", title: "Read a file from your PC", outputs: ["text", "bytes"], params: { path: { type: "str", required: true } } },
      write_file: { where: "local", title: "Write / create a file on your PC", outputs: ["path", "bytes"], params: { path: { type: "str", required: true }, content: { type: "str", default: "" } } },
      find_files: { where: "local", title: "Find files on your PC (search a folder)", outputs: ["count", "files"], params: { folder: { type: "str", required: true }, pattern: { type: "str", default: "*" } } },
      browser_control: { where: "local", title: "Control a browser on your PC (click, type, screenshot)", outputs: ["extracted", "screenshots"], params: { url: { type: "str", required: true }, steps: { type: "json", default: "[]" } } },
      ai_chat: { where: "any", title: "Talk to an AI (GPT / Gemini / any OpenAI-compatible API)", outputs: ["reply"], params: { prompt: { type: "str", required: true }, model: { type: "str", default: "" } } },
    },
    flows: [
      { name: "morning-digest", steps: [{ action: "http_request", params: { url: "https://hacker-news.firebaseio.com/v0/topstories.json" } }, { action: "telegram_notify", params: { text: "Top HN: {{step1.body}}" } }] },
      { name: "publish-video", steps: [{ action: "youtube_upload", params: { file: "{{flow.file}}", title: "{{flow.title}}" } }, { action: "telegram_notify", params: { text: "Uploaded! {{step1.url}}" } }] },
    ],
    agentLog: [
      { action: "youtube_upload", flow: "publish-video", ok: true, ts: new Date(Date.now() - 3600000).toISOString(), detail: "https://youtu.be/dQw4w9WgXcQ" },
      { action: "organize_folder", flow: "sort-downloads", ok: false, ts: new Date(Date.now() - 86400000).toISOString(), detail: "folder not found" },
    ],
    taskResults: [
      { task: "flow", ok: true, started: new Date(Date.now() - 3600000).toISOString(), seconds: 12 },
      { task: "browser", ok: true, started: new Date(Date.now() - 7200000).toISOString(), seconds: 31 },
      { task: "script", ok: false, started: new Date(Date.now() - 10800000).toISOString(), seconds: 2, error: "file not found" },
    ],
    runs: [
      { name: "bot", event: "schedule", status: "completed", conclusion: "success", run_started_at: new Date(Date.now() - 900000).toISOString(), updated_at: new Date(Date.now() - 840000).toISOString(), created_at: new Date().toISOString(), html_url: "#" },
      { name: "bot", event: "schedule", status: "completed", conclusion: "success", run_started_at: new Date(Date.now() - 3600000).toISOString(), updated_at: new Date(Date.now() - 3540000).toISOString(), created_at: new Date().toISOString(), html_url: "#" },
      { name: "tasks", event: "repository_dispatch", status: "completed", conclusion: "failure", run_started_at: new Date(Date.now() - 7200000).toISOString(), updated_at: new Date(Date.now() - 7080000).toISOString(), created_at: new Date().toISOString(), html_url: "#" },
      { name: "bot", event: "workflow_dispatch", status: "in_progress", conclusion: null, run_started_at: new Date(Date.now() - 60000).toISOString(), updated_at: new Date().toISOString(), created_at: new Date().toISOString(), html_url: "#" },
    ],
  };

  /* ---------------- login gate ---------------- */

  const AUTH_USER = "@esc3luS";
  const AUTH_PASS = "@esc3luS";

  function authed() { return sessionStorage.getItem("ns_auth") === "1"; }

  function applyGate() {
    $("#loginGate").classList.toggle("hidden", authed());
  }

  function tryLogin() {
    const u = $("#loginUser").value.trim();
    const p = $("#loginPass").value;
    if (u === AUTH_USER && p === AUTH_PASS) {
      sessionStorage.setItem("ns_auth", "1");
      applyGate();
      toast("workspace unlocked", "good");
    } else {
      sessionStorage.removeItem("ns_auth");
      applyGate();
      $("#loginErr").classList.remove("hidden");
      const card = $("#loginCard");
      card.classList.remove("shake");
      void card.offsetWidth; // restart animation
      card.classList.add("shake");
    }
  }

  $("#loginBtn").onclick = tryLogin;
  $("#loginUser").addEventListener("keydown", (e) => { if (e.key === "Enter") tryLogin(); });
  $("#loginPass").addEventListener("keydown", (e) => { if (e.key === "Enter") tryLogin(); });

  $("#lockBtn").onclick = () => {
    sessionStorage.removeItem("ns_auth");
    applyGate();
    $("#loginUser").value = "";
    $("#loginPass").value = "";
    $("#loginErr").classList.add("hidden");
  };

  applyGate();

  /* ---------------- boot ---------------- */

  function refreshAll() {
    paintLink();
    loadStatus();
    loadRuns();
    loadTasks();
    loadPipelines();
    loadAgent();
    loadLibrary().then(loadFlows);
    loadPipeline();
  }

  if (DEMO) $("#demoBadge").classList.remove("hidden");
  paintLink();
  refreshAll();
  setInterval(loadStatus, 60 * 1000);
  setInterval(loadRuns, 90 * 1000);
})();
