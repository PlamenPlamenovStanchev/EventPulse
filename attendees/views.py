from django.contrib import messages
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from .forms import AttendeeForm
from .models import Attendee


class AttendeeListView(ListView):
    model = Attendee
    context_object_name = "attendees"
    template_name = "attendees/attendee_list.html"

    sort_options = {
        "name": ("name", "email"),
        "-name": ("-name", "email"),
        "email": ("email", "name"),
        "-email": ("-email", "name"),
    }

    def get_queryset(self):
        queryset = Attendee.objects.all()
        search_term = self.request.GET.get("q", "").strip()
        if search_term:
            queryset = queryset.filter(
                Q(name__icontains=search_term)
                | Q(email__icontains=search_term)
                | Q(phone__icontains=search_term)
            )
        return queryset.order_by(*self.sort_options[self.get_sort_option()])

    def get_sort_option(self):
        sort_option = self.request.GET.get("sort", "name")
        return sort_option if sort_option in self.sort_options else "name"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["search_term"] = self.request.GET.get("q", "").strip()
        context["sort"] = self.get_sort_option()
        return context


class AttendeeDetailView(DetailView):
    model = Attendee
    context_object_name = "attendee"
    template_name = "attendees/attendee_detail.html"

    def get_queryset(self):
        return Attendee.objects.prefetch_related("tickets__event")


class AttendeeCreateView(CreateView):
    model = Attendee
    form_class = AttendeeForm
    template_name = "attendees/attendee_form.html"

    def form_valid(self, form):
        messages.success(self.request, "Attendee created successfully.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("attendees:attendee_detail", kwargs={"pk": self.object.pk})


class AttendeeUpdateView(UpdateView):
    model = Attendee
    form_class = AttendeeForm
    template_name = "attendees/attendee_form.html"

    def form_valid(self, form):
        messages.success(self.request, "Attendee updated successfully.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("attendees:attendee_detail", kwargs={"pk": self.object.pk})


class AttendeeDeleteView(DeleteView):
    model = Attendee
    context_object_name = "attendee"
    template_name = "attendees/attendee_confirm_delete.html"

    def form_valid(self, form):
        try:
            response = super().form_valid(form)
        except ProtectedError:
            messages.error(
                self.request,
                "This attendee cannot be deleted because one or more tickets reference them.",
            )
            return redirect("attendees:attendee_detail", pk=self.object.pk)

        messages.success(self.request, "Attendee deleted successfully.")
        return response

    def get_success_url(self):
        return reverse("attendees:attendee_list")
