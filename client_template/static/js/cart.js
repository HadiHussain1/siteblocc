let cart = JSON.parse(localStorage.getItem('cart')) || [];
window.cart = cart;

function getCartItemKey(item) {
  return [
    item.item_kind || 'product',
    item.id,
    item.rank || '',
    item.category || '',
    item.title || ''
  ].join('|');
}

function getCartDisplayName(item) {
  return item.rank ? `${item.title} (${item.rank})` : item.title;
}

window.addToCart = function addToCart(item) {
  const normalizedItem = {
    ...item,
    item_kind: item.item_kind || 'product',
    price: Number(item.price || 0)
  };

  const existingIndex = cart.findIndex(cartItem => getCartItemKey(cartItem) === getCartItemKey(normalizedItem));

  if (existingIndex > -1) {
    cart[existingIndex].quantity = (cart[existingIndex].quantity || 1) + 1;
  } else {
    cart.push({ ...normalizedItem, quantity: 1 });
  }

  saveCart();
  updateCartDisplay();
  updateCartPreview();
  updateCartCount();
};

function saveCart() {
  localStorage.setItem('cart', JSON.stringify(cart));
}

function calculateTotal(items) {
  return items.reduce((sum, item) => sum + (Number(item.price || 0) * (item.quantity || 1)), 0);
}

function groupCartItems() {
  const map = {};

  cart.forEach((item) => {
    const key = getCartItemKey(item);
    if (!map[key]) {
      map[key] = {
        key,
        id: item.id,
        title: item.title,
        displayName: getCartDisplayName(item),
        category: item.category,
        rank: item.rank || null,
        item_kind: item.item_kind || 'product',
        price: Number(item.price || 0),
        qty: 0
      };
    }

    map[key].qty += item.quantity || 1;
  });

  return Object.values(map);
}

function updateCartDisplay() {
  const cartItems = document.getElementById('cart-items');
  const totalElement = document.getElementById('cart-total');
  if (!cartItems) return;

  cartItems.innerHTML = '';

  if (cart.length === 0) {
    cartItems.innerHTML = '<p class="cart-empty">Your cart is empty</p>';
  } else {
    groupCartItems().forEach((group) => {
      const div = document.createElement('div');
      div.classList.add('cart-item');
      div.innerHTML = `
        <div class="cart-item-main">
          <span class="cart-item-qty">${group.qty}x</span>
          <div class="cart-item-copy">
            <strong class="cart-item-title">${group.displayName}</strong>
            <span class="cart-item-meta">$${group.price.toFixed(2)} each</span>
          </div>
        </div>
        <span class="cart-item-total">$${(group.price * group.qty).toFixed(2)}</span>
        <button class="remove-item">×</button>
      `;

      div.querySelector('.remove-item')?.addEventListener('click', () => {
        const index = cart.findIndex(item => getCartItemKey(item) === group.key);
        if (index !== -1) {
          if ((cart[index].quantity || 1) > 1) {
            cart[index].quantity -= 1;
          } else {
            cart.splice(index, 1);
          }
        }

        saveCart();
        updateCartDisplay();
        updateCartPreview();
        updateCartCount();
      });

      cartItems.appendChild(div);
    });
  }

  if (totalElement) {
    totalElement.textContent = `$${calculateTotal(cart).toFixed(2)}`;
  }
}

function updateCartPreview() {
  const previewItems = document.getElementById('cart-preview-items');
  const previewTotal = document.getElementById('cart-preview-total');
  if (!previewItems || !previewTotal) return;

  const totalQty = cart.reduce((sum, item) => sum + (item.quantity || 1), 0);
  const totalPrice = calculateTotal(cart);

  previewItems.innerHTML = '';

  if (totalQty === 0) {
    previewItems.innerHTML = '<p class="cart-empty">Your cart is empty</p>';
    previewTotal.textContent = '$0.00';
  } else {
    previewItems.innerHTML = `<p>You have <strong>${totalQty}</strong> item${totalQty > 1 ? 's' : ''}</p>`;
    previewTotal.textContent = `$${totalPrice.toFixed(2)}`;
  }
}

function updateCartCount() {
  const countEl = document.getElementById('cart-count');
  if (!countEl) return;

  const totalQty = cart.reduce((sum, item) => sum + (item.quantity || 1), 0);
  countEl.textContent = totalQty;
}

const cartSidebar = document.querySelector('.cart-sidebar');
if (cartSidebar) {
  const cartToggleBtn = document.createElement('button');
  cartToggleBtn.className = 'cart-toggle-btn';
  cartToggleBtn.innerHTML = '🛒';
  document.body.appendChild(cartToggleBtn);

  if (!window.location.pathname.includes('menu')) {
    cartSidebar.classList.add('collapsed');
  }

  cartToggleBtn.addEventListener('click', () => {
    cartSidebar.classList.toggle('collapsed');
  });

  if (window.innerWidth < 900) {
    cartSidebar.classList.add('collapsed');
  }
}

const cartIcon = document.querySelector('.cart-icon');
const cartPreview = document.querySelector('.cart-preview');
if (cartIcon && cartPreview) {
  let closeTimeout;

  cartIcon.addEventListener('mouseenter', () => {
    clearTimeout(closeTimeout);
    cartPreview.classList.add('open');
  });

  cartPreview.addEventListener('mouseenter', () => clearTimeout(closeTimeout));

  const startCloseTimer = () => {
    closeTimeout = setTimeout(() => cartPreview.classList.remove('open'), 1000);
  };

  cartIcon.addEventListener('mouseleave', startCloseTimer);
  cartPreview.addEventListener('mouseleave', startCloseTimer);
}

function toggleOrderSummary() {
  document.getElementById('orderSummarySidebar')?.classList.toggle('active');
}

function checkout() {
  const storedCart = JSON.parse(localStorage.getItem('cart')) || [];
  if (storedCart.length === 0) {
    alert('Your cart is empty');
    return;
  }

  localStorage.setItem('checkout_order', JSON.stringify({
    items: storedCart,
    total: calculateTotal(storedCart)
  }));
  window.location.href = publicPath('/checkout');
}

function goToInstoreCheckout() {
  const storedCart = JSON.parse(localStorage.getItem('cart')) || [];
  if (storedCart.length === 0) {
    alert('Your cart is empty');
    return;
  }

  localStorage.setItem('checkout_order', JSON.stringify({
    items: storedCart,
    total: calculateTotal(storedCart)
  }));
  window.location.href = publicPath('/checkout-instore');
}

updateCartDisplay();
updateCartPreview();
updateCartCount();
