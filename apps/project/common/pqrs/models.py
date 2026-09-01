# apps/project/common/pqrs/models.py
"""
Solicitudes de los titulares: peticiones, quejas, reclamos y sugerencias.

Esto no es un formulario de contacto. Cada fila de aqui es el ejercicio de un
derecho con **plazo legal**, y el sistema existe sobre todo para que ese plazo
no se pase por descuido:

* Una **consulta** se responde en 10 dias habiles, prorrogables 5 (Ley 1581 de
  2012, art. 14).
* Un **reclamo**, en 15 habiles, prorrogables 8 (art. 15).
* Un reclamo incompleto se requiere dentro de 5 dias, y si el interesado no
  contesta en 2 meses se entiende que desistio.

Por eso el modelo guarda las fechas y **calcula el vencimiento al recibir**, en
lugar de dejarlo a que alguien lo mire en un calendario. El conteo en dias
habiles vive en ``deadlines.py``, que es donde estan las trampas de verdad.

Dos decisiones que conviene entender antes de tocar nada:

**La identificacion va cifrada.** Es dato personal de alguien que casi nunca
es usuario de la plataforma --un titular puede escribir sin tener cuenta-- y
pedirla es obligatorio para acreditar quien reclama. Se cifra como el resto de
la PII del proyecto (invariante 4).

**El radicado no es la clave primaria.** Es lo que se le da al ciudadano para
que pregunte por su solicitud, asi que tiene que ser corto, decible por
telefono y no revelar cuantas solicitudes hay: un consecutivo puro cuenta el
volumen del despacho a cualquiera que radique dos veces.
"""

import uuid
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.translation import gettext_lazy as _
from encrypted_model_fields.fields import EncryptedCharField

from apps.common.utils.models import TimeStampedModel

from .deadlines import add_business_days, business_days_between


def identity_document_path(instance, filename):
    return f'pqrs/{instance.radicado}/identidad/{filename}'


def legal_existence_path(instance, filename):
    return f'pqrs/{instance.radicado}/existencia/{filename}'


class RequestTypeChoices(models.TextChoices):
    """
    Los siete del formulario.

    Los cuatro primeros son derechos del articulo 8 de la Ley 1581 --lo que
    el titular puede pedir sobre sus datos--; los tres ultimos son las vias
    por las que llega. La distincion no es cosmetica: **decide el plazo**.
    """

    ACCESS = 'ACCESS', _('Access')
    UPDATE = 'UPDATE', _('Update')
    RECTIFICATION = 'RECTIFICATION', _('Rectification')
    DELETION = 'DELETION', _('Deletion')
    PETITION = 'PETITION', _('Petition')
    COMPLAINT = 'COMPLAINT', _('Complaint')
    QUERY = 'QUERY', _('Query')


#: Que tipos cuentan como *reclamo* (15 dias habiles) y cuales como *consulta*
#: (10). Rectificar, actualizar y suprimir son reclamos en el sentido del
#: articulo 15: piden que se corrija algo. Acceder y consultar son consultas.
COMPLAINT_TYPES = frozenset({
    RequestTypeChoices.UPDATE,
    RequestTypeChoices.RECTIFICATION,
    RequestTypeChoices.DELETION,
    RequestTypeChoices.COMPLAINT,
    RequestTypeChoices.PETITION,
})

QUERY_DAYS = 10
QUERY_EXTENSION_DAYS = 5
COMPLAINT_DAYS = 15
COMPLAINT_EXTENSION_DAYS = 8

#: Plazo para subsanar un reclamo incompleto antes de entenderlo desistido.
AMENDMENT_MONTHS = 2


class PQRSRequest(TimeStampedModel):
    """Una solicitud de un titular, con su plazo y su trazabilidad."""

    class PersonTypeChoices(models.TextChoices):
        NATURAL = 'NATURAL', _('Natural person')
        LEGAL = 'LEGAL', _('Legal entity')

    class IdentificationTypeChoices(models.TextChoices):
        CC = 'CC', _('Citizen ID')
        CE = 'CE', _('Foreign ID')
        PA = 'PA', _('Passport')
        NIT = 'NIT', _('NIT')

    class StatusChoices(models.TextChoices):
        RECEIVED = 'RECEIVED', _('Received')
        IN_PROGRESS = 'IN_PROGRESS', _('In progress')
        AWAITING_AMENDMENT = 'AWAITING_AMENDMENT', _('Awaiting amendment')
        EXTENDED = 'EXTENDED', _('Extended')
        ANSWERED = 'ANSWERED', _('Answered')
        TRANSFERRED = 'TRANSFERRED', _('Transferred to another authority')
        WITHDRAWN = 'WITHDRAWN', _('Withdrawn')

    id = models.UUIDField(
        'ID', default=uuid.uuid4, primary_key=True, editable=False)

    radicado = models.CharField(
        _('Reference number'),
        max_length=20,
        unique=True,
        editable=False,
        db_index=True,
        help_text=_('What the person quotes when asking about their request.'),
    )

    request_type = models.CharField(
        _('Request type'),
        max_length=20,
        choices=RequestTypeChoices.choices,
    )

    person_type = models.CharField(
        _('Person type'),
        max_length=10,
        choices=PersonTypeChoices.choices,
        default=PersonTypeChoices.NATURAL,
    )

    # --- Persona natural ------------------------------------------------
    first_name = models.CharField(
        _('Names'), max_length=150, blank=True)
    last_name = models.CharField(
        _('Surnames'), max_length=150, blank=True)

    # --- Persona juridica -----------------------------------------------
    company_name = models.CharField(
        _('Company name'), max_length=200, blank=True)
    legal_representative = models.CharField(
        _('Legal representative'), max_length=200, blank=True)

    # --- Identificacion (comun a las dos) --------------------------------
    identification_type = models.CharField(
        _('Identification type'),
        max_length=5,
        choices=IdentificationTypeChoices.choices,
    )

    # Cifrado: es dato personal de alguien que casi nunca tiene cuenta aqui.
    identification_number = EncryptedCharField(
        _('Identification number'), max_length=50)

    # --- Localizacion ----------------------------------------------------
    country = models.CharField(_('Country'), max_length=100)
    city = models.CharField(_('City'), max_length=100)
    address = EncryptedCharField(_('Address'), max_length=255)

    email = models.EmailField(_('Email address'))
    phone_code = models.CharField(
        _('Phone code'), max_length=7, default='+57')
    phone_number = EncryptedCharField(_('Mobile'), max_length=25)

    # --- Adjuntos --------------------------------------------------------
    identity_document = models.FileField(
        _('Identity document'),
        upload_to=identity_document_path,
        blank=True, null=True,
        help_text=_('To prove who is making the request.'),
    )

    legal_existence_document = models.FileField(
        _('Certificate of existence and legal representation'),
        upload_to=legal_existence_path,
        blank=True, null=True,
    )

    # --- La solicitud ----------------------------------------------------
    description = models.TextField(_('Description'))

    use_titular_contact = models.BooleanField(
        _('Use the contact details above'), default=True)
    contact_email = models.EmailField(
        _('Contact email'), blank=True)
    contact_phone = EncryptedCharField(
        _('Contact mobile'), max_length=25, blank=True)
    contact_landline = EncryptedCharField(
        _('Landline'), max_length=25, blank=True)

    accepted_terms = models.BooleanField(
        _('Terms accepted'), default=False)

    # La constancia de la autorizacion: el art. 9 de la Ley 1581 obliga a
    # conservarla, y "el usuario marco una casilla" no es constancia si no se
    # guarda cuando y desde donde.
    accepted_at = models.DateTimeField(
        _('Terms accepted at'), blank=True, null=True, editable=False)
    submitted_ip = models.GenericIPAddressField(
        _('Submitted from'), blank=True, null=True, editable=False)

    # --- Tramite ---------------------------------------------------------
    status = models.CharField(
        _('Status'),
        max_length=20,
        choices=StatusChoices.choices,
        default=StatusChoices.RECEIVED,
        db_index=True,
    )

    received_on = models.DateField(
        _('Received on'), editable=False, db_index=True)

    due_on = models.DateField(
        _('Due on'),
        editable=False,
        db_index=True,
        help_text=_('Calculated in business days when it comes in.'),
    )

    extended = models.BooleanField(_('Extended'), default=False)

    answered_at = models.DateTimeField(
        _('Answered at'), blank=True, null=True)

    answered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='pqrs_answered',
        verbose_name=_('Answered by'),
    )

    answer = models.TextField(_('Answer'), blank=True)

    internal_notes = models.TextField(
        _('Internal notes'), blank=True,
        help_text=_('Not shown to the person who filed the request.'),
    )

    # ------------------------------------------------------------------
    # Plazos
    # ------------------------------------------------------------------
    @property
    def is_complaint(self) -> bool:
        """Si cuenta como reclamo (15 dias) o como consulta (10)."""
        return self.request_type in COMPLAINT_TYPES

    @property
    def base_days(self) -> int:
        return COMPLAINT_DAYS if self.is_complaint else QUERY_DAYS

    @property
    def extension_days(self) -> int:
        return (
            COMPLAINT_EXTENSION_DAYS if self.is_complaint
            else QUERY_EXTENSION_DAYS
        )

    def compute_due_date(self, *, extended: bool = False):
        """
        Hasta cuando hay para responder.

        La prorroga se cuenta **desde el vencimiento del primer termino**, no
        desde la recepcion: el articulo dice "siguientes al vencimiento del
        primer termino".
        """
        first = add_business_days(self.received_on, self.base_days)

        if not extended:
            return first

        return add_business_days(first, self.extension_days)

    @property
    def business_days_left(self) -> int:
        """
        Cuantos dias habiles quedan. Negativo si ya se paso.

        Es lo que decide el color en el listado, y por eso se calcula y no se
        guarda: un campo se queda viejo en cuanto pasa un dia.
        """
        return business_days_between(timezone.localdate(), self.due_on)

    @property
    def is_overdue(self) -> bool:
        if self.status in (self.StatusChoices.ANSWERED,
                           self.StatusChoices.WITHDRAWN,
                           self.StatusChoices.TRANSFERRED):
            return False

        return timezone.localdate() > self.due_on

    @property
    def amendment_deadline(self):
        """
        Hasta cuando puede subsanar antes de entenderse desistido.

        Dos meses de calendario, no habiles: el articulo 15 habla de meses.
        """
        if self.status != self.StatusChoices.AWAITING_AMENDMENT:
            return None

        return self.received_on + timedelta(days=30 * AMENDMENT_MONTHS)

    # ------------------------------------------------------------------
    def extend(self, *, by=None):
        """
        Prorroga el plazo, una sola vez.

        La ley permite **una** prorroga, y obliga a informar al interesado de
        los motivos y de la nueva fecha. Lo segundo no lo hace este metodo:
        aqui solo se mueve la fecha, y avisar es del flujo que lo llame.
        """
        if self.extended:
            raise ValidationError(
                _('This request has already been extended once.'))

        self.extended = True
        self.due_on = self.compute_due_date(extended=True)
        self.status = self.StatusChoices.EXTENDED
        self.save(update_fields=['extended', 'due_on', 'status', 'updated'])

    def mark_answered(self, user, answer: str):
        if not (answer or '').strip():
            raise ValidationError(_('An answer cannot be empty.'))

        self.answer = answer
        self.answered_by = user
        self.answered_at = timezone.now()
        self.status = self.StatusChoices.ANSWERED
        self.save(update_fields=[
            'answer', 'answered_by', 'answered_at', 'status', 'updated'])

    # ------------------------------------------------------------------
    @property
    def display_name(self) -> str:
        if self.person_type == self.PersonTypeChoices.LEGAL:
            return self.company_name

        return f'{self.first_name} {self.last_name}'.strip()

    @property
    def reply_to(self) -> str:
        """A donde se contesta: el contacto alterno manda si lo hay."""
        if not self.use_titular_contact and self.contact_email:
            return self.contact_email

        return self.email

    def clean(self):
        errors = {}

        if self.person_type == self.PersonTypeChoices.NATURAL:
            if not self.first_name:
                errors['first_name'] = _('Required for a natural person.')
            if not self.last_name:
                errors['last_name'] = _('Required for a natural person.')
        else:
            if not self.company_name:
                errors['company_name'] = _('Required for a legal entity.')
            if not self.legal_representative:
                errors['legal_representative'] = _(
                    'Required for a legal entity.')

        if not self.use_titular_contact and not (
            self.contact_email or self.contact_phone or self.contact_landline
        ):
            errors['contact_email'] = _(
                'Give at least one way to reach you, or use the details '
                'above.'
            )

        if not self.accepted_terms:
            errors['accepted_terms'] = _(
                'The data processing terms must be accepted.')

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self.radicado:
            self.radicado = self._new_radicado()

        if not self.received_on:
            self.received_on = timezone.localdate()

        if self.accepted_terms and not self.accepted_at:
            self.accepted_at = timezone.now()

        # El vencimiento se calcula al recibir y no se recalcula despues: si
        # se recalculara en cada guardado, cambiar el tipo de solicitud
        # mientras se tramita movria la fecha limite hacia adelante.
        if not self.due_on:
            self.due_on = self.compute_due_date()

        super().save(*args, **kwargs)

    @classmethod
    def _new_radicado(cls) -> str:
        """
        ``PQRS-2026-XXXXXX``: el ano, y seis caracteres al azar.

        Al azar y no consecutivo a proposito. Un consecutivo le dice a
        cualquiera que radique dos veces cuantas solicitudes recibe el
        despacho entre una y otra, y eso es informacion del negocio que no
        tiene por que ir impresa en un acuse de recibo.
        """
        year = timezone.localdate().year

        for _attempt in range(10):
            candidate = (
                f'PQRS-{year}-'
                f'{get_random_string(6, "ABCDEFGHJKLMNPQRSTUVWXYZ23456789")}'
            )

            if not cls.objects.filter(radicado=candidate).exists():
                return candidate

        raise ValidationError(_('Could not allocate a reference number.'))

    def __str__(self) -> str:
        return f'{self.radicado} — {self.get_request_type_display()}'

    class Meta:
        db_table = 'apps_pqrs_request'
        verbose_name = _('PQRS request')
        verbose_name_plural = _('PQRS requests')
        ordering = ['default_order', '-created']
        indexes = [
            models.Index(fields=['status', 'due_on']),
            models.Index(fields=['request_type']),
        ]
