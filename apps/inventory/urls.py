from rest_framework.routers import DefaultRouter

from django.urls import include, path

from .views import ProductViewSet, StockMovementViewSet, StockViewSet

router = DefaultRouter()
router.register("products", ProductViewSet, basename="product")
router.register("stocks", StockViewSet, basename="stock")
router.register("stock-movements", StockMovementViewSet, basename="stock-movement")

urlpatterns = [
    path("", include(router.urls)),
]
