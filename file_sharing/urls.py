from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from .views import supabase_login

app_name = 'file_sharing'

urlpatterns = [
    path('', views.homepage, name='homepage'),
    # path('login/', auth_views.LoginView.as_view(template_name='file_sharing/login.html'), name='login'),
    path('login/', views.login_view, name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('register/', views.register, name='register'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('upload/', views.upload_file, name='upload'),
    path('download/<int:file_id>/', views.download_file, name='download'),
    path('share/<int:file_id>/', views.share_file, name='share'),
    path('delete/<int:file_id>/', views.delete_file_view, name='delete'),
    path('audit-logs/', views.audit_logs, name='audit_logs'),
    path('share-history/', views.share_history, name='share_history'),
    path('share/', views.share_page, name='share_page'),

    # path('chat/', ),

    path('profile/', views.profile, name='profile'),
    path('my-uploads/', views.user_uploads, name='user_uploads'),
    path('feedback/', views.feedback, name='feedback'),

    path("auth/supabase-login/", supabase_login, name='supabase_login'),

    # urls.py - add this line temporarily
    path("debug/auth/", views.debug_auth, name="debug_auth"),
    

]