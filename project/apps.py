from django.apps import AppConfig


class ProjectConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'project'
    verbose_name = "Project App Section"

    def ready(self):
        # django-jazzmin 3.0.2 uses format_html(html_str), which breaks on Django 6+.
        from jazzmin.templatetags.jazzmin import register

        from project.jazzmin_compat import jazzmin_paginator_number

        register.simple_tag(name="jazzmin_paginator_number")(jazzmin_paginator_number)
