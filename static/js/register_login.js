// Legacy auth pages (register, password reset via base_legacy_auth.html).
// /login/ uses Alpine for password toggle — eyes span not present on that page.
// register
const inputs = document.querySelectorAll('.input');
const checkBox = document.querySelector('#show-pass');
const inputPassword = document.querySelectorAll('.input-password');
const eyes = document.querySelector('span.eyes');
const openEye = document.querySelector('.fa-eye');
const slashEye = document.querySelector('.fa-eye-slash');

function action(e) {
  const parent = e.target.parentNode.parentNode;
  if (e.type === 'focus') parent.classList.add(this);
  if (e.type === 'blur' && e.target.value == '') parent.classList.remove(this);
}

inputs.forEach((input) => (input.addEventListener('focus', action.bind('focus')), input.addEventListener('blur', action.bind('focus'))));

// password viewer

if (checkBox) {
  checkBox.addEventListener('click', function (e) {
    inputPassword.forEach((el) => {
      if (this.checked) el.type = 'text';
      else el.type = 'password';
    });
  });
}

//login — password visibility toggle (legacy register layout; login uses Alpine)
if (eyes) {
  eyes.addEventListener('click', function () {
    const input = this.parentElement.querySelector('input[type="password"], input[type="text"]');
    if (!input) return;
    if (input.type === 'password') {
      openEye.style.visibility = 'hidden';
      slashEye.style.visibility = 'visible';
      input.type = 'text';
    } else {
      slashEye.style.visibility = 'hidden';
      openEye.style.visibility = 'visible';
      input.type = 'password';
    }
  });
}

// Auto-dismiss flash messages on auth pages (no jQuery)
document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('[data-dismiss="alert"]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      btn.closest('.alert')?.remove();
    });
  });

  document.querySelectorAll('.alert-success, .alert-danger').forEach(function (alert) {
    setTimeout(function () {
      alert.style.transition = 'opacity 0.3s';
      alert.style.opacity = '0';
      setTimeout(function () {
        alert.remove();
      }, 300);
    }, 5000);
  });
});
