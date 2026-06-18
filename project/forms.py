from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator

from .models import PROJECT_COLOR_CHOICES, Account, Project, TargetSite, Webprovider

PROJECT_SLUG_RE = RegexValidator(
    r'^[a-z0-9]+(?:-[a-z0-9]+)*$',
    message='Use lowercase letters, numbers, and hyphens only (e.g. av-aim).',
)


class ProjectCreateForm(forms.ModelForm):
    """Frontend form for new Target Sites projects (replaces Django admin shortcut)."""

    class Meta:
        model = Project
        fields = ['name', 'color', 'sort_order']
        labels = {
            'name': 'Project slug',
            'color': 'Sidebar color',
            'sort_order': 'Sort order',
        }
        help_texts = {
            'name': 'Used in URLs: /project/your-slug/. Lowercase, hyphens allowed.',
            'sort_order': 'Lower numbers appear first in the Target Sites sidebar.',
        }
        widgets = {
            'name': forms.TextInput(
                attrs={
                    'placeholder': 'e.g. fleet-sites',
                    'class': 'vdp-input',
                    'autocomplete': 'off',
                }
            ),
            'color': forms.RadioSelect(
                attrs={'class': 'vdp-color-picker__input'},
            ),
            'sort_order': forms.NumberInput(
                attrs={
                    'class': 'vdp-input',
                    'min': 0,
                    'step': 1,
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].validators.append(PROJECT_SLUG_RE)
        self.fields['color'].choices = PROJECT_COLOR_CHOICES
        # Default swatch matches brand purple (first palette option).
        if not self.instance.pk and not self.data:
            self.fields['color'].initial = 'brand'
        if not self.instance.pk:
            self.fields['sort_order'].required = False
            self.fields['sort_order'].initial = None

    def clean_name(self):
        name = (self.cleaned_data.get('name') or '').strip().lower()
        if not name:
            raise ValidationError('Project slug is required.')
        if Project.objects.filter(name__iexact=name).exists():
            raise ValidationError('A project with this slug already exists.')
        return name

    def clean_sort_order(self):
        value = self.cleaned_data.get('sort_order')
        if value is None or value == '':
            last = (
                Project.objects.order_by('-sort_order')
                .values_list('sort_order', flat=True)
                .first()
            )
            return (last or 0) + 10
        return value


class AccountUpdateForm(forms.ModelForm):
    """
    In-app account edit (/accounts/<id>/edit/) — operator-managed fields only.

    AIM-owned fields (name, status, stats) are read-only in account_form.html.
    Excludes aim_last_synced_at so manual saves never look like AIM sync rows.

    vdp_data_source / direct_feed_* are operator-only (not sync_accounts); they drive
    Accounts “VDP setup” column and dashboard covered vs need_setup KPIs.
    """

    class Meta:
        model = Account
        fields = [
            'web_provider',
            'account_manager',
            'site_url',
            'vdp_data_source',
            'direct_feed_file',
            'batch_feed_source',
            'note',
        ]
        labels = {
            'web_provider': 'Web provider',
            'account_manager': 'Account manager',
            'site_url': 'Site URL',
            'vdp_data_source': 'VDP data source',
            'direct_feed_file': 'Direct feed file',
            'batch_feed_source': 'Batch feed source',
            'note': 'Notes',
        }
        help_texts = {
            'web_provider': 'Synced to the linked target site when one exists.',
            'site_url': 'Dealer VDP URL from AIM or manual override.',
            'vdp_data_source': Account._meta.get_field('vdp_data_source').help_text,
            'direct_feed_file': Account._meta.get_field('direct_feed_file').help_text,
            'batch_feed_source': Account._meta.get_field('batch_feed_source').help_text,
        }
        widgets = {
            'web_provider': forms.Select(attrs={'class': 'vdp-input'}),
            'account_manager': forms.TextInput(
                attrs={'class': 'vdp-input', 'autocomplete': 'off'}
            ),
            'site_url': forms.TextInput(
                attrs={'class': 'vdp-input', 'placeholder': 'https://…'}
            ),
            'vdp_data_source': forms.Select(attrs={'class': 'vdp-input'}),
            'direct_feed_file': forms.TextInput(
                attrs={
                    'class': 'vdp-input',
                    'placeholder': 'e.g. dealer_12345_vdp.csv',
                    'autocomplete': 'off',
                }
            ),
            'batch_feed_source': forms.TextInput(
                attrs={
                    'class': 'vdp-input',
                    'placeholder': 'e.g. reynolds_master_batch.csv',
                    'autocomplete': 'off',
                }
            ),
            'note': forms.Textarea(
                attrs={
                    'class': 'vdp-input',
                    'rows': 3,
                    'placeholder': 'Internal notes for this account',
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['web_provider'].queryset = Webprovider.objects.order_by('name')
        self.fields['web_provider'].required = False
        self.fields['web_provider'].empty_label = '— none —'
        self.fields['account_manager'].required = False
        self.fields['site_url'].required = False
        self.fields['vdp_data_source'].choices = Account.VDP_DATA_SOURCE
        self.fields['direct_feed_file'].required = False
        self.fields['batch_feed_source'].required = False
        self.fields['note'].required = False

    def clean(self):
        cleaned_data = super().clean()
        # Switching back to SCRAPE clears feed fields so model.clean() stays valid.
        if cleaned_data.get('vdp_data_source') == 'SCRAPE':
            cleaned_data['direct_feed_file'] = None
            cleaned_data['batch_feed_source'] = None
        return cleaned_data


class SiteCreateForm(forms.ModelForm):
    """Create/update TargetSite — shared by /scrape/new/ and site update."""

    # Boolean scrape fields — class vdp-scrape-item-cb scopes All/None toolbar in newscrape.js
    SCRAPE_ITEM_FIELDS = (
        'condition',
        'unit',
        'year',
        'make',
        'model',
        'trim',
        'stock_number',
        'vin',
        'vehicle_url',
        'msrp',
        'price',
        'selling_price',
        'rebate',
        'discount',
        'images',
        'images_count',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Keep placeholder choices explicit for unselected ForeignKey dropdowns.
        self.fields['site_name'].empty_label = 'select...'
        self.fields['project'].empty_label = 'select...'
        # Feed ID is optional for providers that do not expose feed metadata.
        self.fields['feed_id'].required = False
        self.label_suffix = ''  # Remove default colon from labels.

        # /scrape/new/ omits status in targetsite_form.html; without this, POST fails
        # validation silently ("This field is required") and the form never saves.
        if not self.instance.pk:
            self.fields['status'].required = False
            self.fields['status'].initial = 'Pending'
        else:
            # Edit form shows status only to superusers — keep existing value for others.
            self.fields['status'].required = False

        # vdp-input / vdp-scrape-item-cb — styled in main.css (matches project_form.html)
        for name, field in self.fields.items():
            if name in self.SCRAPE_ITEM_FIELDS:
                field.widget.attrs.setdefault('class', 'vdp-scrape-item-cb')
            elif isinstance(
                field.widget,
                (forms.TextInput, forms.Textarea, forms.Select, forms.NumberInput),
            ):
                field.widget.attrs.setdefault('class', 'vdp-input')

    site_url = forms.CharField(
        label='Site URL',
        max_length=200,  # Match TargetSite.site_url — was 50 and rejected long dealer URLs.
        validators=[
            # Validate URL-like input while allowing optional scheme from operators.
            RegexValidator(
                r'((http|https)\:\/\/)?[a-zA-Z0-9\.\/\?\:@\-_=#]+\.([a-zA-Z]){2,6}([a-zA-Z0-9\.\&\/\?\:@\-_=#])*',
                message='Please enter a valid web address',
            )
        ],
        widget=forms.TextInput(
            attrs={
                'placeholder': 'site url',
            }
        ),
    )
    web_provider = forms.CharField(
        # Plain label — tooltip HTML moved to targetsite_form.html (Bootstrap tooltips removed)
        label='Web Provider',
        widget=forms.TextInput(
            attrs={
                'placeholder': 'select or add...',
                # No list= datalist — suggestions UI is initProviderCombobox() in newscrape.js
                'autocomplete': 'off',
            }
        ),
    )

    site_id = forms.CharField(
        label='Domain Name',
        widget=forms.TextInput(
            attrs={
                # Preserve explicit required attr for template-side rendering consistency.
                'required': 'true',
                'placeholder': 'domain name here',
            },
        ),
    )

    feed_id = forms.CharField(
        label='Feed ID',
        widget=forms.TextInput(
            attrs={
                'placeholder': 'optional',
            },
        ),
    )

    class Meta:
        model = TargetSite

        fields = [
            'site_name',
            'project',
            'site_url',
            'web_provider',
            'site_id',
            'feed_id',
            'note',
            'status',
            'condition',
            'unit',
            'year',
            'make',
            'model',
            'trim',
            'stock_number',
            'vin',
            'vehicle_url',
            'msrp',
            'price',
            'selling_price',
            'rebate',
            'discount',
            'images',
            'images_count',
        ]
        widgets = {
            'note': forms.Textarea(
                attrs={
                    'rows': '2',
                    'placeholder': 'Any notes or additional items to scrape, please specify here',
                }
            ),
        }
        labels = {
            'site_name': 'Site Name | Dealership',
            'project': 'Project',
            'note': 'Notes:',
            'status': 'Status',
            'condition': 'condition',
            'unit': 'as a unit',
            'year': 'year',
            'make': 'make',
            'model': 'model',
            'trim': 'trim',
            'stock_number': 'stock#',
            'vin': 'vin',
            'vehicle_url': 'vehicle url',
            'msrp': 'msrp',
            'price': 'price',
            'selling_price': 'selling price',
            'rebate': 'rebate',
            'discount': 'discount',
            'images': 'images',
            'images_count': 'images count',
        }
