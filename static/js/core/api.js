const API = {

    getCategories: () => fetch('/api/categories').then(r => r.json()),
    getProducts: () => fetch('/api/products').then(r => r.json()),
    getDeals: () => fetch('/api/deals').then(r => r.json()),

    submitOrder: (payload) =>
        fetch('/api/order', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        }).then(r => r.json())
};
