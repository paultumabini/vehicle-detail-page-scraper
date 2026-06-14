"""
User auth forms — register, login, profile.

/register/, /login/, and /password-reset/* render vdp-auth-input fields manually
in their templates; form widgets here are mostly for validation labels/errors.
Profile forms must set vdp-input via Meta.widgets only — redeclaring email= on
the form class drops widgets.
"""
from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _

from .models import Profile


class UserRegisterForm(UserCreationForm):
    # Email is required for account communication and password reset flows.
    # Template icons (register.html): fa-user, fa-envelope, fa-lock, fa-repeat.
    email = forms.EmailField(label='Email')
    password1 = forms.CharField(label='Enter password', widget=forms.PasswordInput)
    password2 = forms.CharField(label='Confirm password', widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ['username', 'email', 'password1', 'password2']
        help_texts = {
            'username': None,
        }


class MyLogInForm(AuthenticationForm):
    # Legacy widget attrs — login.html renders vdp-auth-input fields directly.
    username = forms.CharField(label='Username', widget=forms.TextInput(attrs={'style': 'margin:1rem 0 2rem', 'placeholder': 'Username'}))
    password = forms.CharField(label='Password', widget=forms.PasswordInput(attrs={'class': 'mb-4', 'placeholder': 'Password'}))

    error_messages = {
        'invalid_login': _("Invalid login. Note that both " "fields may be case-sensitive."),
        'inactive': _("This account is inactive."),
    }


class UserUpdateForm(forms.ModelForm):
    """
    Username and email — editable from /profile/.

    Both fields use Meta.widgets vdp-input. Do not redeclare email= here;
    a standalone EmailField overrides widgets and the email input loses its border.
    """

    class Meta:
        model = User
        fields = ['username', 'email']
        labels = {
            'email': 'Email',
        }
        help_texts = {
            'username': None,
        }
        widgets = {
            'username': forms.TextInput(
                attrs={'class': 'vdp-input', 'autocomplete': 'username'}
            ),
            'email': forms.EmailInput(
                attrs={'class': 'vdp-input', 'autocomplete': 'email'}
            ),
        }


class ProfileUpdateForm(forms.ModelForm):
    """Avatar upload — native input hidden; camera button in profile.html triggers it."""

    image = forms.ImageField(
        label='',
        widget=forms.FileInput(attrs={'class': 'vdp-profile-file-input', 'accept': 'image/*'}),
    )

    class Meta:
        model = Profile
        fields = ['image']
