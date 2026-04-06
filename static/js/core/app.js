document.addEventListener("DOMContentLoaded", () => {

    console.log("App Initialising...");

    if (window.MenuSystem) {
        MenuSystem.init();
    }

    if (window.EcommerceSystem) {
        EcommerceSystem.init();
    }

});
