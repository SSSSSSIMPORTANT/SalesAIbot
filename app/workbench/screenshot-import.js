function createScreenshotImport({ getContext, request, requestJSON, refreshDetails }) {
  const panel = byId("screenshot-import");
  const fileInput = byId("screenshot-file");
  const preview = byId("screenshot-preview");
  const transcribeButton = byId("screenshot-transcribe");
  const clearButton = byId("screenshot-clear");
  const confirmButton = byId("screenshot-confirm");
  const feedback = byId("screenshot-feedback");
  const candidates = byId("screenshot-candidates");
  const lines = byId("screenshot-lines");
  const actors = [
    ["customer", "客户"],
    ["human", "人工销售"],
    ["unknown", "待确认"],
  ];
  const pendingImports = new Map();
  let selection = null;
  let activeOperatorId = null;
  let activeConversationId = null;

  function confirmedLines() {
    const edited = selection?.rows?.map(({ actor, body }) => ({
      actor: actor.value,
      text: body.value.trim(),
    }));
    if (!edited?.length || !edited.every(line =>
      ["customer", "human"].includes(line.actor) &&
      line.text && Array.from(line.text).length <= 2000
    )) return null;
    return edited;
  }

  function renderControls() {
    const { operatorId, conversationId, version } = getContext();
    const available = Boolean(operatorId && conversationId && version !== null);
    const pending = pendingImports.get(conversationId);
    panel.hidden = !available;
    fileInput.disabled = !available || Boolean(pending);
    clearButton.disabled = !available || Boolean(pending) || (!selection && feedback.hidden);
    transcribeButton.disabled = !available || Boolean(pending) || !selection?.previewURL ||
      Boolean(selection.transcribing || selection.versionConflict || selection.transcribed);
    confirmButton.disabled = !available || (pending
      ? pending.busy
      : Boolean(selection?.versionConflict) || !confirmedLines());
    confirmButton.textContent = pending
      ? (pending.busy ? "正在导入…" : "重试导入")
      : "确认导入";
    for (const { actor, body } of selection?.rows ?? []) {
      actor.disabled = body.readOnly = Boolean(pending);
    }
  }

  function reset({ close = false, clearInput = true } = {}) {
    const previous = selection;
    selection = null;
    previous?.controller?.abort();
    preview.hidden = true;
    preview.removeAttribute("src");
    if (previous?.previewURL) URL.revokeObjectURL(previous.previewURL);
    if (clearInput) fileInput.value = "";
    candidates.hidden = true;
    lines.replaceChildren();
    showFeedback(feedback, "");
    if (close) panel.open = false;
    renderControls();
  }

  function renderContext() {
    const { operatorId, conversationId, version } = getContext();
    if (operatorId !== activeOperatorId || conversationId !== activeConversationId) {
      if (operatorId !== activeOperatorId) pendingImports.clear();
      activeOperatorId = operatorId;
      activeConversationId = conversationId;
      reset({ close: true });
    }
    const pending = pendingImports.get(conversationId);
    if (selection && version !== null && version !== selection.version && !pending) {
      reset({ close: true });
    }
    if (pending && version !== null) {
      if (!selection) {
        selection = {
          ...getContext(),
          version: pending.body.based_on_version,
          transcribed: true,
        };
        renderLines(selection, pending.body.lines);
        panel.open = true;
      }
      showFeedback(feedback, pending.busy
        ? "正在保存已核对的消息…"
        : "暂时无法确认导入结果。请在当前页面点击「重试导入」。", !pending.busy);
    }
    renderControls();
  }

  function contentType(file) {
    if (file.type) return file.type;
    if (/\.png$/i.test(file.name)) return "image/png";
    if (/\.jpe?g$/i.test(file.name)) return "image/jpeg";
    return "";
  }

  function uploadOptions(current) {
    return {
      method: "POST",
      headers: { "Content-Type": current.mediaType },
      body: current.file,
      signal: current.controller.signal,
    };
  }

  function errorMessage(error, operation) {
    if (error.detail?.code === "conversation_version_conflict") {
      return "会话已更新。请刷新工作台，重新选择截图。";
    }
    if (error.detail === "vision_model_not_configured") {
      return "视觉模型尚未配置。配置后可重试识别。";
    }
    if (error.status === 413) return "图片体积超出处理限制，请裁剪或压缩后重试。";
    if (error.status === 415 || error.status === 422) {
      return "图片无法处理。请换一张有效的 PNG 或 JPEG 截图。";
    }
    return `${operation}失败，请稍后重试。`;
  }

  async function selectFile() {
    if (fileInput.disabled) return;
    const file = fileInput.files[0];
    reset({ clearInput: false });
    if (!file || panel.hidden) return;

    const mediaType = contentType(file);
    if (!["image/png", "image/jpeg"].includes(mediaType) || !file.size || file.size > 5 * 1024 * 1024) {
      showFeedback(feedback, "请选择不超过 5 MiB 的非空 PNG 或 JPEG 图片。", true);
      renderControls();
      return;
    }

    const current = { ...getContext(), file, mediaType, controller: new AbortController() };
    selection = current;
    showFeedback(feedback, "正在校验截图…");
    renderControls();
    try {
      const response = await request(
        `${conversationURL(current.conversationId)}/screenshots/preview`,
        uploadOptions(current),
      );
      if (!response.ok) throw { status: response.status };
      const png = await response.blob();
      if (selection !== current) return;
      if (png.type !== "image/png" || !png.size) throw new Error("Invalid preview");
      current.previewURL = URL.createObjectURL(png);
      preview.src = current.previewURL;
      preview.hidden = false;
      showFeedback(feedback, "截图校验通过，可以开始识别。");
    } catch (error) {
      if (selection === current) showFeedback(feedback, errorMessage(error, "预览"), true);
    } finally {
      if (selection === current) renderControls();
    }
  }

  function renderLine(line, index) {
    const item = element("li", "card");
    const title = element("p", "card-label", `第 ${index + 1} 条`);
    if (line.unclear) title.append(element("span", "screenshot-unclear", " · 原图有不清晰内容"));
    const actor = element("select", "");
    actor.setAttribute("aria-label", `第 ${index + 1} 条角色`);
    for (const [value, label] of actors) {
      const option = element("option", "", label);
      option.value = value;
      actor.append(option);
    }
    actor.value = line.actor;
    const body = element("textarea", "");
    body.setAttribute("aria-label", `第 ${index + 1} 条正文`);
    body.rows = 2;
    body.maxLength = 2000;
    body.value = line.text;
    item.append(title, actor, body);
    return { item, actor, body };
  }

  function renderLines(current, transcriptLines) {
    current.rows = transcriptLines.map(renderLine);
    lines.replaceChildren(...current.rows.map(row => row.item));
    candidates.hidden = current.rows.length === 0;
  }

  async function transcribe() {
    if (transcribeButton.disabled) return;
    const current = selection;
    current.transcribing = true;
    showFeedback(feedback, "正在识别截图…");
    renderControls();
    try {
      const result = await requestJSON(
        `${conversationURL(current.conversationId)}/screenshots/transcribe?based_on_version=${current.version}`,
        uploadOptions(current),
      );
      if (selection !== current) return;
      renderLines(current, result.lines);
      current.transcribed = result.lines.length > 0;
      const emptyMessage = result.mode === "mock" ?
        "当前是模拟模式，没有转录候选。" : "未识别到可读发言。";
      showFeedback(feedback, current.transcribed ? `已生成 ${result.lines.length} 条候选。` : emptyMessage);
    } catch (error) {
      if (selection !== current) return;
      current.versionConflict = error.detail?.code === "conversation_version_conflict";
      showFeedback(feedback, errorMessage(error, "识别"), true);
    } finally {
      if (selection === current) {
        current.transcribing = false;
        renderControls();
      }
    }
  }

  async function confirmImport() {
    if (confirmButton.disabled) return;
    const { conversationId } = getContext();
    let pending = pendingImports.get(conversationId);
    if (!pending) {
      const reviewed = confirmedLines();
      if (!reviewed) return;
      pending = {
        body: {
          request_key: crypto.randomUUID(),
          based_on_version: selection.version,
          lines: reviewed,
        },
      };
      pendingImports.set(conversationId, pending);
    }
    pending.busy = true;
    renderContext();

    let result;
    try {
      result = await requestJSON(`${conversationURL(conversationId)}/screenshots/import`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(pending.body),
        signal: AbortSignal.timeout(15000),
      });
      if (result?.request_key !== pending.body.request_key ||
          result.conversation_id !== conversationId ||
          result.message_ids?.length !== pending.body.lines.length) {
        throw new Error("Unexpected import receipt");
      }
    } catch (error) {
      if (pendingImports.get(conversationId) !== pending) return;
      pending.busy = false;
      const rejected = [404, 409, 422].includes(error.status);
      if (rejected) pendingImports.delete(conversationId);
      if (activeConversationId !== conversationId) return;
      if (!rejected) {
        renderContext();
        return;
      }

      const conflict = error.detail?.code === "conversation_version_conflict";
      if (selection && error.status !== 422) selection.versionConflict = true;
      showFeedback(feedback, conflict
        ? "会话已更新。请查看最新消息，再重新选择截图。"
        : error.status === 422
          ? "候选未通过校验。请检查每条消息的角色和正文。"
          : "导入请求已被拒绝。请刷新工作台后检查当前会话。", true);
      renderControls();
      return;
    }

    if (pendingImports.get(conversationId) !== pending) return;
    pendingImports.delete(conversationId);
    if (activeConversationId !== conversationId) return;
    reset();
    showFeedback(feedback, `已导入 ${result.message_ids.length} 条实际消息。`);
    await refreshDetails(conversationId);
  }

  fileInput.addEventListener("change", selectFile);
  transcribeButton.addEventListener("click", transcribe);
  clearButton.addEventListener("click", () => {
    if (!clearButton.disabled) reset();
  });
  lines.addEventListener("input", renderControls);
  lines.addEventListener("change", renderControls);
  confirmButton.addEventListener("click", confirmImport);
  window.addEventListener("pagehide", () => {
    pendingImports.clear();
    reset({ close: true });
  });
  return { renderContext };
}
