const adminSlugMatch = window.location.pathname.match(/^\/admin\/([^/]+)/);
const adminBasePath = adminSlugMatch ? `/admin/${adminSlugMatch[1]}` : '';
const adminApi = (path) => `${adminBasePath}${path}`;

let previousOrderIds = new Set();

async function loadOrders() {
  const res = await fetch(adminApi('/get_orders'));
  const orders = await res.json();

  const receivedTable = document.querySelector('#received-orders tbody');
  const inProgressTable = document.querySelector('#in-progress-orders tbody');
  const completedTable = document.querySelector('#completed-orders tbody');

  receivedTable.innerHTML = '';
  inProgressTable.innerHTML = '';
  completedTable.innerHTML = '';

  orders.forEach(order => {

    const tr = document.createElement('tr');

    const isNew = !previousOrderIds.has(order.id);
    if (isNew) {
      tr.classList.add('new-order');
    }

    // ✅ Parse items properly
    let itemsHtml = '';
    try {
      const items = JSON.parse(order.items);
      itemsHtml = items.map(i =>
        `${i.title} x${i.quantity}`
      ).join('<br>');
    } catch {
      itemsHtml = order.items;
    }

const created = new Date(order.created_at).toLocaleString();
const started = order.in_progress_time
  ? new Date(order.in_progress_time).toLocaleString()
  : '-';

const completed = order.completed_time
  ? new Date(order.completed_time).toLocaleString()
  : '-';

tr.innerHTML = `
  <td>${order.id}</td>
  <td>${order.name || ''} ${order.surname || ''}</td>
  <td class="order-items">${itemsHtml}</td>
  <td>$${parseFloat(order.total).toFixed(2)}</td>
  <td>${order.payment_method}</td>

  ${
    order.status === 'received'
      ? `<td>${created}</td>`
      : order.status === 'in progress'
      ? `<td>
            <div>Created: ${created}</div>
            <div>Started: ${started}</div>
         </td>`
      : `<td>
            <div>Created: ${created}</div>
            <div>Started: ${started}</div>
            <div>Completed: ${completed}</div>
         </td>`
  }

  <td>
    ${
      order.status === 'received'
        ? `<button onclick="updateStatus(${order.id}, 'in progress')" class="btn-start">Start</button>`
        : order.status === 'in progress'
        ? `<button onclick="updateStatus(${order.id}, 'completed')" class="btn-start">Complete</button>`
        : ''
    }
  </td>
`;

    // ✅ ROUTE TO CORRECT TABLE
    if (order.status === 'received') {
      receivedTable.appendChild(tr);
    } else if (order.status === 'in progress') {
      inProgressTable.appendChild(tr);
    } else if (order.status === 'completed') {
      completedTable.appendChild(tr);
    }

    previousOrderIds.add(order.id);
  });
}

document.addEventListener('click', () => {
  notificationSound.play().then(() => {
    notificationSound.pause();
    notificationSound.currentTime = 0;
  }).catch(() => {});
}, { once: true });


async function updateStatus(orderId, status) {
  await fetch(adminApi('/update_order_status/' + orderId), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status })
  });

  loadOrders();
}

loadOrders();
setInterval(loadOrders, 3000); // refresh every 3 seconds
