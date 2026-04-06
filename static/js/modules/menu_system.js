window.MenuSystem = {

    menuData: [],

    async init() {

        const menuContainer = document.getElementById('menu');
        const tabsContainer = document.getElementById('menu-tabs');

        if (!menuContainer || !tabsContainer) return;

        console.log("Menu System Active");

        await this.fetchMenu();
        await this.fetchDeals();
    },

    async fetchMenu() {
        try {
            const categories = await API.getCategories();
            const products = await API.getProducts();

            this.menuData = categories.map(cat => ({
                ...cat,
                products: products.filter(p => p.category_id === cat.id)
            }));

            this.renderMenu();
        } catch (err) {
            console.error("Menu fetch failed", err);
        }
    },

    renderMenu() {

        const menuContainer = document.getElementById('menu');
        const tabsContainer = document.getElementById('menu-tabs');

        menuContainer.innerHTML = '';
        tabsContainer.innerHTML = '';

        const allTab = document.createElement('div');
        allTab.classList.add('menu-tab', 'active');
        allTab.dataset.category = 'All';
        allTab.textContent = 'All';
        tabsContainer.appendChild(allTab);

        this.menuData.forEach(cat => {
            const tab = document.createElement('div');
            tab.classList.add('menu-tab');
            tab.textContent = cat.name;
            tab.dataset.category = cat.name;
            tabsContainer.appendChild(tab);
        });

        this.menuData.forEach(cat => {

            const group = document.createElement('div');
            group.classList.add('category-group');
            group.dataset.category = cat.name;

            cat.products.forEach(product => {

                const card = document.createElement('div');
                card.classList.add('menu-card');

                card.innerHTML = `
                    ${product.image_path ? `<img class="menu-card-img" src="${product.image_path}">` : ''}
                    <div class="menu-card-body">
                        <h3>${product.title}</h3>
                        <p>${product.description}</p>
                        <div class="menu-card-footer">
                            <span>$${parseFloat(product.price).toFixed(2)}</span>
                            ${ (window.EcommerceSystem || !!(window.PROJECT_MODULES && window.PROJECT_MODULES.online_ordering_system)) ? `<button class="add-btn">Add</button>` : ''}
                        </div>
                    </div>
                `;

                if (window.EcommerceSystem || (window.PROJECT_MODULES && window.PROJECT_MODULES.online_ordering_system)) {
                    card.querySelector('.add-btn')
                        ?.addEventListener('click', () =>
                            (window.EcommerceSystem ? EcommerceSystem.addToCart(product) : window.CartAPI?.add(product)));
                }

                group.appendChild(card);
            });

            menuContainer.appendChild(group);
        });

        tabsContainer.addEventListener('click', e => {

            if (!e.target.classList.contains('menu-tab')) return;

            const selected = e.target.dataset.category;

            document.querySelectorAll('.menu-tab')
                .forEach(t => t.classList.toggle('active',
                    t.dataset.category === selected));

            document.querySelectorAll('.category-group')
                .forEach(g => {
                    g.style.display =
                        selected === 'All' || g.dataset.category === selected
                        ? 'flex'
                        : 'none';
                });
        });
    },

    async fetchDeals() {
        try {
            const deals = await API.getDeals();

            const dealsContainer = document.getElementById('deals-container');
            const hotContainer = document.getElementById('hot-deals-container');

            if (!dealsContainer || !hotContainer) return;

            deals.forEach(deal => {

                const card = document.createElement('div');
                card.classList.add('deal-card');

                card.innerHTML = `
                    <img src="${deal.image_path}">
                    <h3>${deal.title}</h3>
                    <p>${deal.description}</p>
                    <span>$${parseFloat(deal.price).toFixed(2)}</span>
                    ${window.EcommerceSystem ? `<button class="add-btn">Add</button>` : ''}
                `;

                if (window.EcommerceSystem) {
                    card.querySelector('.add-btn')
                        ?.addEventListener('click', () =>
                            EcommerceSystem.addToCart(deal));
                }

                (deal.type === 'deal' ? dealsContainer : hotContainer)
                    .appendChild(card);
            });

        } catch (err) {
            console.error("Deals fetch failed", err);
        }
    }
};
