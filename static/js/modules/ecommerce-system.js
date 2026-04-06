window.EcommerceSystem = {

    cart: [],

    init() {
        console.log("Ecommerce System Active");
    },

    addToCart(item) {

        const existing = this.cart.find(i => i.id === item.id);

        if (existing) {
            existing.quantity = (existing.quantity || 1) + 1;
        } else {
            this.cart.push({...item, quantity: 1});
        }

        this.updateCartUI();
    },

    updateCartUI() {

        const count = document.getElementById("cart-count");
        const totalEl = document.getElementById("cart-total");

        if (!count || !totalEl) return;

        count.innerText = this.cart.length;

        const total = this.cart.reduce((sum, i) =>
            sum + (i.price * (i.quantity || 1)), 0);

        totalEl.innerText = `$${total.toFixed(2)}`;
    }
};
