from django.db.models import OuterRef, Prefetch, Subquery
from django.shortcuts import render
from .models import Admission, Device, Reading

def build_rows(version="naive"):
    qs = Admission.objects.filter(discharged_at__isnull=True)
    if version != "naive":
        qs = qs.select_related("patient")
    if version in ("prefetch", "subquery"):
        devs = Device.objects.all()
        if version == "subquery":
            latest = Reading.objects.filter(device=OuterRef("pk")).order_by("-instant")
            devs = devs.annotate(last_value=Subquery(latest.values("value")[:1]), last_instant=Subquery(latest.values("instant")[:1]))
        qs = qs.prefetch_related(Prefetch("devices", queryset=devs))
    rows = []
    for a in qs:
        for d in a.devices.all():
            if version == "subquery":
                value, instant = d.last_value, d.last_instant
            else:
                last = d.readings.order_by("-instant").first()
                value, instant = (last.value, last.instant) if last else (None, None)
            rows.append((a.patient.name, a.ward, d.type, value, instant))
    return rows

def dashboard(request):
    version = request.GET.get("v", "subquery")
    return render(request, "dashboard.html", {"rows": build_rows(version), "version": version})
