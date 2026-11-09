function createSuggestionOutcome({ url, state, isActive, redraw }) {
  const labels = {
    unknown: "结果未知",
    copied: "已复制",
    abandoned: "已放弃",
    reported_sent: "已补录发送",
  };
  const panel = element("details", "suggestion-outcome");
  const summary = element("summary", "", "使用结果");
  const result = element("p", "feedback");
  result.setAttribute("role", "status");
  const reasonNote = element("p", "card-note");
  const retryRead = element("button", "secondary-button", "重试读取");
  const abandon = element("button", "secondary-button", "放弃建议");
  const form = element("form", "workbench-form");
  const label = element("label", "", "放弃原因");
  const reason = element("textarea", "");
  reason.rows = 2;
  reason.maxLength = 300;
  reason.required = true;
  reason.value = state.pendingAbandonReason ?? "";
  const controls = element("div", "actions");
  const submit = element("button", "primary-button", "确认放弃");
  const cancel = element("button", "secondary-button", "取消");
  retryRead.type = abandon.type = cancel.type = "button";
  submit.type = "submit";
  label.append(reason);
  controls.append(submit, cancel);
  form.append(label, controls);
  panel.append(summary, result, reasonNote, retryRead, abandon, form);

  let outcome = null;
  let readRequest = 0;
  let reading = false;
  let readError = false;
  let editing = Boolean(state.pendingAbandonReason);
  const active = () => panel.isConnected && isActive();

  function draw() {
    const abandoned = Boolean(state.abandonment);
    const sent = outcome?.status === "reported_sent";
    const pending = Boolean(state.pendingAbandonReason);
    const status = sent ? "reported_sent" : abandoned ? "abandoned" : outcome?.status;
    summary.textContent = status ? `使用结果 · ${labels[status]}` : "使用结果";

    let details = "";
    if (outcome) {
      const sentMessages = outcome.reported_messages;
      const verbatim = sentMessages.filter(row => row.adoption_mode === "verbatim").length;
      details = `复制 ${outcome.copy_count} 次 · 已补录 ${sentMessages.length} 条`;
      if (sentMessages.length) details += `（原样 ${verbatim} · 改写 ${sentMessages.length - verbatim}）`;
    }
    if (reading) details = "正在读取使用结果…";
    if (readError) details = "暂时无法读取使用结果。";
    showFeedback(result, details, readError);
    showFeedback(reasonNote, abandoned ? `放弃原因：${state.abandonment.reason}` : "");
    retryRead.hidden = !readError;
    const canAbandon = !abandoned && (pending || (outcome && !sent && !readError));
    abandon.hidden = !canAbandon || editing;
    abandon.disabled = state.busy || reading;
    form.hidden = !canAbandon || !editing;
    reason.readOnly = state.busy || pending;
    submit.disabled = state.busy || reading || !reason.value.trim();
    submit.textContent = pending ? "重试放弃" : "确认放弃";
    cancel.disabled = state.busy || pending;
  }

  async function refresh() {
    if (!active() || (!panel.open && !outcome)) return;
    const requestId = ++readRequest;
    reading = true;
    readError = false;
    draw();
    try {
      const data = await getJSON(`${url}/outcome`);
      if (!active() || requestId !== readRequest) return;
      outcome = data;
      if (data.abandonment) {
        state.abandonment = data.abandonment;
        state.pendingAbandonReason = null;
        editing = false;
      }
    } catch {
      if (active() && requestId === readRequest) readError = true;
    } finally {
      if (requestId === readRequest) {
        reading = false;
        if (active()) redraw();
      }
    }
  }

  async function save(event) {
    event.preventDefault();
    if (!active() || form.hidden || submit.disabled) return;
    state.pendingAbandonReason ??= reason.value.trim();
    state.busy = true;
    state.feedback = "正在记录放弃…";
    state.error = false;
    redraw();
    try {
      state.abandonment = await getJSON(`${url}/abandonment`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: state.pendingAbandonReason }),
        signal: AbortSignal.timeout(15000),
      });
      state.pendingAbandonReason = null;
      editing = false;
      state.feedback = "已记录放弃。";
      await refresh();
    } catch (error) {
      state.error = true;
      if ([404, 409, 422].includes(error.status)) {
        state.pendingAbandonReason = null;
        state.feedback = error.detail?.code === "suggestion_already_reported_sent"
          ? "这条建议已有补录发送记录。"
          : error.detail?.code === "abandonment_already_recorded"
            ? "这条建议已有放弃记录。"
            : "放弃请求未通过，请检查原因和当前建议。";
        await refresh();
      } else {
        state.feedback = "暂时无法确认放弃结果，请点击「重试放弃」。";
      }
    } finally {
      state.busy = false;
      redraw();
    }
  }

  panel.addEventListener("toggle", () => {
    if (!active()) return;
    state.outcomeOpen = panel.open;
    if (panel.open && !reading) return refresh();
  });
  panel.open = Boolean(state.outcomeOpen);
  retryRead.addEventListener("click", refresh);
  abandon.addEventListener("click", () => {
    editing = true;
    draw();
    reason.focus();
  });
  cancel.addEventListener("click", () => {
    editing = false;
    reason.value = "";
    draw();
    abandon.focus();
  });
  reason.addEventListener("input", draw);
  form.addEventListener("submit", save);
  return { panel, draw, refresh };
}
