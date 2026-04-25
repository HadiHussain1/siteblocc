const apiBase = document.body.dataset.apiBase || "";
const api = (path) => `${apiBase}${path}`;

let previousOrderIds = new Set();
let orderCatalog = { products: [], deals: [] };
let draftItems = [];
let currentOrderId = null;
let orderViewMode = "tabular";
let orderDetailMode = "detailed";
let priorityEnabled = true;
let priorityOrderState = { received: [], "in progress": [] };

const orderModal = document.getElementById("orderModal");
const orderModalTitle = document.getElementById("orderModalTitle");
const orderModalCopy = document.getElementById("orderModalCopy");
const orderSearch = document.getElementById("orderSearch");
const orderSearchResults = document.getElementById("orderSearchResults");
const orderSummaryList = document.getElementById("orderSummaryList");
const orderSummaryTotal = document.getElementById("orderSummaryTotal");
const allowDiscounts = document.getElementById("allowDiscounts");
const saveOrderBtn = document.getElementById("saveOrderBtn");
const statusSections = Array.from(document.querySelectorAll("[data-status-section]"));

function getPriorityStorageKey() {
  return `orders-priority:${apiBase || window.location.pathname}`;
}

function loadPriorityState() {
  try {
    const saved = JSON.parse(localStorage.getItem(getPriorityStorageKey()) || "{}");
    priorityEnabled = saved.enabled !== false;
    priorityOrderState = {
      received: Array.isArray(saved.received) ? saved.received : [],
      "in progress": Array.isArray(saved["in progress"]) ? saved["in progress"] : []
    };
  } catch {
    priorityEnabled = true;
    priorityOrderState = { received: [], "in progress": [] };
  }
}

function savePriorityState() {
  localStorage.setItem(getPriorityStorageKey(), JSON.stringify({
    enabled: priorityEnabled,
    received: priorityOrderState.received,
    "in progress": priorityOrderState["in progress"]
  }));
}

const customerFields = {
  name: document.getElementById("orderCustomerName"),
  surname: document.getElementById("orderCustomerSurname"),
  phone: document.getElementById("orderCustomerPhone"),
  email: document.getElementById("orderCustomerEmail"),
  payment: document.getElementById("orderPaymentMethod"),
  note: document.getElementById("orderNote")
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatCurrency(value) {
  const amount = Number(value || 0);
  return `$${amount.toFixed(2)}`;
}

function parseOrderItems(rawItems) {
  if (Array.isArray(rawItems)) return rawItems;
  try {
    return JSON.parse(rawItems || "[]");
  } catch {
    return [];
  }
}

function computeDraftTotal() {
  return draftItems.reduce((sum, item) => {
    const qty = Number(item.quantity || 1);
    const basePrice = Number(item.base_price ?? item.price ?? 0);
    const discount = allowDiscounts.checked ? Number(item.discount || 0) : 0;
    const linePrice = Math.max(basePrice - discount, 0);
    return sum + (linePrice * qty);
  }, 0);
}

function readDraftPayload() {
  return {
    items: draftItems.map((item) => ({
      id: item.id,
      item_kind: item.item_kind,
      quantity: Number(item.quantity || 1),
      rank: item.rank || null,
      discount: allowDiscounts.checked ? Number(item.discount || 0) : 0
    })),
    payment: customerFields.payment.value,
    name: customerFields.name.value.trim(),
    surname: customerFields.surname.value.trim(),
    phone: customerFields.phone.value.trim(),
    email: customerFields.email.value.trim(),
    note: customerFields.note.value.trim()
  };
}

function resetModalState() {
  currentOrderId = null;
  draftItems = [];
  orderModalTitle.textContent = "Add Order";
  orderModalCopy.textContent = "Search products or deals, build the order summary, and save it straight into the orders list.";
  allowDiscounts.checked = false;
  orderSearch.value = "";
  customerFields.name.value = "";
  customerFields.surname.value = "";
  customerFields.phone.value = "";
  customerFields.email.value = "";
  customerFields.payment.value = "cash";
  customerFields.note.value = "";
  document.getElementById("orderStatusPreview").value = "Received";
  renderSearchResults();
  renderSummary();
}

function openOrderModal() {
  resetModalState();
  orderModal.classList.add("open");
  orderModal.setAttribute("aria-hidden", "false");
  orderSearch.focus();
}

function closeOrderModal() {
  orderModal.classList.remove("open");
  orderModal.setAttribute("aria-hidden", "true");
}

function getCatalogMatches() {
  const query = orderSearch.value.trim().toLowerCase();
  const products = orderCatalog.products.map((product) => ({
    ...product,
    item_kind: "product"
  }));
  const deals = orderCatalog.deals.map((deal) => ({
    ...deal,
    item_kind: "deal"
  }));

  const catalog = [...products, ...deals];
  if (!query) return catalog.slice(0, 18);

  return catalog.map((item) => {
    const title = String(item.title || "").toLowerCase();
    const description = String(item.description || "").toLowerCase();
    const category = String(item.category || item.type || "").toLowerCase();

    let score = -1;

    if (title.startsWith(query)) score = 400;
    else if (title.includes(query)) score = 300;
    else if (description.startsWith(query)) score = 220;
    else if (description.includes(query)) score = 180;
    else if (category.startsWith(query)) score = 120;
    else if (category.includes(query)) score = 90;

    return { item, score };
  }).filter((entry) => entry.score >= 0)
    .sort((a, b) => b.score - a.score || String(a.item.title || "").localeCompare(String(b.item.title || "")))
    .map((entry) => entry.item)
    .slice(0, 18);
}

function addCatalogItem(item) {
  const existingIndex = draftItems.findIndex((entry) =>
    entry.id === item.id &&
    entry.item_kind === item.item_kind &&
    (entry.rank || "") === ""
  );

  const basePayload = {
    id: item.id,
    item_kind: item.item_kind,
    title: item.title,
    quantity: 1,
    rank: null,
    price: Number(item.price || 0),
    base_price: Number(item.price || 0),
    discount: 0
  };

  if (item.item_kind === "product" && item.has_ranking && Array.isArray(item.ranks) && item.ranks.length) {
    basePayload.rank = item.ranks[0].name;
    basePayload.price = Number(item.ranks[0].price || 0);
    basePayload.base_price = Number(item.ranks[0].price || 0);
    draftItems.push(basePayload);
  } else if (existingIndex >= 0) {
    draftItems[existingIndex].quantity = Number(draftItems[existingIndex].quantity || 1) + 1;
  } else {
    draftItems.push(basePayload);
  }

  renderSummary();
}

function updateDraftItem(index, field, value) {
  const item = draftItems[index];
  if (!item) return;

  if (field === "quantity") {
    item.quantity = Math.max(1, Number(value || 1));
  }

  if (field === "discount") {
    const nextDiscount = Math.max(0, Number(value || 0));
    item.discount = Math.min(nextDiscount, Number(item.base_price || 0));
  }

  if (field === "rank") {
    const product = orderCatalog.products.find((entry) => entry.id === item.id);
    const matchedRank = product?.ranks?.find((rank) => rank.name === value);
    if (matchedRank) {
      item.rank = matchedRank.name;
      item.base_price = Number(matchedRank.price || 0);
      item.price = Number(matchedRank.price || 0);
      item.discount = Math.min(Number(item.discount || 0), item.base_price);
    }
  }

  renderSummary();
}

function removeDraftItem(index) {
  draftItems.splice(index, 1);
  renderSummary();
}

function renderSearchResults() {
  const matches = getCatalogMatches();

  if (!matches.length) {
    orderSearchResults.innerHTML = '<div class="summary-empty">No products or deals matched that search.</div>';
    return;
  }

  orderSearchResults.innerHTML = matches.map((item) => {
    const isProduct = item.item_kind === "product";
    const bundleHtml = !isProduct && Array.isArray(item.bundle_items) && item.bundle_items.length
      ? `<div class="bundle-pills">${item.bundle_items.map((bundle) => `<span class="bundle-pill">${escapeHtml(`${bundle.quantity} x ${bundle.product_title || `Product ${bundle.product_id}`}`)}</span>`).join("")}</div>`
      : "";
    const meta = isProduct
      ? `<span class="item-meta">${escapeHtml(item.category || "Product")}</span>`
      : `<span class="item-meta">${escapeHtml((item.type || "Deal").toUpperCase())}</span>`;

    return `
      <article class="catalog-card">
        <div class="catalog-card-head">
          <div>
            <strong>${escapeHtml(item.title)}</strong>
            <p>${escapeHtml(item.description || (isProduct ? "Product available for ordering." : "Deal available for ordering."))}</p>
          </div>
          ${meta}
        </div>
        ${bundleHtml}
        <div class="catalog-card-footer">
          <span>${formatCurrency(item.price)}</span>
          <button class="btn btn-primary" type="button" data-add-kind="${escapeHtml(item.item_kind)}" data-add-id="${item.id}">Add to Order</button>
        </div>
      </article>
    `;
  }).join("");
}

function renderSummary() {
  if (!draftItems.length) {
    orderSummaryList.innerHTML = '<div class="summary-empty">No items added yet. Search above to build this order.</div>';
    orderSummaryTotal.textContent = formatCurrency(0);
    return;
  }

  orderSummaryList.innerHTML = draftItems.map((item, index) => {
    const product = item.item_kind === "product"
      ? orderCatalog.products.find((entry) => entry.id === item.id)
      : null;

    const rankOptions = product?.ranks?.map((rank) => `
      <option value="${escapeHtml(rank.name)}" ${rank.name === item.rank ? "selected" : ""}>
        ${escapeHtml(`${rank.name} (${formatCurrency(rank.price)})`)}
      </option>
    `).join("") || "";

    const linePrice = Math.max(Number(item.base_price || 0) - (allowDiscounts.checked ? Number(item.discount || 0) : 0), 0);
    const lineMeta = [
      item.item_kind === "deal" ? "Deal" : "Product",
      item.rank || null,
      allowDiscounts.checked && Number(item.discount || 0) > 0 ? `Discount ${formatCurrency(item.discount)}` : null
    ].filter(Boolean).join(" | ");

    return `
      <article class="summary-card">
        <div class="summary-card-head">
          <div>
            <strong>${escapeHtml(item.title)}</strong>
            <p>${escapeHtml(lineMeta || "Ready to save")}</p>
          </div>
          <strong>${formatCurrency(linePrice * Number(item.quantity || 1))}</strong>
        </div>
        <div class="summary-row-grid">
          <div class="summary-field">
            <label>Quantity
              <input type="number" min="1" value="${Number(item.quantity || 1)}" data-field="quantity" data-index="${index}">
            </label>
          </div>
          <div class="summary-field">
            ${rankOptions ? `
              <label>Variant
                <select data-field="rank" data-index="${index}">${rankOptions}</select>
              </label>
            ` : `
              <label>Base Price
                <input type="text" value="${formatCurrency(item.base_price)}" disabled>
              </label>
            `}
          </div>
          <div class="summary-field">
            <label>Discount
              <input type="number" min="0" step="0.01" value="${allowDiscounts.checked ? Number(item.discount || 0) : 0}" data-field="discount" data-index="${index}" ${allowDiscounts.checked ? "" : "disabled"}>
            </label>
          </div>
        </div>
        <div class="catalog-card-footer">
          <span>Unit Price ${formatCurrency(linePrice)}</span>
          <button class="summary-remove" type="button" data-remove-index="${index}">Remove</button>
        </div>
      </article>
    `;
  }).join("");

  orderSummaryTotal.textContent = formatCurrency(computeDraftTotal());
}

function renderEmptyTable(tableBody, label) {
  tableBody.innerHTML = `<tr class="empty-table"><td colspan="8">No ${label.toLowerCase()} right now.</td></tr>`;
}

function setViewMode(mode) {
  orderViewMode = mode;
  document.querySelectorAll("[data-view-mode]").forEach((button) => {
    button.classList.toggle("active", button.dataset.viewMode === mode);
  });
  statusSections.forEach((section) => {
    section.classList.toggle("view-mode-container", mode === "container");
  });
}

function setDetailMode(mode) {
  orderDetailMode = mode;
  document.querySelectorAll("[data-detail-mode]").forEach((button) => {
    button.classList.toggle("active", button.dataset.detailMode === mode);
  });
}

function setPriorityMode(mode) {
  priorityEnabled = mode === "on";
  document.querySelectorAll("[data-priority-mode]").forEach((button) => {
    button.classList.toggle("active", button.dataset.priorityMode === mode);
  });
  savePriorityState();
}

function syncPriorityLists(orders) {
  ["received", "in progress"].forEach((status) => {
    const idsForStatus = orders
      .filter((order) => order.status === status)
      .map((order) => Number(order.id));
    const preserved = priorityOrderState[status].filter((id) => idsForStatus.includes(Number(id)));
    const missing = idsForStatus.filter((id) => !preserved.includes(id));
    priorityOrderState[status] = [...preserved, ...missing];
  });
  savePriorityState();
}

function sortOrdersByPriority(orders) {
  if (!priorityEnabled) return orders;

  syncPriorityLists(orders);

  return [...orders].sort((a, b) => {
    const aStatus = a.status || "";
    const bStatus = b.status || "";

    if (aStatus === bStatus && (aStatus === "received" || aStatus === "in progress")) {
      const list = priorityOrderState[aStatus] || [];
      const aIndex = list.indexOf(Number(a.id));
      const bIndex = list.indexOf(Number(b.id));
      return aIndex - bIndex;
    }

    return 0;
  });
}

function moveOrderPriority(orderId, status, direction) {
  if (!(status === "received" || status === "in progress")) return;

  const list = [...(priorityOrderState[status] || [])];
  const index = list.indexOf(Number(orderId));
  if (index === -1) return;

  const nextIndex = direction === "up" ? index - 1 : index + 1;
  if (nextIndex < 0 || nextIndex >= list.length) return;

  [list[index], list[nextIndex]] = [list[nextIndex], list[index]];
  priorityOrderState[status] = list;
  savePriorityState();
  loadOrders();
}

function renderOrderItems(items) {
  if (!items.length) {
    return '<div class="order-item-card"><div class="order-item-title">No items</div></div>';
  }

  return items.map((item) => {
    const unitPrice = Number(item.price || 0);
    const basePrice = Number(item.base_price ?? item.price ?? 0);
    const discount = Number(item.discount || 0);
    const subtitleParts = [
      item.item_kind === "deal" ? "Deal" : "Product",
      item.rank || null,
      discount > 0 ? `-${formatCurrency(discount)}` : null
    ].filter(Boolean);

    return `
      <div class="order-item-card">
        <div class="order-item-head">
          <div>
            <div class="order-item-title">${escapeHtml(item.title || "Item")}</div>
            <div class="order-item-sub">${escapeHtml(subtitleParts.join(" | "))}</div>
          </div>
          <strong>${formatCurrency(unitPrice * Number(item.quantity || 1))}</strong>
        </div>
        <div class="order-item-sub">Qty ${Number(item.quantity || 1)} | Unit ${formatCurrency(unitPrice)}${discount > 0 ? ` from ${formatCurrency(basePrice)}` : ""}</div>
      </div>
    `;
  }).join("");
}

function buildOrderRow(order) {
  const tr = document.createElement("tr");
  const isNew = !previousOrderIds.has(order.id);
  if (isNew) tr.classList.add("new-order");

  const items = parseOrderItems(order.items);
  const created = order.created_at ? new Date(order.created_at).toLocaleString() : "-";
  const started = order.in_progress_time ? new Date(order.in_progress_time).toLocaleString() : "-";
  const completed = order.completed_time ? new Date(order.completed_time).toLocaleString() : "-";

  const timingHtml = order.status === "received"
    ? `<div class="time-stack"><div><strong>Created</strong></div><small>${created}</small></div>`
    : order.status === "in progress"
      ? `<div class="time-stack"><div><strong>Created</strong></div><small>${created}</small><div><strong>Started</strong></div><small>${started}</small></div>`
      : `<div class="time-stack"><div><strong>Created</strong></div><small>${created}</small><div><strong>Started</strong></div><small>${started}</small><div><strong>Completed</strong></div><small>${completed}</small></div>`;

  tr.innerHTML = `
    <td>
      <div class="customer-stack">
        <div class="customer-name">#${order.order_number || order.id}</div>
        <span class="detail-chip">Order ID ${order.id}</span>
      </div>
    </td>
    <td>
      <div class="customer-stack">
        <div class="customer-name">${escapeHtml(`${order.name || ""} ${order.surname || ""}`.trim() || "Walk-in Customer")}</div>
        <div>${escapeHtml(order.phone || "No phone")}</div>
        <div>${escapeHtml(order.email || "No email")}</div>
      </div>
    </td>
    <td class="order-items">${renderOrderItems(items)}</td>
    <td class="order-note">${escapeHtml(order.note || "No notes added.")}</td>
    <td><strong>${formatCurrency(order.total)}</strong></td>
    <td>${escapeHtml(order.payment_method || "-")}</td>
    <td>${timingHtml}</td>
    <td><div class="action-cluster">${getOrderActionButtons(order)}</div></td>
  `;

  previousOrderIds.add(order.id);
  return tr;
}

function getOrderActionButtons(order) {
  const buttons = [
    `<button class="table-action-btn edit" type="button" data-edit-order="${order.id}">Edit Items</button>`
  ];

  if (order.status === "received") {
    buttons.push(`<button class="table-action-btn start" type="button" data-status-order="${order.id}" data-next-status="in progress">Start</button>`);
  }

  if (order.status === "in progress") {
    buttons.push(`<button class="table-action-btn complete" type="button" data-status-order="${order.id}" data-next-status="completed">Complete</button>`);
  }

  if (priorityEnabled && (order.status === "received" || order.status === "in progress")) {
    buttons.push(`
      <div class="priority-actions">
        <button class="table-action-btn priority" type="button" data-priority-order="${order.id}" data-priority-status="${escapeHtml(order.status)}" data-priority-direction="up">&uarr;</button>
        <button class="table-action-btn priority" type="button" data-priority-order="${order.id}" data-priority-status="${escapeHtml(order.status)}" data-priority-direction="down">&darr;</button>
      </div>
    `);
  }

  return buttons.join("");
}

function buildOrderCard(order) {
  const items = parseOrderItems(order.items);
  const displayName = `${order.name || ""} ${order.surname || ""}`.trim() || "Walk-in Customer";
  const orderNumber = order.order_number || order.id;
  const statusLabel = order.status || "received";
  const created = order.created_at ? new Date(order.created_at).toLocaleString() : "-";
  const started = order.in_progress_time ? new Date(order.in_progress_time).toLocaleString() : "-";
  const completed = order.completed_time ? new Date(order.completed_time).toLocaleString() : "-";

  if (orderDetailMode === "short") {
    const itemBriefs = items.map((i) => {
      const qty = Number(i.quantity || 1);
      return `<span class="item-brief-pill">${escapeHtml(i.title || "Item")}${qty > 1 ? ` ×${qty}` : ""}</span>`;
    }).join("");

    return `
      <article class="order-card order-card-short" data-order-detail="${order.id}" style="cursor:pointer;">
        <div class="order-card-head">
          <div class="order-card-kicker">${escapeHtml(statusLabel)}</div>
          <div class="order-card-title-row">
            <div>
              <div class="order-card-title">${escapeHtml(displayName)}</div>
              <div class="order-card-subtitle">Order #${escapeHtml(String(orderNumber))}</div>
            </div>
          </div>
        </div>
        <div class="order-card-items-brief">${itemBriefs || '<span class="item-brief-pill">No items</span>'}</div>
        <div class="order-card-actions" onclick="event.stopPropagation()">${getOrderActionButtons(order)}</div>
      </article>
    `;
  }

  const details = [
    ["Customer", `${displayName}${order.phone ? ` | ${order.phone}` : ""}${order.email ? ` | ${order.email}` : ""}`],
    ["Note", order.note || "No notes added."],
    ["Payment", order.payment_method || "-"],
    ["Timeline", `Created: ${created}${order.status !== "received" ? ` | Started: ${started}` : ""}${order.status === "completed" ? ` | Completed: ${completed}` : ""}`]
  ];

  return `
    <article class="order-card">
      <div class="order-card-head">
        <div class="order-card-kicker">${escapeHtml(statusLabel)}</div>
        <div class="order-card-title-row">
          <div>
            <div class="order-card-title">${escapeHtml(displayName)}</div>
            <div class="order-card-subtitle">Order #${escapeHtml(orderNumber)}</div>
          </div>
          <span class="detail-chip">${formatCurrency(order.total)}</span>
        </div>
      </div>
      <ul class="order-card-detail-list">
        <li class="order-card-detail items-detail">
          <strong>Items</strong>
          <div class="order-items">${renderOrderItems(items)}</div>
        </li>
        ${details.map(([label, value]) => `
          <li class="order-card-detail">
            <strong>${escapeHtml(label)}</strong>
            <span>${escapeHtml(value)}</span>
          </li>
        `).join("")}
      </ul>
      <div class="order-card-actions">${getOrderActionButtons(order)}</div>
    </article>
  `;
}

async function loadCatalog() {
  const res = await fetch(api("/order_catalog"));
  if (!res.ok) return;
  orderCatalog = await res.json();
  renderSearchResults();
}

async function updateStatus(orderId, status) {
  await fetch(api(`/update_order_status/${orderId}`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status })
  });
  loadOrders();
}

function hydrateModalFromOrder(order) {
  currentOrderId = order.id;
  orderModalTitle.textContent = `Edit Order #${order.order_number || order.id}`;
  orderModalCopy.textContent = "Adjust items, discounts, notes, and customer details. Saving will recalculate the order total.";
  customerFields.name.value = order.name || "";
  customerFields.surname.value = order.surname || "";
  customerFields.phone.value = order.phone || "";
  customerFields.email.value = order.email || "";
  customerFields.payment.value = order.payment_method || "cash";
  customerFields.note.value = order.note || "";
  document.getElementById("orderStatusPreview").value = order.status || "received";

  draftItems = parseOrderItems(order.items).map((item) => ({
    ...item,
    quantity: Number(item.quantity || 1),
    price: Number(item.price || 0),
    base_price: Number(item.base_price ?? item.price ?? 0),
    discount: Number(item.discount || 0)
  }));
  allowDiscounts.checked = draftItems.some((item) => Number(item.discount || 0) > 0);
  renderSearchResults();
  renderSummary();
  orderModal.classList.add("open");
  orderModal.setAttribute("aria-hidden", "false");
}

async function openEditOrder(orderId) {
  const res = await fetch(api("/get_orders"));
  if (!res.ok) return;
  const orders = await res.json();
  const order = orders.find((entry) => Number(entry.id) === Number(orderId));
  if (!order) return;
  hydrateModalFromOrder(order);
}

async function saveOrder() {
  if (!draftItems.length) {
    alert("Add at least one product or deal before saving.");
    return;
  }

  const payload = readDraftPayload();
  const endpoint = currentOrderId ? api(`/orders/${currentOrderId}`) : api("/add_order");
  const res = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });

  if (!res.ok) {
    alert("The order could not be saved.");
    return;
  }

  closeOrderModal();
  await loadOrders();
}

document.addEventListener("click", async (event) => {
  const addButton = event.target.closest("[data-add-id]");
  if (addButton) {
    const type = addButton.dataset.addKind;
    const collection = type === "deal" ? orderCatalog.deals : orderCatalog.products;
    const item = collection.find((entry) => String(entry.id) === addButton.dataset.addId);
    if (item) addCatalogItem({ ...item, item_kind: type });
    return;
  }

  const removeButton = event.target.closest("[data-remove-index]");
  if (removeButton) {
    removeDraftItem(Number(removeButton.dataset.removeIndex));
    return;
  }

  const editButton = event.target.closest("[data-edit-order]");
  if (editButton) {
    await openEditOrder(editButton.dataset.editOrder);
    return;
  }

  const statusButton = event.target.closest("[data-status-order]");
  if (statusButton) {
    await updateStatus(statusButton.dataset.statusOrder, statusButton.dataset.nextStatus);
    return;
  }

  const priorityButton = event.target.closest("[data-priority-order]");
  if (priorityButton) {
    moveOrderPriority(
      priorityButton.dataset.priorityOrder,
      priorityButton.dataset.priorityStatus,
      priorityButton.dataset.priorityDirection
    );
  }
});

document.addEventListener("input", (event) => {
  if (event.target === orderSearch) {
    renderSearchResults();
  }
});

document.addEventListener("change", (event) => {
  const field = event.target.dataset.field;
  if (!field) return;
  updateDraftItem(Number(event.target.dataset.index), field, event.target.value);
});

document.getElementById("openOrderModal")?.addEventListener("click", openOrderModal);
document.getElementById("closeOrderModal")?.addEventListener("click", closeOrderModal);
document.getElementById("cancelOrderModal")?.addEventListener("click", closeOrderModal);
allowDiscounts?.addEventListener("change", renderSummary);
saveOrderBtn?.addEventListener("click", saveOrder);
document.querySelectorAll("[data-view-mode]").forEach((button) => {
  button.addEventListener("click", () => setViewMode(button.dataset.viewMode));
});
document.querySelectorAll("[data-detail-mode]").forEach((button) => {
  button.addEventListener("click", async () => {
    setDetailMode(button.dataset.detailMode);
    await loadOrders();
  });
});
document.querySelectorAll("[data-priority-mode]").forEach((button) => {
  button.addEventListener("click", async () => {
    setPriorityMode(button.dataset.priorityMode);
    await loadOrders();
  });
});

orderModal?.addEventListener("click", (event) => {
  if (event.target === orderModal) closeOrderModal();
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && orderModal?.classList.contains("open")) closeOrderModal();
});

let cachedOrders = [];

const orderDetailModal = document.getElementById("orderDetailModal");
const orderDetailClose = document.getElementById("closeOrderDetailModal");

function openOrderDetail(orderId) {
  const order = cachedOrders.find((o) => Number(o.id) === Number(orderId));
  if (!order || !orderDetailModal) return;

  const items = parseOrderItems(order.items);
  const displayName = `${order.name || ""} ${order.surname || ""}`.trim() || "Walk-in Customer";
  const orderNumber = order.order_number || order.id;
  const created = order.created_at ? new Date(order.created_at).toLocaleString() : "-";
  const started = order.in_progress_time ? new Date(order.in_progress_time).toLocaleString() : "-";
  const completed = order.completed_time ? new Date(order.completed_time).toLocaleString() : "-";

  document.getElementById("orderDetailTitle").textContent = `Order #${orderNumber}`;
  document.getElementById("orderDetailBody").innerHTML = `
    <div class="detail-modal-grid">
      <section class="detail-section">
        <h3 class="panel-title">Customer</h3>
        <dl class="detail-dl">
          <dt>Name</dt><dd>${escapeHtml(displayName)}</dd>
          <dt>Phone</dt><dd>${escapeHtml(order.phone || "—")}</dd>
          <dt>Email</dt><dd>${escapeHtml(order.email || "—")}</dd>
          <dt>Payment</dt><dd>${escapeHtml(order.payment_method || "—")}</dd>
          <dt>Note</dt><dd>${escapeHtml(order.note || "No notes.")}</dd>
        </dl>
      </section>
      <section class="detail-section">
        <h3 class="panel-title">Timing</h3>
        <dl class="detail-dl">
          <dt>Status</dt><dd>${escapeHtml(order.status || "received")}</dd>
          <dt>Created</dt><dd>${escapeHtml(created)}</dd>
          ${order.status !== "received" ? `<dt>Started</dt><dd>${escapeHtml(started)}</dd>` : ""}
          ${order.status === "completed" ? `<dt>Completed</dt><dd>${escapeHtml(completed)}</dd>` : ""}
          <dt>Total</dt><dd><strong>${formatCurrency(order.total)}</strong></dd>
        </dl>
      </section>
    </div>
    <section class="detail-section" style="margin-top:1rem;">
      <h3 class="panel-title">Items</h3>
      <div class="order-items">${renderOrderItems(items)}</div>
    </section>
    <div class="detail-modal-actions">${getOrderActionButtons(order)}</div>
  `;

  orderDetailModal.classList.add("open");
  orderDetailModal.setAttribute("aria-hidden", "false");
}

function closeOrderDetail() {
  if (!orderDetailModal) return;
  orderDetailModal.classList.remove("open");
  orderDetailModal.setAttribute("aria-hidden", "true");
}

orderDetailClose?.addEventListener("click", closeOrderDetail);
orderDetailModal?.addEventListener("click", (e) => { if (e.target === orderDetailModal) closeOrderDetail(); });
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && orderDetailModal?.classList.contains("open")) closeOrderDetail();
});

document.addEventListener("click", (e) => {
  const card = e.target.closest("[data-order-detail]");
  if (card && !e.target.closest("[data-status-order]") && !e.target.closest("[data-edit-order]") && !e.target.closest("[data-priority-order]")) {
    openOrderDetail(card.dataset.orderDetail);
  }
});

async function loadOrders() {
  const res = await fetch(api("/get_orders"));
  if (!res.ok) return;

  const orders = sortOrdersByPriority(await res.json());
  cachedOrders = orders;

  const receivedTable = document.querySelector("#received-orders tbody");
  const inProgressTable = document.querySelector("#in-progress-orders tbody");
  const completedTable = document.querySelector("#completed-orders tbody");
  const receivedCards = document.getElementById("received-order-cards");
  const inProgressCards = document.getElementById("in-progress-order-cards");
  const completedCards = document.getElementById("completed-order-cards");

  receivedTable.innerHTML = "";
  inProgressTable.innerHTML = "";
  completedTable.innerHTML = "";
  receivedCards.innerHTML = "";
  inProgressCards.innerHTML = "";
  completedCards.innerHTML = "";

  orders.forEach((order) => {
    const row = buildOrderRow(order);
    const cardHtml = buildOrderCard(order);

    if (order.status === "received") {
      receivedTable.appendChild(row);
      receivedCards.insertAdjacentHTML("beforeend", cardHtml);
    } else if (order.status === "in progress") {
      inProgressTable.appendChild(row);
      inProgressCards.insertAdjacentHTML("beforeend", cardHtml);
    } else {
      completedTable.appendChild(row);
      completedCards.insertAdjacentHTML("beforeend", cardHtml);
    }
  });

  if (!receivedTable.children.length) renderEmptyTable(receivedTable, "Incoming Orders");
  if (!inProgressTable.children.length) renderEmptyTable(inProgressTable, "In Progress Orders");
  if (!completedTable.children.length) renderEmptyTable(completedTable, "Completed Orders");
  if (!receivedCards.children.length) receivedCards.innerHTML = '<div class="summary-empty">No incoming orders right now.</div>';
  if (!inProgressCards.children.length) inProgressCards.innerHTML = '<div class="summary-empty">No in progress orders right now.</div>';
  if (!completedCards.children.length) completedCards.innerHTML = '<div class="summary-empty">No completed orders right now.</div>';
}

loadPriorityState();
loadCatalog();
setViewMode(orderViewMode);
setDetailMode(orderDetailMode);
setPriorityMode(priorityEnabled ? "on" : "off");
loadOrders();
setInterval(loadOrders, 3000);
