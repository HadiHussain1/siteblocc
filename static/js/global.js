function getGlobalLoader() {
  return document.getElementById('global-loader');
}

function showLoader() {
  const loader = getGlobalLoader();
  if (loader) {
    loader.classList.add('active');
  }
}

function hideLoader() {
  const loader = getGlobalLoader();
  if (loader) {
    loader.classList.remove('active');
  }
}

document.addEventListener('DOMContentLoaded', () => {
  hideLoader();

  document.querySelectorAll('form').forEach((form) => {
    form.addEventListener('submit', (event) => {
      if (event.defaultPrevented) {
        hideLoader();
        return;
      }

      if (typeof form.checkValidity === 'function' && !form.checkValidity()) {
        hideLoader();
        return;
      }

      showLoader();
    });
  });

  document.querySelectorAll('[data-show-loader="true"]').forEach((element) => {
    element.addEventListener('click', () => {
      showLoader();
    });
  });
});

window.addEventListener('pageshow', hideLoader);
