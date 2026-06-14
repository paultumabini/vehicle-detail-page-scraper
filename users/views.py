"""
User auth views — login, register, logout, profile.

Auth UI polish (vdp-auth-* in main.css):
  - MyLogoutView: Django 6 POST-only logout; nav uses CSRF form in base.html.
  - register: redirects authenticated users to home; template uses _auth_brand_mark.html.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.shortcuts import redirect, render

from webscraping.constants import DEMO_READ_ONLY_USERNAME

from .forms import MyLogInForm, ProfileUpdateForm, UserRegisterForm, UserUpdateForm


def register(request):
    """
    Sign-up page (/register/).

    Creates a User + Profile (via signal). On success, redirects to /login/
    with a flash message; invalid submissions re-render with field errors.
    Authenticated users are sent to home (same idea as MyLoginView redirect).
    """
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':
        form = UserRegisterForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(
                request,
                'Your account has been created. You can now log in.',
                extra_tags='text-center',
            )
            return redirect('login')
    else:
        form = UserRegisterForm()

    return render(request, 'users/register.html', {'form': form})


@login_required
def profile(request):
    """
    User profile editor (/profile/).

    Updates username, email, and avatar. The seeded demo account
    (``DEMO_READ_ONLY_USERNAME``) is read-only.
    """
    is_read_only = request.user.get_username() == DEMO_READ_ONLY_USERNAME

    if request.method == 'POST':
        user_form = UserUpdateForm(request.POST, instance=request.user)
        profile_form = ProfileUpdateForm(
            request.POST, request.FILES, instance=request.user.profile
        )

        if is_read_only:
            messages.warning(
                request,
                'You are not authorized to edit this profile.',
                extra_tags='exclamation',
            )
            return redirect('profile')

        if user_form.is_valid() and profile_form.is_valid():
            user_form.save()
            profile_form.save()
            messages.success(
                request,
                'Your account has been updated.',
                extra_tags='check',
            )
            return redirect('profile')

    else:
        user_form = UserUpdateForm(instance=request.user)
        profile_form = ProfileUpdateForm(instance=request.user.profile)

    context = {
        'user_form': user_form,
        'profile_form': profile_form,
        'is_read_only': is_read_only,  # DEMO_READ_ONLY_USERNAME — disables fieldset in template
    }
    return render(request, 'users/profile.html', context)


class MyLoginView(LoginView):
    """
    Sign-in page (/login/).

    Uses MyLogInForm for validation; template renders vdp-auth-* fields manually.
    redirect_authenticated_user sends logged-in users to LOGIN_REDIRECT_URL.
    """

    authentication_form = MyLogInForm
    template_name = 'users/login.html'
    redirect_authenticated_user = True


class MyLogoutView(LogoutView):
    """
    Sign-out (/logout/).

    Django 6 accepts POST only — the nav dropdown submits a CSRF form, not a GET link.
    Renders users/logout.html after the session is cleared.
    """

    template_name = 'users/logout.html'
    http_method_names = ['post', 'options']
