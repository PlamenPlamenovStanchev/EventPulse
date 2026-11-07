from django.shortcuts import render

def attendee_list(request):
    return render(request, 'attendees/attendee_list.html')
