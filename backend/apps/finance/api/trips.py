from decimal import Decimal

from rest_framework import serializers, status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.permissions import ModuleRequired
from apps.core.api_permissions import permission_required
from apps.forwarding.trips.models import Trip

from .. import periods
from .. import trip_expense as te
from .serializers import money


class AllocationSerializer(serializers.Serializer):
    order_id = serializers.IntegerField()
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0"))


class TripExpenseSerializer(serializers.Serializer):
    allocations = AllocationSerializer(many=True, allow_empty=False)


def _present(data: dict) -> dict:
    return {
        "trip": {
            **data["trip"],
            "price": money(data["trip"]["price"]),
            "carrier_price": money(data["trip"]["carrier_price"]),
        },
        "orders": [
            {**o, "lines": [{**ln, "expense": money(ln["expense"])} for ln in o["lines"]]}
            for o in data["orders"]
        ],
        "suggestion": [
            {"order_id": s["order_id"], "amount": money(s["amount"])} for s in data["suggestion"]
        ],
        "manual_unlinked": [
            {**m, "expense": money(m["expense"])} for m in data["manual_unlinked"]
        ],
    }


class TripExpenseLinesView(APIView):
    """GET - подсказка по заказам рейса; POST - создать строки расхода из цены рейса."""

    def get_permissions(self):
        code = "finance.create" if self.request.method == "POST" else "finance.view"
        return [ModuleRequired("finance")(), permission_required(code)()]

    def get_trip(self, pk):
        trip = Trip.objects.filter(pk=pk).first()
        if trip is None:
            raise NotFound()
        return trip

    def get(self, request, pk):
        return Response(_present(te.trip_expense_lines(self.get_trip(pk))))

    def post(self, request, pk):
        trip = self.get_trip(pk)
        ser = TripExpenseSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        lines = te.create_trip_expense(
            trip,
            ser.validated_data["allocations"],
            user=request.user,
            perms=periods.request_perms(request),
            adjust_reason=periods.request_adjust_reason(request),
        )
        return Response(
            {
                "lines": [
                    {"id": ln.pk, "order": ln.order_id, "expense": money(ln.expense)}
                    for ln in lines
                ]
            },
            status=status.HTTP_201_CREATED,
        )
