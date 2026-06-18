from django.urls import path
from django.views.generic import RedirectView

from webscraping.constants import DEFAULT_PROJECT_LIST_SLUG, LEGACY_AIM_PROJECT_SLUG

from . import views
from .views import (
    AccountUpdateView,
    ProjectCreateView,
    SiteCreateView,
    SiteDeleteView,
    SiteDetailView,
    SiteListView,
    SiteUpdateView,
)

urlpatterns = [
    path('', views.home, name='home'),
    path('projects/new/', ProjectCreateView.as_view(), name='new-project'),
    path(
        f'project/{LEGACY_AIM_PROJECT_SLUG}/',
        RedirectView.as_view(pattern_name='site-list', permanent=True),
        {'project_name': DEFAULT_PROJECT_LIST_SLUG},
        name='site-list-legacy',
    ),
    path('project/<project_name>/', SiteListView.as_view(), name='site-list'),
    # Must be before site-detail — otherwise export_scrape_by_csv is captured as <pk>.
    path(
        'project/<project_name>/export_scrape_by_csv/',
        views.scrape_data_csv,
        name='scrape-csv',
    ),
    path(
        'project/<project_name>/<str:pk>/', SiteDetailView.as_view(), name='site-detail'
    ),
    path('scrape/new/', SiteCreateView.as_view(), name='new-scrape'),
    path(
        'project/<project_name>/<str:pk>/update/',
        SiteUpdateView.as_view(),
        name='update-scrape',
    ),
    path(
        'project/<project_name>/<site>/<str:pk>/delete/',
        SiteDeleteView.as_view(),
        name='delete-scrape',
    ),
    path('api-docs/', views.api_docs, name='api-docs'),
    path('help/', views.help, name='help'),
    path('spider-templates/', views.spider_templates_view, name='spider-templates'),
    path('scrape-data-json/', views.scrape_data_json, name='scrape-json'),
    path('spider-log-json/', views.spider_logs_json, name='log-json'),
    path('web-provider-json/', views.web_providers_json, name='web-provider-json'),
    path('account-provider-json/', views.accounts_json, name='account-json'),
    path('accounts/', views.accounts_view, name='accounts'),
    path(
        'accounts/datatable/',
        views.accounts_datatable_json,
        name='accounts-datatable',
    ),
    # htmx clear-new action:
    path(
        'accounts/<int:account_id>/clear-new/',
        views.account_clear_new,
        name='account-clear-new',
    ),
    # In-app account edit (staff) — AccountUpdateView
    path(
        'accounts/<int:account_id>/edit/',
        AccountUpdateView.as_view(),
        name='account-edit',
    ),
]
