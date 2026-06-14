// Unfold admin — inject author below the sidebar user/profile panel.
// appendChild places the credit after the user panel (below profile).
document.addEventListener('DOMContentLoaded', () => {
  const sidebar = document.querySelector('#nav-sidebar-inner');
  if (!sidebar) return;

  const credit = document.createElement('div');
  credit.style.cssText = 'padding:0.4rem 1.5rem 0.6rem;text-align:center;';
  credit.innerHTML =
    '<a href="https://github.com/paultumabini" target="_blank" rel="noopener noreferrer" ' +
    'style="font-size:11px;color:#a78bfa;text-decoration:none;opacity:0.7;">@paultumabini</a>';

  sidebar.appendChild(credit);
});
