/* ============================================================
   MCP Secure Console — live streaming client
   Consumes Server-Sent Events from POST /api/v1/execute/stream
   and lights up the circuit pipeline gate-by-gate in real time.
   ============================================================ */
(function () {
  "use strict";

  // ============ Data bootstrap ============
  const usersData = JSON.parse(
    document.getElementById("users-data").textContent || "[]"
  );
  const usersByName = {};
  for (const u of usersData) usersByName[u.username] = u;

  const form = document.getElementById("execute-form");
  const usernameSelect = document.getElementById("username");
  const promptInput = document.getElementById("prompt");
  const submitBtn = document.getElementById("submit-btn");
  const resultContainer = document.getElementById("result-container");
  const permPreview = document.getElementById("permission-preview");

  // The five pipeline gates, in order. glyph shows while pending/running;
  // it swaps to ✓ / ✕ as each gate resolves.
  const GATES = [
    { key: "tool-selection", label: "Tool Select", glyph: "✦" },
    { key: "rbac",           label: "RBAC",        glyph: "⬡" },
    { key: "intent",         label: "Intent",      glyph: "≈" },
    { key: "policy",         label: "Policy",      glyph: "❖" },
    { key: "execution",      label: "Execute",     glyph: "▷" },
  ];

  // ============ Helpers ============
  function escapeHtml(s) {
    if (s === null || s === undefined) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function stageDisplayLabel(stage) {
    const m = {
      success: "all gates passed",
      rbac: "blocked at RBAC",
      intent: "blocked at intent alignment",
      policy: "blocked by policy rule",
      "tool-selection": "no matching tool",
      system: "execution error",
    };
    return m[stage] || stage || "unknown";
  }

  // ============ Permission preview ============
  function renderPermissions() {
    const u = usersByName[usernameSelect.value];
    if (!u) { permPreview.innerHTML = ""; return; }
    const role = u.role || "no role";
    const perms = u.permissions || [];
    const chips = perms.length === 0
      ? '<span class="perm-chip empty">no permissions</span>'
      : perms.map((p) => `<span class="perm-chip">${escapeHtml(p)}</span>`).join("");
    permPreview.innerHTML =
      `<span>Role <strong style="color:var(--text)">${escapeHtml(role)}</strong> grants:</span>${chips}`;
  }
  usernameSelect.addEventListener("change", renderPermissions);
  renderPermissions();

  // ============ Sample-prompt chips ============
  const sampleWrap = document.getElementById("sample-prompts");
  if (sampleWrap) {
    sampleWrap.addEventListener("click", (e) => {
      const chip = e.target.closest(".prompt-chip");
      if (!chip) return;
      promptInput.value = chip.getAttribute("data-prompt") || "";
      promptInput.focus();
    });
  }

  // ============ Pipeline DOM ============
  function buildScaffold() {
    const gateHtml = GATES.map((g, i) => {
      const gate = `
        <div class="gate" data-key="${g.key}" data-status="pending">
          <div class="gate-orb"><span class="gate-icon">${g.glyph}</span></div>
          <div class="gate-label">${g.label}</div>
          <div class="gate-sub"></div>
        </div>`;
      const channel = i < GATES.length - 1
        ? `<div class="channel" data-idx="${i}"></div>` : "";
      return gate + channel;
    }).join("");

    resultContainer.innerHTML = `
      <div class="card">
        <div id="badge-slot">
          <div class="decision-badge running">
            <div class="decision-icon">⟳</div>
            <div class="decision-text">
              <div class="decision-label">RUNNING</div>
              <div class="decision-stage">streaming through the policy pipeline</div>
            </div>
          </div>
        </div>
        <div class="pipeline">${gateHtml}</div>
        <div id="outcome-slot"></div>
        <div id="meta-slot"></div>
      </div>`;
  }

  function setGate(key, status) {
    const gate = resultContainer.querySelector(`.gate[data-key="${key}"]`);
    if (!gate) return;
    const def = GATES.find((g) => g.key === key);
    const idx = GATES.findIndex((g) => g.key === key);
    gate.setAttribute("data-status", status);

    const icon = gate.querySelector(".gate-icon");
    const sub = gate.querySelector(".gate-sub");
    if (status === "ok") { icon.textContent = "✓"; sub.textContent = "pass"; }
    else if (status === "fail") { icon.textContent = "✕"; sub.textContent = "blocked"; }
    else if (status === "running") { icon.textContent = def.glyph; sub.textContent = "···"; }
    else { icon.textContent = def.glyph; sub.textContent = ""; }

    // Advance the energy channel as gates pass.
    if (status === "ok") {
      const ch = resultContainer.querySelector(`.channel[data-idx="${idx}"]`);
      if (ch) ch.setAttribute("data-fill", "ok");
    } else if (status === "running" && idx > 0) {
      const prev = resultContainer.querySelector(`.channel[data-idx="${idx - 1}"]`);
      if (prev && prev.getAttribute("data-fill") !== "ok") prev.setAttribute("data-fill", "run");
    }
  }

  // ============ Result rendering ============
  function isPlainObject(v) { return v !== null && typeof v === "object" && !Array.isArray(v); }
  function formatCell(v) {
    if (v === null || v === undefined) return "—";
    if (typeof v === "object") return JSON.stringify(v);
    return String(v);
  }

  function buildTableHtml(output) {
    let rows = null;
    if (Array.isArray(output) && output.length && output.every(isPlainObject)) {
      rows = output;
    } else if (isPlainObject(output) &&
      Object.values(output).every((v) => typeof v !== "object" || v === null)) {
      rows = [output];
    }
    if (!rows) return "";
    const cols = [];
    rows.forEach((r) => Object.keys(r).forEach((k) => { if (!cols.includes(k)) cols.push(k); }));
    const head = cols.map((c) => `<th>${escapeHtml(c)}</th>`).join("");
    const body = rows.map((r) =>
      `<tr>${cols.map((c) => `<td>${escapeHtml(formatCell(r[c]))}</td>`).join("")}</tr>`
    ).join("");
    const label = rows.length === 1 ? "1 record" : `${rows.length} records`;
    return `
      <div class="result-table-wrap">
        <div class="result-table-label">Results — ${label}</div>
        <table class="data-table">
          <thead><tr>${head}</tr></thead>
          <tbody>${body}</tbody>
        </table>
      </div>`;
  }

  function renderResult(data) {
    const isAllow = data.policy_decision === "ALLOW";
    const cls = isAllow ? "allow" : "deny";
    const icon = isAllow ? "✓" : "✕";

    const badgeSlot = document.getElementById("badge-slot");
    if (badgeSlot) {
      badgeSlot.innerHTML = `
        <div class="decision-badge ${cls}">
          <div class="decision-icon">${icon}</div>
          <div class="decision-text">
            <div class="decision-label">${escapeHtml(data.policy_decision)}</div>
            <div class="decision-stage">${escapeHtml(stageDisplayLabel(data.authorization_stage))}</div>
          </div>
        </div>`;
    }

    let outcome = "";
    if (isAllow) {
      if (data.human_summary) {
        outcome += `
          <div class="answer" dir="auto">
            <div class="answer-label">Answer</div>
            <div class="answer-text">${escapeHtml(data.human_summary)}</div>
          </div>`;
      }
      outcome += buildTableHtml(data.tool_output);
      outcome += `
        <details class="raw-output">
          <summary>Raw tool output (JSON)</summary>
          <pre>${escapeHtml(JSON.stringify(data.tool_output, null, 2))}</pre>
        </details>`;
    } else {
      outcome = `
        <div class="error-panel" dir="auto">
          <div class="error-label">Reason</div>
          <div class="error-text">${escapeHtml(data.error_message || "(no reason returned)")}</div>
        </div>`;
    }
    const outcomeSlot = document.getElementById("outcome-slot");
    if (outcomeSlot) outcomeSlot.innerHTML = outcome;

    const metaSlot = document.getElementById("meta-slot");
    if (metaSlot) {
      const argsJson = JSON.stringify(data.arguments || {}, null, 2);
      metaSlot.innerHTML = `
        <details class="meta-details">
          <summary>Request details</summary>
          <div class="meta-grid">
            <div class="key">User</div>       <div>${escapeHtml(data.username)}</div>
            <div class="key">Prompt</div>     <div dir="auto">${escapeHtml(data.prompt)}</div>
            <div class="key">Tool chosen</div><div><code>${escapeHtml(data.tool_name || "(none)")}</code></div>
            <div class="key">Arguments</div>  <div><code>${escapeHtml(argsJson)}</code></div>
            <div class="key">Stage</div>      <div>${escapeHtml(data.authorization_stage)}</div>
          </div>
        </details>`;
    }
  }

  function renderTransportError(message) {
    resultContainer.innerHTML = `
      <div class="card">
        <div class="transport-error">
          <strong>Request failed:</strong> ${escapeHtml(message)}
        </div>
      </div>`;
  }

  // ============ SSE stream handling ============
  function handleEvent(evt) {
    if (evt.type === "stage") setGate(evt.key, evt.status);
    else if (evt.type === "result") renderResult(evt);
  }

  async function streamRequest(payload) {
    const resp = await fetch("/api/v1/execute/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!resp.ok || !resp.body) {
      let detail = `HTTP ${resp.status}`;
      try {
        const err = await resp.json();
        if (err && err.detail) detail += ` — ${JSON.stringify(err.detail)}`;
      } catch (_) { /* non-JSON */ }
      throw new Error(detail);
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    let gotResult = false;

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });

      let sep;
      while ((sep = buf.indexOf("\n\n")) >= 0) {
        const frame = buf.slice(0, sep);
        buf = buf.slice(sep + 2);
        const line = frame.split("\n").find((l) => l.startsWith("data:"));
        if (!line) continue;
        try {
          const evt = JSON.parse(line.slice(5).trim());
          if (evt.type === "result") gotResult = true;
          handleEvent(evt);
        } catch (_) { /* skip malformed frame */ }
      }
    }
    if (!gotResult) throw new Error("Stream ended before a result was received.");
  }

  // ============ Submit ============
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const payload = {
      username: usernameSelect.value,
      prompt: promptInput.value,
    };
    submitBtn.disabled = true;
    submitBtn.textContent = "Running…";
    buildScaffold();

    try {
      await streamRequest(payload);
    } catch (err) {
      renderTransportError(err.message || String(err));
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = "Run secure request";
    }
  });
})();