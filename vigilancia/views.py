from django.shortcuts import render
from django.db import connection
from .models import Admission
import time
from django.db.models import Subquery, OuterRef, Prefetch
from .models import Reading, Device

def dashboard(request):
    start_time = time.time()
    
    last_reading_qs = Reading.objects.filter(device=OuterRef('pk')).order_by('-instant').values('value')[:1]
    devices_with_last_reading = Device.objects.annotate(last_val=Subquery(last_reading_qs))

    admissions = Admission.objects.filter(
        discharged_at__isnull=True
    ).select_related("patient").prefetch_related(
        Prefetch('devices', queryset=devices_with_last_reading)
    )

    rows = []
    for a in admissions:
        for d in a.devices.all():
            last = d.last_val  # Usamos a anotação em vez de fazer nova query
            rows.append((a.patient.name, d.type, last))
            
    end_time = time.time()
    
    # Passamos os resultados e a contagem para o HTML
    context = {
        "rows": rows,
        "query_count": len(connection.queries),
        "total_time": round((end_time - start_time) * 1000, 2)
    }
    return render(request, "dashboard.html", context)