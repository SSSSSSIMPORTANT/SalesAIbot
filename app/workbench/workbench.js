"use strict";

const byId = id => document.getElementById(id);
const workspace = byId("workspace");
const loginForm = byId("login-form");
const loginUsername = byId("login-username");
const loginPassword = byId("login-password");
const loginButton = byId("login-submit");
const logoutButton = byId("logout");
const refreshButton = byId("refresh");
const conversationList = byId("conversation-list");
const statusLine = byId("status");
const versionLabel = byId("conversation-version");
const assistanceStatus = byId("assistance-status");
const assistanceButton = byId("toggle-assistance");
const messageForm = byId("message-form");
const messageActor = byId("message-actor");
const messageSourceLabel = byId("message-source-label");
const messageSource = byId("message-source");
const messageInput = byId("customer-message");
const saveMessageButton = byId("save-message");
const messageFeedback = byId("message-feedback");
const conversationName = byId("new-customer-name");
const createButton = byId("create-conversation");
const generationForm = byId("generation-form");
const productSelect = byId("product-select");
const productInput = byId("product-id");
const generateButton = byId("generate-suggestion");
const checkGenerationButton = byId("check-generation");
const timeFormat = new Intl.DateTimeFormat("zh-CN", {
  month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
});

let conversations = [];
let selectedId = null;
let detailRequestId = 0;
let currentVersion = null;
let latestActor = null;
let suggestionsPaused = null;
let refreshing = false;
let creating = false;
let creationNeedsRefresh = false;
let products = [];
let productMode = "loading";
let productRequestId = 0;
let operator = null;
let stateOperatorId = null;
let authEpoch = 0;
let signingIn = false;
let signingOut = false;
const messageDrafts = new Map();
const generations = new Map();
const assistanceActions = new Map();
const suggestionActions = new Map();
const suggestionViews = new Map();

async function workbenchFetch(url, options = {}) {
  const authRequest = url.startsWith("/auth/");
  const epoch = authEpoch;
  if (!authRequest && (!operator || signingOut)) throw new Error("请先登录。");

  const headers = { ...options.headers };
  if (!authRequest) headers["X-Workbench-Operator"] = operator.id;
  const response = await fetch(url, { cache: "no-store", ...options, headers });
  if (!authRequest) {
    if (epoch !== authEpoch) throw new Error("登录状态已变化。");
    if (response.status === 401) {
      showSignedOut("登录已失效，请重新登录。", true);
      throw new Error("登录已失效。");
    }
  }
  return response;
}

async function getJSON(url, options = {}) {
  const epoch = authEpoch;
  const response = await workbenchFetch(url, options);
  if (!response.ok) {
    const error = new Error(`请求失败（HTTP ${response.status}）`);
    error.status = response.status;
    error.detail = (await response.json().catch(() => null))?.detail;
    throw error;
  }
  if (response.status === 204) return null;
  const data = await response.json();
  if (!url.startsWith("/auth/") && epoch !== authEpoch) {
    throw new Error("登录状态已变化。");
  }
  return data;
}

function postJSON(url, body, options = {}) {
  if (body === undefined) return getJSON(url, { method: "POST" });
  return getJSON(url, {
    ...options,
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function conversationURL(id) {
  return `/conversations/${encodeURIComponent(id)}`;
}

function currentConversation() {
  return operator ? conversations.find(row => row.id === selectedId) : undefined;
}

function scopedKey(kind, recordId) {
  return `salesaibot:${stateOperatorId}:${kind}:${recordId}`;
}

function readStored(key) {
  try { return JSON.parse(sessionStorage.getItem(key)); }
  catch { return null; }
}

function writeStored(key, value) {
  try {
    if (value === null) sessionStorage.removeItem(key);
    else sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    // In-memory state remains available when session storage is disabled.
  }
}

function showFeedback(node, text, isError = false) {
  node.textContent = text;
  node.hidden = !text;
  node.dataset.error = String(isError);
}

function showSignedOut(message = "使用本地销售账号登录。", isError = false) {
  operator = null;
  ++authEpoch;
  ++detailRequestId;
  ++productRequestId;
  signingOut = false;
  refreshing = creating = creationNeedsRefresh = false;

  workspace.hidden = true;
  workspace.inert = false;
  byId("account-controls").hidden = true;
  byId("operator-name").textContent = "";
  byId("environment").hidden = false;
  byId("auth-panel").hidden = false;
  loginForm.hidden = false;
  loginPassword.value = "";
  logoutButton.disabled = false;
  showFeedback(byId("auth-feedback"), message, isError);

  conversations = [];
  suggestionActions.clear();
  products = [];
  productMode = "loading";
  productSelect.replaceChildren();
  productInput.value = "";
  messageInput.value = "";
  conversationName.value = "";
  byId("customer-name").textContent = "会话详情";
  showFeedback(byId("conversation-feedback"), "");
  showFeedback(byId("logout-feedback"), "");
  renderConversations();
  clearDetails("正在加载…");
  renderConversationForm();
}

function openWorkbench(identity) {
  if (stateOperatorId !== identity.id) {
    stateOperatorId = identity.id;
    selectedId = null;
    messageDrafts.clear();
    generations.clear();
    assistanceActions.clear();
    suggestionActions.clear();
  }
  operator = identity;
  ++authEpoch;
  byId("auth-panel").hidden = true;
  byId("environment").hidden = true;
  byId("operator-name").textContent = identity.username;
  byId("account-controls").hidden = false;
  workspace.hidden = false;
  refreshWorkbench();
}

async function startWorkbench() {
  try {
    openWorkbench(await getJSON("/auth/me"));
  } catch (error) {
    if (error.status === 401) showSignedOut();
    else showSignedOut("暂时无法检查登录状态，请确认服务已启动。", true);
  }
}

async function signIn(event) {
  event.preventDefault();
  if (signingIn || operator) return;
  const username = loginUsername.value.trim();
  const password = loginPassword.value;
  if (!username || !password) return;

  signingIn = true;
  loginButton.disabled = true;
  loginButton.textContent = "正在登录…";
  loginPassword.value = "";
  showFeedback(byId("auth-feedback"), "");
  try {
    openWorkbench(await postJSON("/auth/login", { username, password }));
  } catch (error) {
    const message = error.status === 401 ? "用户名或密码不正确。" :
      error.status === 422 ? "请检查用户名和密码的格式。" : "暂时无法登录，请稍后重试。";
    showFeedback(byId("auth-feedback"), message, true);
  } finally {
    signingIn = false;
    loginButton.disabled = false;
    loginButton.textContent = "登录";
  }
}

async function signOut() {
  if (!operator || signingOut) return;
  const epoch = authEpoch;
  signingOut = true;
  workspace.inert = true;
  logoutButton.disabled = true;
  showFeedback(byId("logout-feedback"), "");
  try {
    await postJSON("/auth/logout");
    if (epoch === authEpoch) showSignedOut("已退出登录。");
  } catch {
    if (epoch === authEpoch) {
      showFeedback(byId("logout-feedback"), "暂时无法确认退出，请重试。", true);
    }
  } finally {
    if (epoch === authEpoch) {
      signingOut = false;
      workspace.inert = false;
      logoutButton.disabled = false;
    }
  }
}

function setStatus(text, isError = false) {
  statusLine.textContent = text;
  statusLine.dataset.error = String(isError);
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function createCard(kind, label, timestamp, text, note) {
  const card = element("li", "card");
  card.dataset.kind = kind;
  const meta = element("div", "card-meta");
  meta.append(element("span", "card-label", label));
  const date = new Date(timestamp);
  if (timestamp && Number.isFinite(date.getTime())) {
    const time = element("time", "", timeFormat.format(date));
    time.dateTime = timestamp;
    meta.append(time);
  }
  card.append(meta);
  if (note) card.append(element("p", "card-note", note));
  card.append(element("p", "card-text", text));
  return card;
}

function renderCards(id, countId, rows, renderRow, emptyText) {
  const fragment = document.createDocumentFragment();
  for (const row of rows) fragment.append(renderRow(row));
  byId(id).replaceChildren(fragment);
  byId(countId).textContent = rows.length;
  const empty = byId(`${id}-empty`);
  empty.textContent = emptyText;
  empty.hidden = rows.length > 0;
}

function clearDetails(emptyText) {
  currentVersion = null;
  screenshotImport.renderContext();
  latestActor = null;
  suggestionsPaused = null;
  suggestionViews.clear();
  versionLabel.hidden = true;
  renderCards("messages", "message-count", [], null, emptyText);
  renderCards("suggestions", "suggestion-count", [], null, emptyText);
  setMessageSources(currentConversation()?.id, []);
  renderMessageForm();
  renderAssistance();
  renderGenerationForm();
}

function getAssistanceAction(conversationId) {
  if (!assistanceActions.has(conversationId)) {
    assistanceActions.set(conversationId, { busy: false, feedback: "", error: false });
  }
  return assistanceActions.get(conversationId);
}

function renderAssistance() {
  const conversation = currentConversation();
  const loaded = Boolean(conversation && currentVersion !== null && typeof suggestionsPaused === "boolean");
  const state = loaded ? getAssistanceAction(conversation.id) : null;
  assistanceStatus.hidden = assistanceButton.hidden = !loaded;
  assistanceButton.disabled = !loaded || state.busy;
  assistanceStatus.dataset.paused = String(suggestionsPaused === true);
  assistanceStatus.textContent = suggestionsPaused ? "AI 建议已暂停" : "AI 建议已启用";
  assistanceButton.textContent = state?.busy ? "正在更新…" :
    suggestionsPaused ? "恢复 AI 建议" : "暂停 AI 建议";
  showFeedback(byId("assistance-feedback"), state?.feedback ?? "", state?.error ?? false);
}

async function toggleAssistance() {
  const conversation = currentConversation();
  if (!conversation || assistanceButton.disabled || signingOut) return;
  const state = getAssistanceAction(conversation.id);
  const epoch = authEpoch;
  const paused = !suggestionsPaused;
  const body = { based_on_version: currentVersion, suggestions_paused: paused };

  state.busy = true;
  state.feedback = "";
  renderAssistance();
  renderGenerationForm();
  for (const draw of suggestionViews.values()) draw();

  try {
    await getJSON(`${conversationURL(conversation.id)}/assistance`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    state.feedback = paused
      ? "已暂停 AI 建议，可以继续补录实际消息。"
      : "已恢复 AI 建议，可以按当前会话重新生成。";
    state.error = false;
  } catch (error) {
    state.feedback = error.status === 409
      ? "会话已更新，请查看当前状态后再试。"
      : "暂时无法确认切换结果，请查看当前状态。";
    state.error = true;
  } finally {
    state.busy = false;
    const active = currentConversation();
    if (epoch === authEpoch && active?.id === conversation.id) await loadDetails(active);
  }
}

function getMessageDraft(conversationId) {
  if (!messageDrafts.has(conversationId)) {
    const storageKey = scopedKey("pending-message", conversationId);
    const stored = readStored(storageKey);
    const pending = ["customer", "human"].includes(stored?.actor) &&
      typeof stored.text === "string" && typeof stored.request_key === "string" &&
      Number.isInteger(stored.based_on_version) ? stored : null;
    messageDrafts.set(conversationId, {
      storageKey,
      text: pending?.text ?? "",
      actor: pending?.actor ?? "customer",
      sourceSuggestionId: pending?.source_suggestion_id ?? "",
      pending,
      submitting: false,
      feedback: pending ? "上次保存结果待确认，可以重试保存。" : "",
      error: Boolean(pending),
    });
  }
  return messageDrafts.get(conversationId);
}

function setMessageSources(conversationId, suggestions) {
  const options = suggestions.map(suggestion => {
    const name = suggestion.generation_snapshot?.retrieved_knowledge?.name || suggestion.product_id;
    return new Option(
      `${name} · 版本 ${suggestion.based_on_version} · ${suggestion.id.slice(0, 8)}`,
      suggestion.id,
    );
  });
  const selected = conversationId ? getMessageDraft(conversationId).sourceSuggestionId : "";
  if (selected && !suggestions.some(suggestion => suggestion.id === selected)) {
    options.push(new Option(`已选择的历史建议 · ${selected.slice(0, 8)}`, selected));
  }
  messageSource.replaceChildren(new Option("不关联建议", ""), ...options);
}

function renderMessageForm() {
  const conversation = currentConversation();
  messageForm.hidden = !conversation;
  if (!conversation) return;

  const draft = getMessageDraft(conversation.id);
  if (messageInput.value !== draft.text) messageInput.value = draft.text;
  messageActor.value = draft.actor;
  messageActor.disabled = Boolean(draft.pending);
  messageSourceLabel.hidden = messageSource.hidden = draft.actor !== "human";
  messageSource.disabled = messageSource.hidden || Boolean(draft.pending) || currentVersion === null;
  messageSource.value = draft.sourceSuggestionId;
  messageInput.placeholder = draft.actor === "human"
    ? "粘贴销售在外部实际发出的原文" : "粘贴或输入客户原话";
  messageInput.readOnly = Boolean(draft.pending);
  saveMessageButton.disabled = draft.submitting || (
    !draft.pending && (currentVersion === null || !draft.text.trim())
  );
  saveMessageButton.textContent = draft.submitting
    ? "正在保存…"
    : draft.pending ? "重试保存" : "保存消息";
  showFeedback(messageFeedback, draft.feedback, draft.error);
}

async function saveMessage(event) {
  event.preventDefault();
  const conversation = currentConversation();
  if (!conversation) return;
  const epoch = authEpoch;

  const draft = getMessageDraft(conversation.id);
  if (draft.submitting) return;

  if (!draft.pending) {
    const text = draft.text.trim();
    if (currentVersion === null || !text) return;
    if (Array.from(text).length > 2000) {
      draft.feedback = "消息最多 2000 个字符。";
      draft.error = true;
      renderMessageForm();
      return;
    }
    draft.pending = {
      request_key: crypto.randomUUID(),
      based_on_version: currentVersion,
      actor: draft.actor,
      text,
    };
    if (draft.actor === "human" && draft.sourceSuggestionId) {
      draft.pending.source_suggestion_id = draft.sourceSuggestionId;
    }
    writeStored(draft.storageKey, draft.pending);
  }

  draft.submitting = true;
  draft.feedback = "";
  renderMessageForm();
  let reloadDetails = false;

  try {
    const response = await workbenchFetch(`${conversationURL(conversation.id)}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(draft.pending),
    });

    if (response.status === 200 || response.status === 201) {
      draft.pending = null;
      draft.text = "";
      draft.sourceSuggestionId = "";
      draft.feedback = draft.actor === "human" ? "已发原文已补录。" : "客户消息已保存。";
      draft.error = false;
      reloadDetails = true;
    } else if ([404, 409, 422].includes(response.status)) {
      draft.pending = null;
      draft.error = true;
      if (response.status === 409) {
        draft.feedback = "提交发生冲突，已保留原文。请检查最新消息后再保存。";
      } else if (response.status === 404) {
        draft.feedback = draft.sourceSuggestionId
          ? "找不到会话或关联的建议。已保留原文，请检查会话和所选建议。"
          : "找不到会话，已保留原文。请刷新会话列表。";
      } else {
        draft.feedback = "消息未通过校验，已保留原文。请检查后再保存。";
      }
      reloadDetails = response.status !== 422;
    } else {
      throw new Error(`Unexpected HTTP status ${response.status}`);
    }
    writeStored(draft.storageKey, null);
  } catch {
    draft.feedback = "暂时无法确认保存结果。恢复连接后，请点击「重试保存」。";
    draft.error = true;
  } finally {
    draft.submitting = false;
    const active = currentConversation();
    if (active?.id === conversation.id && messageDrafts.get(conversation.id) === draft) {
      if (reloadDetails && epoch === authEpoch) await loadDetails(active);
      else renderMessageForm();
    }
  }
}

function renderConversationForm() {
  conversationName.readOnly = creating;
  createButton.disabled = !operator || creating || refreshing || creationNeedsRefresh || !conversationName.value.trim();
  createButton.textContent = creating ? "正在创建…" : "创建会话";
  refreshButton.disabled = !operator || refreshing || creating;
}

async function createConversation(event) {
  event.preventDefault();
  if (createButton.disabled) return;
  const epoch = authEpoch;
  const name = conversationName.value.trim();
  const feedback = byId("conversation-feedback");
  if (Array.from(name).length > 100) {
    showFeedback(feedback, "客户名称最多 100 个字符。", true);
    return;
  }

  creating = true;
  renderConversationForm();
  showFeedback(feedback, "");
  try {
    const conversation = await postJSON("/conversations", { customer_name: name });
    if (epoch !== authEpoch) return;
    conversationName.value = "";
    conversations.unshift(conversation);
    renderConversations();
    showFeedback(feedback, "会话已创建。");
    await loadDetails(conversation);
  } catch (error) {
    if (epoch !== authEpoch) return;
    creationNeedsRefresh = error.status !== 422;
    showFeedback(feedback, creationNeedsRefresh
      ? "创建结果待确认，请刷新并查看会话列表。"
      : "客户名称未通过校验，请检查后再创建。", true);
  } finally {
    if (epoch === authEpoch) {
      creating = false;
      renderConversationForm();
    }
  }
}

async function loadProducts() {
  const requestId = ++productRequestId;
  productMode = "loading";
  renderGenerationForm();
  try {
    const rows = await getJSON("/products");
    if (requestId !== productRequestId) return;
    if (!Array.isArray(rows) || rows.some(row =>
      typeof row?.product_id !== "string" || typeof row?.name !== "string"
    )) throw new Error("Invalid product list");
    products = rows;
    productSelect.replaceChildren(
      new Option("请选择课程", ""),
      ...products.map(row => new Option(row.name, row.product_id)),
    );
    productMode = "catalog";
  } catch {
    if (requestId !== productRequestId) return;
    productMode = "manual";
  }
  renderGenerationForm();
}

function getGeneration(conversationId) {
  if (!generations.has(conversationId)) {
    const storageKey = scopedKey("pending-generation", conversationId);
    const stored = readStored(storageKey);
    const pending = typeof stored?.request_key === "string" && typeof stored.product_id === "string" &&
      Number.isInteger(stored.based_on_version) ? stored : null;
    generations.set(conversationId, {
      storageKey,
      productId: pending?.product_id ?? "", pending, busy: false, running: false,
      feedback: pending ? "上次生成结果待确认。" : "", error: false,
    });
  }
  return generations.get(conversationId);
}

function renderGenerationForm() {
  const conversation = currentConversation();
  generationForm.hidden = !conversation;
  if (!conversation) return;

  const state = getGeneration(conversation.id);
  const manual = productMode === "manual";
  const selectedProduct = state.pending?.product_id ?? state.productId;
  const locked = Boolean(state.pending) || state.busy;
  byId("product-label").htmlFor = manual ? "product-id" : "product-select";
  byId("product-label").textContent = manual ? "课程 ID" : "课程";
  productSelect.hidden = manual;
  productSelect.disabled = locked || productMode === "loading" || products.length === 0;
  productSelect.value = selectedProduct;
  productInput.hidden = !manual;
  productInput.readOnly = locked;
  if (productInput.value !== selectedProduct) productInput.value = selectedProduct;

  const hasProduct = manual ? Boolean(state.productId.trim()) :
    productMode === "catalog" && products.some(row => row.product_id === state.productId);
  generateButton.disabled = state.busy || suggestionsPaused === true ||
    getAssistanceAction(conversation.id).busy || (state.pending ? state.running : (
    !hasProduct || currentVersion === null || latestActor !== "customer"
  ));
  generateButton.textContent = state.busy ? "处理中…" : state.pending ? "重试同一次生成" : "生成建议";
  checkGenerationButton.hidden = !state.pending;
  checkGenerationButton.disabled = state.busy;

  const hints = [];
  if (productMode === "loading") hints.push("正在加载课程列表…");
  if (manual) hints.push("课程列表暂不可用，可手动输入课程 ID。");
  if (productMode === "catalog" && products.length === 0) hints.push("暂无已发布课程。");
  if (suggestionsPaused) {
    hints.push("AI 建议已暂停，恢复后可生成新建议。");
  } else if (!state.pending && currentVersion !== null && latestActor !== "customer") {
    hints.push("最近一条实际消息为客户原话时，可以生成建议。");
  }
  showFeedback(byId("product-hint"), hints.join(" "));
  showFeedback(byId("generation-feedback"), state.feedback, state.error);
}

function finishGeneration(state, feedback, error = false) {
  state.pending = null;
  state.running = false;
  state.feedback = feedback;
  state.error = error;
  writeStored(state.storageKey, null);
}

async function inspectGeneration(conversationId, state, releaseMissing = false) {
  const query = new URLSearchParams({ request_key: state.pending.request_key });
  try {
    const row = await getJSON(`${conversationURL(conversationId)}/generation-requests/by-key?${query}`);
    if (row.status === "running") {
      state.running = true;
      state.feedback = "生成仍在运行，请稍后查询状态。";
      state.error = false;
      return false;
    }
    if (row.status === "succeeded") {
      finishGeneration(state, "建议已保存。");
      return true;
    }
    if (row.status === "failed") {
      finishGeneration(state, "本次生成失败。请检查课程和最新消息后重新生成。", true);
      return true;
    }
    throw new Error("Invalid generation state");
  } catch (error) {
    if (error.status !== 404) throw error;
    if (releaseMissing) {
      finishGeneration(state, "会话或生成条件已变化，请核对后重新生成。", true);
      return true;
    }
    state.running = false;
    state.feedback = "暂未查到生成记录，可以重试同一次生成。";
    state.error = true;
    return false;
  }
}

async function runGeneration(checkOnly) {
  const conversation = currentConversation();
  if (!conversation) return;
  const epoch = authEpoch;
  const state = getGeneration(conversation.id);
  if (state.busy || (checkOnly ? !state.pending : generateButton.disabled)) return;

  if (!state.pending) {
    const productId = state.productId.trim();
    if (Array.from(productId).length > 100) {
      state.feedback = "课程 ID 最多 100 个字符。";
      state.error = true;
      renderGenerationForm();
      return;
    }
    state.pending = {
      request_key: crypto.randomUUID(), based_on_version: currentVersion, product_id: productId,
    };
    writeStored(state.storageKey, state.pending);
  }

  state.busy = true;
  state.feedback = checkOnly ? "正在查询生成状态…" : "正在生成建议…";
  state.error = false;
  renderGenerationForm();
  let reloadDetails = false;

  try {
    if (checkOnly) {
      reloadDetails = await inspectGeneration(conversation.id, state);
    } else {
      try {
        await postJSON(`${conversationURL(conversation.id)}/suggestions`, state.pending, {
          signal: AbortSignal.timeout(60_000),
        });
        finishGeneration(state, "建议已保存。");
        reloadDetails = true;
      } catch (error) {
        if (epoch !== authEpoch) return;
        if (error.detail?.code === "suggestions_paused") {
          finishGeneration(state, "AI 建议已暂停，恢复后可重新生成。", true);
          reloadDetails = true;
        } else if (error.status === 422 || error.detail?.code === "generation_request_mismatch") {
          finishGeneration(state, "生成请求不匹配或参数未通过校验，请核对后重试。", true);
          reloadDetails = true;
        } else {
          const rejected = error.status === 404 || (
            error.status === 409 && error.detail?.code !== "generation_in_progress"
          );
          reloadDetails = await inspectGeneration(conversation.id, state, rejected);
        }
      }
    }
  } catch {
    state.feedback = "暂时无法确认生成结果。恢复连接后，请查询生成状态。";
    state.error = true;
  } finally {
    state.busy = false;
    const active = currentConversation();
    if (active?.id === conversation.id && generations.get(conversation.id) === state) {
      if (reloadDetails && epoch === authEpoch) await loadDetails(active);
      else renderGenerationForm();
    }
  }
}

const validityReasons = {
  conversation_changed: "会话已更新",
  suggestions_paused: "AI 建议已暂停",
  memory_changed: "客户记忆已更新",
  knowledge_changed: "知识资料已更新",
  knowledge_unavailable: "知识资料已下架或不可用",
  invalid_snapshot: "生成依据不完整",
  suggestion_abandoned: "已放弃",
};

function getSuggestionAction(suggestionId) {
  if (!suggestionActions.has(suggestionId)) {
    const storageKey = scopedKey("pending-copy-report", suggestionId);
    const stored = readStored(storageKey);
    const pendingKey = typeof stored === "string" ? stored : null;
    suggestionActions.set(suggestionId, {
      storageKey,
      validity: null, pendingKey, busy: false,
      feedback: pendingKey ? "已复制，记录待确认。" : "", error: Boolean(pendingKey),
    });
  }
  return suggestionActions.get(suggestionId);
}

function suggestionURL(conversationId, suggestionId) {
  return `${conversationURL(conversationId)}/suggestions/${encodeURIComponent(suggestionId)}`;
}

function updateSuggestionView(suggestionId, state) {
  if (suggestionActions.get(suggestionId) === state) suggestionViews.get(suggestionId)?.();
}

async function checkSuggestion(conversationId, suggestionId) {
  if (!operator || selectedId !== conversationId) return;
  const state = getSuggestionAction(suggestionId);
  if (state.busy) return;
  state.busy = true;
  state.feedback = "";
  updateSuggestionView(suggestionId, state);
  try {
    state.validity = await getJSON(`${suggestionURL(conversationId, suggestionId)}/validity`);
  } catch (error) {
    state.validity = null;
    state.feedback = `暂时无法检查建议。${error.message}`;
    state.error = true;
  } finally {
    state.busy = false;
    updateSuggestionView(suggestionId, state);
  }
}

async function reportCopy(conversationId, suggestionId, state) {
  try {
    await postJSON(`${suggestionURL(conversationId, suggestionId)}/copy-events`, {
      request_key: state.pendingKey,
    });
    state.pendingKey = null;
    writeStored(state.storageKey, null);
    state.feedback = "已复制，复制记录已保存。";
    state.error = false;
  } catch {
    state.feedback = "已复制，记录待确认。可点击「重试记录」。";
    state.error = true;
  }
}

async function copySuggestion(conversationId, suggestionId) {
  if (!operator || selectedId !== conversationId) return;
  const epoch = authEpoch;
  const state = getSuggestionAction(suggestionId);
  if (state.busy || (!state.pendingKey && (
    suggestionsPaused || getAssistanceAction(conversationId).busy ||
    state.abandonment || state.pendingAbandonReason
  ))) return;
  state.busy = true;
  state.feedback = "";
  updateSuggestionView(suggestionId, state);

  try {
    if (!state.pendingKey) {
      const prepared = await postJSON(`${suggestionURL(conversationId, suggestionId)}/copy-ready`);
      if (epoch !== authEpoch || signingOut || selectedId !== conversationId ||
        suggestionsPaused || getAssistanceAction(conversationId).busy || (
        currentVersion !== null && currentVersion > prepared.based_on_version
      )) {
        state.feedback = "会话已切换或更新，请重新检查后复制。";
        state.error = true;
        return;
      }
      const requestKey = crypto.randomUUID();
      try {
        await navigator.clipboard.writeText(prepared.text);
      } catch {
        state.feedback = "浏览器未能写入剪贴板，请检查权限后再试。";
        state.error = true;
        return;
      }
      state.validity = { status: "current", reasons: [] };
      state.pendingKey = requestKey;
      writeStored(state.storageKey, requestKey);
    }
    if (epoch === authEpoch && !signingOut) await reportCopy(conversationId, suggestionId, state);
  } catch (error) {
    if (error.detail?.code === "suggestion_stale") {
      state.validity = { status: "stale", reasons: error.detail.reasons };
      state.feedback = error.detail.reasons?.includes("suggestion_abandoned")
        ? "这条建议已放弃。" : "请根据最新会话重新生成建议。";
    } else {
      state.validity = null;
      state.feedback = `暂时无法准备复制。${error.message}`;
    }
    state.error = true;
  } finally {
    state.busy = false;
    updateSuggestionView(suggestionId, state);
  }
}

function renderSuggestion(conversationId, row) {
  const knowledge = row.generation_snapshot?.retrieved_knowledge;
  const source = knowledge ? ` · 资料 ${knowledge.knowledge_id} · ${knowledge.revision}` : "";
  const card = createCard(
    "suggestion", knowledge?.name || row.product_id, row.created_at, row.reply_text,
    `生成时版本 ${row.based_on_version} · 建议 ${row.id.slice(0, 8)}${source}`,
  );
  if (knowledge?.source) card.append(element("p", "card-note", `来源 ${knowledge.source}`));

  const state = getSuggestionAction(row.id);
  const status = element("p", "feedback suggestion-status");
  const feedback = element("p", "feedback copy-feedback");
  feedback.setAttribute("role", "status");
  const actions = element("div", "actions suggestion-actions");
  const check = element("button", "secondary-button", "检查有效性");
  const copy = element("button", "secondary-button");
  const outcome = createSuggestionOutcome({
    url: suggestionURL(conversationId, row.id),
    state,
    isActive: () => Boolean(operator && !signingOut && selectedId === conversationId),
    redraw: () => updateSuggestionView(row.id, state),
  });
  check.type = copy.type = "button";
  check.addEventListener("click", () => checkSuggestion(conversationId, row.id));
  copy.addEventListener("click", async () => {
    await copySuggestion(conversationId, row.id);
    await outcome.refresh();
  });
  actions.append(check, copy);
  card.append(status, actions, outcome.panel, feedback);

  const draw = () => {
    const reasons = new Set(state.validity?.reasons ?? []);
    if (state.abandonment) reasons.add("suggestion_abandoned");
    if (currentVersion !== null && currentVersion > row.based_on_version) {
      reasons.add("conversation_changed");
    }
    if (suggestionsPaused) reasons.add("suggestions_paused");
    else if (currentVersion !== null && currentVersion > row.based_on_version) {
      reasons.delete("suggestions_paused");
    }
    const stale = state.validity?.status === "stale" || reasons.size > 0;
    const labels = Array.from(reasons, reason => validityReasons[reason] ?? reason);
    status.textContent = reasons.has("suggestion_abandoned") ? "已放弃" :
      stale ? ["已过期", ...labels].join(" · ") :
      state.validity?.status === "current" ? "上次检查通过" : "有效性待检查";
    status.dataset.stale = String(stale);
    check.disabled = state.busy;
    copy.disabled = state.busy || (
      !state.pendingKey && (stale || state.pendingAbandonReason || getAssistanceAction(conversationId).busy)
    );
    copy.textContent = state.busy ? "处理中…" : state.pendingKey ? "重试记录" : "复制建议";
    showFeedback(feedback, state.feedback, state.error);
    outcome.draw();
  };
  suggestionViews.set(row.id, draw);
  draw();
  return card;
}

function renderConversations() {
  const fragment = document.createDocumentFragment();
  for (const conversation of conversations) {
    const item = element("li", "");
    const button = element("button", "conversation-button");
    button.type = "button";
    button.dataset.id = conversation.id;
    button.append(
      element("span", "conversation-name", conversation.customer_name),
      element("span", "conversation-id", conversation.id.slice(0, 8)),
    );
    button.addEventListener("click", () => loadDetails(conversation));
    item.append(button);
    fragment.append(item);
  }
  conversationList.replaceChildren(fragment);
  byId("conversation-count").textContent = conversations.length;
  byId("conversation-empty").hidden = conversations.length > 0;
}

function renderMessage(row) {
  const adoption = row.adoption_mode === "verbatim" ? "原样采用" :
    row.adoption_mode === "edited" ? "改写后采用" : "";
  const note = adoption && row.source_suggestion_id
    ? `${adoption} · 建议 ${row.source_suggestion_id.slice(0, 8)}` : "";
  return createCard(
    row.actor, row.actor === "customer" ? "客户" : "人工销售", row.created_at, row.text, note,
  );
}

async function loadDetails(conversation) {
  if (!operator) return;
  const requestId = ++detailRequestId;
  selectedId = conversation.id;
  for (const button of conversationList.querySelectorAll("button")) {
    if (button.dataset.id === selectedId) button.setAttribute("aria-current", "true");
    else button.removeAttribute("aria-current");
  }

  byId("customer-name").textContent = conversation.customer_name;
  clearDetails("正在加载…");
  setStatus("正在加载当前会话…");
  const base = conversationURL(conversation.id);

  try {
    const [details, messages, suggestions] = await Promise.all([
      getJSON(base),
      getJSON(`${base}/messages`),
      getJSON(`${base}/suggestions`),
    ]);
    if (requestId !== detailRequestId) return;

    byId("customer-name").textContent = details.customer_name;
    currentVersion = details.version;
    screenshotImport.renderContext();
    latestActor = messages.at(-1)?.actor ?? null;
    suggestionsPaused = details.suggestions_paused;
    versionLabel.textContent = `当前版本 ${details.version}`;
    versionLabel.hidden = false;
    renderCards("messages", "message-count", messages, renderMessage, "这个会话还没有消息。");
    renderCards("suggestions", "suggestion-count", suggestions,
      row => renderSuggestion(conversation.id, row), "这个会话还没有建议。");
    setMessageSources(conversation.id, suggestions);
    renderMessageForm();
    renderAssistance();
    renderGenerationForm();
    setStatus(`已加载 ${messages.length} 条消息和 ${suggestions.length} 条建议。`);
  } catch (error) {
    if (requestId !== detailRequestId) return;
    clearDetails("加载失败，请刷新后重试。");
    setStatus(`无法加载当前会话。${error.message}`, true);
  }
}

async function refreshWorkbench() {
  if (!operator || refreshing || creating) return;
  const epoch = authEpoch;
  refreshing = true;
  renderConversationForm();
  ++detailRequestId;
  conversations = [];
  renderConversations();
  byId("conversation-empty").textContent = "正在加载会话…";
  byId("customer-name").textContent = "会话详情";
  clearDetails("正在加载…");
  setStatus("正在加载会话列表…");
  loadProducts();

  try {
    const rows = await getJSON("/conversations");
    if (epoch !== authEpoch) return;
    conversations = rows;
    if (creationNeedsRefresh) {
      creationNeedsRefresh = false;
      showFeedback(byId("conversation-feedback"), "列表已刷新，请确认会话是否已创建。");
    }
    renderConversations();
    const preferred = conversations.find(row => row.id === selectedId) || conversations[0];
    if (preferred) {
      await loadDetails(preferred);
    } else {
      selectedId = null;
      byId("conversation-empty").textContent = "当前账号暂无会话。";
      clearDetails("创建会话后，这里会显示对应内容。");
      setStatus("可以从左侧创建第一个会话。");
    }
  } catch (error) {
    if (epoch !== authEpoch) return;
    byId("conversation-empty").textContent = "会话列表加载失败。";
    clearDetails("请刷新后重试。");
    setStatus(`无法加载会话列表。${error.message}`, true);
  } finally {
    if (epoch === authEpoch) {
      refreshing = false;
      renderConversationForm();
    }
  }
}

refreshButton.addEventListener("click", refreshWorkbench);
assistanceButton.addEventListener("click", toggleAssistance);
loginForm.addEventListener("submit", signIn);
logoutButton.addEventListener("click", signOut);
conversationName.addEventListener("input", renderConversationForm);
byId("conversation-form").addEventListener("submit", createConversation);
messageInput.addEventListener("input", () => {
  const conversation = currentConversation();
  if (!conversation) return;
  const draft = getMessageDraft(conversation.id);
  if (draft.pending) return;
  draft.text = messageInput.value;
  draft.feedback = "";
  renderMessageForm();
});
messageActor.addEventListener("change", () => {
  const conversation = currentConversation();
  if (!conversation) return;
  const draft = getMessageDraft(conversation.id);
  if (draft.pending) return;
  draft.actor = messageActor.value;
  if (draft.actor !== "human") draft.sourceSuggestionId = "";
  draft.feedback = "";
  renderMessageForm();
});
messageSource.addEventListener("change", () => {
  const conversation = currentConversation();
  if (!conversation) return;
  const draft = getMessageDraft(conversation.id);
  if (draft.pending || draft.actor !== "human") return;
  draft.sourceSuggestionId = messageSource.value;
  draft.feedback = "";
  renderMessageForm();
});
messageForm.addEventListener("submit", saveMessage);

function chooseProduct(control) {
  const conversation = currentConversation();
  if (!conversation) return;
  const state = getGeneration(conversation.id);
  if (state.pending) return;
  state.productId = control.value;
  state.feedback = "";
  renderGenerationForm();
}

productSelect.addEventListener("change", () => chooseProduct(productSelect));
productInput.addEventListener("input", () => chooseProduct(productInput));
generationForm.addEventListener("submit", event => {
  event.preventDefault();
  return runGeneration(false);
});
checkGenerationButton.addEventListener("click", () => runGeneration(true));
const screenshotImport = createScreenshotImport({
  getContext: () => ({
    operatorId: operator?.id ?? null,
    conversationId: selectedId,
    version: currentVersion,
  }),
  request: workbenchFetch,
  requestJSON: getJSON,
  refreshDetails: conversationId => {
    const active = currentConversation();
    if (active?.id === conversationId) return loadDetails(active);
  },
});
startWorkbench();
