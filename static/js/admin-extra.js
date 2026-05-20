// Jazzmin admin footer text (avatar comes from JAZZMIN_SETTINGS user_avatar).
document.addEventListener('DOMContentLoaded', () => {
  const footer = document.querySelector('.main-footer > div');
  if (footer) {
    const link = document.createElement('a');
    link.href = 'https://github.com/paultumabini';
    link.textContent = '@paultumabini';
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    footer.textContent = '';
    footer.appendChild(link);
  }
});
