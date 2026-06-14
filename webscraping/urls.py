"""webscraping URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_view
from django.urls import include, path, reverse_lazy
from users import views as user_views

urlpatterns = [
    path('admin/', admin.site.urls),
    # Auth — vdp-auth-* templates in users/templates/users/
    #
    # Logout: POST-only in Django 6 — MyLogoutView + CSRF form in project/base.html
    #   (GET /logout/ returns 405; do not revert to href link).
    # Password reset: explicit success_url on reset + confirm views.
    # Brand mark on form pages: users/_auth_brand_mark.html (replaces profile_login.png).
    path('register/', user_views.register, name='register'),
    path('profile/', user_views.profile, name='profile'),
    path(
        'login/',
        user_views.MyLoginView.as_view(template_name='users/login.html'),
        name='login',
    ),
    path('logout/', user_views.MyLogoutView.as_view(), name='logout'),
    path(
        'password-reset/',
        auth_view.PasswordResetView.as_view(
            template_name='users/password_reset.html',
            success_url=reverse_lazy('password_reset_done'),
        ),
        name='password_reset',
    ),
    path(
        'password-reset/done/',
        auth_view.PasswordResetDoneView.as_view(
            template_name='users/password_reset_done.html'
        ),
        name='password_reset_done',
    ),
    path(
        'password-reset-confirm/<uidb64>/<token>/',
        auth_view.PasswordResetConfirmView.as_view(
            template_name='users/password_reset_confirm.html',
            success_url=reverse_lazy('password_reset_complete'),
        ),
        name='password_reset_confirm',
    ),
    path(
        'password-reset-complete/',
        auth_view.PasswordResetCompleteView.as_view(
            template_name='users/password_reset_complete.html'
        ),
        name='password_reset_complete',
    ),
    path('', include('project.urls')),
    # rest framework urls (legacy aim-dealers path kept as alias)
    path(
        'api/scraped-items/av-aim/',
        include(('project.api.urls', 'api'), namespace='api-scrape'),
    ),
    path(
        'api/scraped-items/aim-dealers/',
        include(('project.api.urls', 'api'), namespace='api-scrape-legacy'),
    ),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
