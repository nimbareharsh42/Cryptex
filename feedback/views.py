from django.shortcuts import redirect, render
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from .forms import FeedbackForm
from .models import Feedback

@login_required
def submit_feedback(request):
    if request.method == "POST":
        form = FeedbackForm(request.POST)

        if form.is_valid():
            feedback = form.save(commit=False)
            feedback.user = request.user
            feedback.save()

            messages.success(request, "Feedback submitted successfully!")
        else:
            print(form.errors)  # ← THIS WILL EXPOSE YOUR BUG

        return redirect("file_sharing:dashboard")
    
@staff_member_required
def feedback_list(request):
    feedbacks = Feedback.objects.all().order_by('-created_at')
    return render(request, "feedback_list.html", {"feedbacks": feedbacks})