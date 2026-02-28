from django.shortcuts import redirect, render
from .models import Feedback

def submit_feedback(request):
    if request.method == "POST":
        Feedback.objects.create(
            name=request.POST.get("name"),
            email=request.POST.get("email"),
            message=request.POST.get("message"),
            rating=request.POST.get("rating")
        )
        return redirect("/thank-you/")

    return render(request, "feedback.html")