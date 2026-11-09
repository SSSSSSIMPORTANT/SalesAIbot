const handoffReasons = {
  refund_request: "退款办理",
  complaint: "客户投诉",
  payment_dispute: "付款争议",
  model_unavailable: "建议生成失败",
  other: "其他人工处理",
};

function createHandoffPanel() {
  const panel = byId("handoff-panel");
  const list = byId("handoff-list");
  const feedback = byId("handoff-feedback");
  const form = byId("handoff-form");
  const reason = byId("handoff-reason");
  const submit = byId("handoff-submit");
  const cancel = byId("handoff-cancel");
  let active = null;
  reason.replaceChildren(...Object.entries(handoffReasons).map(([value, label]) => new Option(label, value)));

  function taskURL(state, messageId) {
    return `${conversationURL(state.conversationId)}/messages/${messageId}/handoff`;
  }

  function put(url, body) {
    return getJSON(url, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(15000),
    });
  }

  function draw(state) {
    const tasks = state.tasks;
    const pending = tasks?.filter(task => task.status === "pending").length ?? 0;
    byId("handoff-count").textContent = tasks ? `待处理 ${pending}` : "";
    form.hidden = !state.sourceMessageId;
    submit.disabled = cancel.disabled = reason.disabled = state.creating;
    const cards = new Map();
    for (const task of tasks ?? []) {
      const previous = state.cards.get(task.source_message_id);
      const card = previous?.task === task ? previous : { task, node: renderTask(state, task) };
      cards.set(task.source_message_id, card);
    }
    state.cards = cards;
    list.replaceChildren(...Array.from(cards.values(), card => card.node));
    const text = tasks === null ? "暂时无法读取人工任务，请刷新工作台。" :
      tasks.length ? "" : "当前会话还没有人工任务。";
    showFeedback(feedback, text, tasks === null);
  }

  function remember(state, task) {
    state.tasks = [
      task,
      ...state.tasks.filter(row => row.source_message_id !== task.source_message_id),
    ].sort((a, b) => (
      Number(a.status === "resolved") - Number(b.status === "resolved") ||
      b.created_at.localeCompare(a.created_at)
    ));
  }

  async function reload(state) {
    const tasks = await getJSON(`${conversationURL(state.conversationId)}/handoffs`);
    if (active !== state) return;
    state.tasks = tasks;
    draw(state);
  }

  function renderTask(state, task) {
    const resolved = task.status === "resolved";
    const card = createCard(
      "human",
      `${handoffReasons[task.reason]} · ${resolved ? "已处理" : "待处理"}`,
      task.created_at,
      task.resolution || "等待销售跟进。",
      `来源客户消息 #${task.source_message_id}`,
    );
    if (resolved) return card;

    const details = element("details", "handoff-resolution");
    details.append(element("summary", "", "记录处理结果"));
    const resolveForm = element("form", "workbench-form");
    const input = element("textarea", "");
    input.rows = 2;
    input.maxLength = 500;
    input.required = true;
    input.setAttribute("aria-label", "处理结果");
    const button = element("button", "primary-button", "确认完成");
    button.type = "submit";
    const status = element("p", "feedback");
    status.setAttribute("role", "status");
    status.hidden = true;
    resolveForm.append(input, button, status);
    details.append(resolveForm);
    card.append(details);
    resolveForm.addEventListener("submit", async event => {
      event.preventDefault();
      const resolution = input.value.trim();
      if (active !== state || button.disabled || !resolution) return;
      button.disabled = input.readOnly = true;
      try {
        const saved = await put(`${taskURL(state, task.source_message_id)}/resolution`, { resolution });
        if (active !== state) return;
        remember(state, saved);
        draw(state);
        showFeedback(feedback, "处理结果已保存。");
      } catch (error) {
        if (active !== state) return;
        if (error.detail?.code === "handoff_already_resolved") {
          try {
            await reload(state);
            if (active === state) showFeedback(feedback, "该任务已有处理结果，列表已更新。");
            return;
          } catch {}
        }
        showFeedback(status, "暂时无法确认处理结果，请用相同内容重试。", true);
      } finally {
        button.disabled = input.readOnly = false;
      }
    });
    return card;
  }

  function clear() {
    active = null;
    panel.hidden = form.hidden = true;
    panel.open = false;
    list.replaceChildren();
    showFeedback(feedback, "");
  }

  function load(conversationId, tasks) {
    active = { conversationId, tasks, cards: new Map(), sourceMessageId: null, creating: false };
    panel.hidden = false;
    draw(active);
  }

  function open(messageId, suggestedReason = "other") {
    if (!active || active.creating) return;
    panel.open = true;
    if (active.tasks !== null && !active.tasks.some(task => task.source_message_id === messageId)) {
      active.sourceMessageId = messageId;
      reason.value = handoffReasons[suggestedReason] ? suggestedReason : "other";
      byId("handoff-source").textContent = `来源客户消息 #${messageId}`;
      form.hidden = false;
      reason.focus();
    } else {
      active.sourceMessageId = null;
      form.hidden = true;
      panel.querySelector("summary").focus();
    }
    panel.scrollIntoView({ block: "nearest" });
  }

  cancel.addEventListener("click", () => {
    if (!active || active.creating) return;
    active.sourceMessageId = null;
    form.hidden = true;
  });

  form.addEventListener("submit", async event => {
    event.preventDefault();
    const state = active;
    if (!state?.sourceMessageId || state.creating || state.tasks === null) return;
    const messageId = state.sourceMessageId;
    state.creating = true;
    submit.disabled = cancel.disabled = reason.disabled = true;
    try {
      const task = await put(taskURL(state, messageId), { reason: reason.value });
      if (active !== state) return;
      remember(state, task);
      state.sourceMessageId = null;
      showFeedback(feedback, "人工任务已记录。");
    } catch (error) {
      if (active !== state) return;
      if (error.detail?.code === "handoff_already_exists") {
        try {
          state.sourceMessageId = null;
          await reload(state);
          if (active === state) showFeedback(feedback, "这条客户消息已有人工任务。");
          return;
        } catch {}
      }
      showFeedback(feedback, "暂时无法确认任务是否已创建，请用相同原因重试。", true);
    } finally {
      state.creating = false;
      if (active === state) {
        const notice = feedback.textContent;
        const isError = feedback.dataset.error === "true";
        draw(state);
        showFeedback(feedback, notice, isError);
      }
    }
  });

  return { clear, load, open };
}
