import datetime

from ..generate_purchase_order import generate_purchase_order_pdf
from ..generate_service_order import generate_service_order_pdf

class DummyOffer:
    def __init__(self):
        self.id = 1
        self.created = datetime.datetime.now()
        self.asset_display_name = "Industrial Generator X200"
        self.offer_quantity = 5
        self.offer_amount = 12500.75
        self._quantity_type = "Units"
        self.es_observation = "Requiere entrega en bodega central en Bogotá."
        self.en_observation = "Requires delivery to the main warehouse in Bogotá."
        self.es_description = "Generador industrial de alta capacidad."
        self.en_description = "High-capacity industrial generator."
        self.description = "Generador industrial de alta capacidad."
        self.observation = "Requiere entrega en bodega central en Bogotá."

    def get_quantity_type_display(self):
        return self._quantity_type


class DummyUser:
    def get_full_name(self):
        return "Sebastián Morales"

    @property
    def email(self):
        return "sebastian@example.com"

    @property
    def username(self):
        return "sebastian"


# --- Probar la generación del PDF ---
offer = DummyOffer()
user = DummyUser()

pdf_bytes = generate_purchase_order_pdf(offer, user)
pdf_bytes_service = generate_service_order_pdf(offer, user)

# Guardar el PDF localmente para verificar
with open("orden_compra_dummy.pdf", "wb") as f:
    f.write(pdf_bytes)

with open("orden_servicio_dummy.pdf", "wb") as f:
    f.write(pdf_bytes_service)

print("PDF generado: orden_compra_dummy.pdf")
print("PDF generado: orden_servicio_dummy.pdf")
