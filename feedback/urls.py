from django.urls import path
from .views import feedback_list, submit_feedback

app_name = 'feedback'

urlpatterns = [
    path("submit/", submit_feedback, name="submit_feedback"),
    path("feedbacks/", feedback_list, name="feedback_list"),
]