
if (typeof window.nextRoute === 'undefined') window.nextRoute = null;

function openMembershipModal(route) {
  window.nextRoute = route;
  const modal = document.getElementById('memberModal');
  if (modal) modal.style.display = 'flex';
}

function continueCheckout() {
  const modal = document.getElementById('memberModal');
  if (modal) modal.style.display = 'none';

  if (window.nextRoute) {
    window.location.href = window.nextRoute;
  }
}