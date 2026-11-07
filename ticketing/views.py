from django.shortcuts import render

def dashboard(request):
    return render(request, 'ticketing/dashboard.html')


def ticket_list(request):
    return render(request, 'ticketing/ticket_list.html')


def tracker(request):
    return render(request, 'ticketing/tracker.html')


def insights(request):
    return render(request, 'ticketing/insights.html')
