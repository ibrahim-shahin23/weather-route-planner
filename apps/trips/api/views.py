from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .. import container as container_module
from ..domain.risk import describe_rules
from . import presenters
from .serializers import AnalyzeRequestSerializer, HeatmapRequestSerializer


class _BaseView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]

    @property
    def services(self):
        # Looked up at call time so tests can patch `container.get_container`.
        return container_module.get_container()


class HealthView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"status": "ok"})


class RiskRulesView(_BaseView):
    throttle_scope = "light"

    def get(self, request):
        return Response(describe_rules())


class GeocodeView(_BaseView):
    throttle_scope = "geocode"

    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        if len(q) < 2:
            return Response({"results": []})
        places = self.services.geocoder.search(q[:200], limit=6)
        return Response({"results": [{"label": p.label, "lat": round(p.lat, 5), "lon": round(p.lon, 5)} for p in places]})


class AnalyzeView(_BaseView):
    throttle_scope = "analyze"

    def post(self, request):
        ser = AnalyzeRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        result = self.services.analysis.analyze(ser.to_domain())
        return Response(presenters.analysis(result))


class HeatmapView(_BaseView):
    throttle_scope = "heatmap"

    def post(self, request):
        ser = HeatmapRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        result = self.services.heatmap.build(ser.to_domain())
        return Response(presenters.heatmap(result))
