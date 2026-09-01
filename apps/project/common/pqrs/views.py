# apps/project/common/pqrs/views.py
"""
El formulario publico de PQRS y la consulta del estado.

Es **publico y sin sesion** a proposito: un titular puede ejercer sus derechos
sin ser usuario de la plataforma, y de hecho el caso mas probable --pedir que
se supriman unos datos-- es justo el de alguien que no quiere tener cuenta.

Eso lo convierte, como el formulario de recuperacion de contrasena, en una
superficie que alguien de fuera puede accionar: manda correo, guarda ficheros
y crea filas. De ahi el limite por IP.
"""

import logging
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.core.cache import cache
from django.core.files.storage import FileSystemStorage
from django.core.mail import send_mail
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView, TemplateView, View
from formtools.wizard.views import SessionWizardView

from apps.common.utils.client_ip import get_client_ip

from .forms import (ConfirmationForm, ContactForm, DescriptionForm,
                    LegalHolderForm, NaturalHolderForm, RequestTypeForm)
from .models import PQRSRequest

logger = logging.getLogger(__name__)

STEP_TYPE = 'type'
STEP_HOLDER = 'holder'
STEP_DESCRIPTION = 'description'
STEP_CONTACT = 'contact'
STEP_CONFIRM = 'confirm'

#: Cuantas solicitudes admite una IP por ventana. Alto para una persona
#: --nadie radica cinco quejas seguidas de verdad-- y bajo para un script.
MAX_PER_WINDOW = 5
WINDOW_SECONDS = 60 * 60


def wizard_file_storage() -> FileSystemStorage:
    """
    Donde descansan los adjuntos entre un paso y el siguiente.

    Un wizard con ficheros tiene que guardarlos mientras el usuario sigue
    rellenando, y **donde** los guarde importa aqui mas que en otros sitios:
    lo que se sube en este formulario es una cedula o un pasaporte.

    Por eso no van a ``MEDIA_ROOT``. Esa carpeta la sirve el servidor web, y
    en este proyecto hace falta un ``.htaccess`` para que no reparta lo que
    hay dentro (invariante 13). Un documento de identidad esperando en una
    ruta adivinable, aunque sea diez minutos, es exactamente el fallo que ese
    invariante existe para evitar.

    Se usa una carpeta hermana, fuera de lo servible. Si alguna vez se mueve,
    que sea a otro sitio que el servidor web tampoco sirva.
    """
    root = Path(settings.MEDIA_ROOT).parent / 'pqrs_tmp'

    return FileSystemStorage(location=str(root))


class PQRSWizardView(SessionWizardView):
    """
    Los cinco pasos.

    La rama natural/juridica se decide **en el servidor**, en ``get_form()``,
    y no escondiendo campos con JavaScript: un formulario que valida en el
    navegador es un formulario que no valida.
    """

    template_name = 'pqrs/wizard.html'

    # Fuera de MEDIA_ROOT a proposito: ver `wizard_file_storage()`.
    file_storage = wizard_file_storage()

    form_list = [
        (STEP_TYPE, RequestTypeForm),
        (STEP_HOLDER, NaturalHolderForm),  # se sustituye segun el paso 1
        (STEP_DESCRIPTION, DescriptionForm),
        (STEP_CONTACT, ContactForm),
        (STEP_CONFIRM, ConfirmationForm),
    ]

    STEP_LABELS = (
        (STEP_TYPE, _('Type of request')),
        (STEP_HOLDER, _('Your details')),
        (STEP_DESCRIPTION, _('Description')),
        (STEP_CONTACT, _('How to reach you')),
        (STEP_CONFIRM, _('Confirmation')),
    )

    def get_form_kwargs(self, step=None):
        return super().get_form_kwargs(step)

    # ------------------------------------------------------------------
    def _person_type(self):
        """
        Lee el tipo de persona del almacenamiento **crudo**.

        Con ``get_cleaned_data_for_step`` se entra en recursion:
        ``get_form_list()`` llama a ``get_form()``, que llamaria otra vez a
        la lista. Es el mismo motivo por el que el wizard de registro lo hace
        asi.
        """
        data = self.storage.get_step_data(STEP_TYPE) or {}
        value = data.get(f'{STEP_TYPE}-person_type')

        if isinstance(value, (list, tuple)):
            value = value[0] if value else None

        return value

    def get_form(self, step=None, data=None, files=None):
        step = step or self.steps.current

        if step == STEP_HOLDER:
            from collections import OrderedDict

            forms_by_step = OrderedDict(super().get_form_list())
            forms_by_step[STEP_HOLDER] = (
                LegalHolderForm
                if self._person_type() == PQRSRequest.PersonTypeChoices.LEGAL
                else NaturalHolderForm
            )
            self.form_list = forms_by_step

        return super().get_form(step=step, data=data, files=files)

    def get_context_data(self, form, **kwargs):
        context = super().get_context_data(form=form, **kwargs)

        context['title'] = _('Requests and complaints (PQRS)')
        context['steps_labels'] = self.STEP_LABELS
        context['current_step'] = self.steps.current
        context['step_number'] = self.steps.step1
        context['step_total'] = len(self.STEP_LABELS)

        # En el ultimo paso se enseña todo lo escrito antes de enviarlo: es
        # la unica pantalla donde el titular puede detectar un dato mal
        # tecleado, y el correo es su unica via de respuesta.
        if self.steps.current == STEP_CONFIRM:
            context['summary'] = self._summary()

        return context

    def _summary(self):
        gathered = {}

        for step, _label in self.STEP_LABELS[:-1]:
            gathered.update(self.get_cleaned_data_for_step(step) or {})

        return gathered

    # ------------------------------------------------------------------
    def _rate_key(self):
        return f'pqrs:submit:{get_client_ip(self.request)}'

    def _within_rate_limit(self) -> bool:
        return (cache.get(self._rate_key()) or 0) < MAX_PER_WINDOW

    def _record_submission(self):
        key = self._rate_key()

        try:
            cache.add(key, 0, timeout=WINDOW_SECONDS)
            cache.incr(key)
        except Exception:
            # Sin cache no se limita, pero tampoco se cae: el derecho de
            # peticion no puede depender de que Redis conteste.
            logger.warning('Could not record the PQRS submission rate')

    # ------------------------------------------------------------------
    def done(self, form_list, **kwargs):
        if not self._within_rate_limit():
            messages.error(
                self.request,
                _('Too many requests from this connection. Try again later, '
                  'or write to us directly.'),
            )
            return redirect(reverse('pqrs:new'))

        data = {}
        for step, _label in self.STEP_LABELS:
            data.update(self.get_cleaned_data_for_step(step) or {})

        request_object = self._build(data)

        self._record_submission()
        self._send_acknowledgement(request_object)
        self._notify_the_team(request_object)

        self.request.session['pqrs_radicado'] = request_object.radicado

        return redirect(
            reverse('pqrs:receipt', kwargs={'radicado': request_object.radicado})
        )

    def _build(self, data) -> PQRSRequest:
        person_type = data['person_type']

        record = PQRSRequest(
            request_type=data['request_type'],
            person_type=person_type,
            first_name=data.get('first_name', ''),
            last_name=data.get('last_name', ''),
            company_name=data.get('company_name', ''),
            legal_representative=data.get('legal_representative', ''),
            identification_type=data['identification_type'],
            identification_number=data['identification_number'],
            country=data['country'],
            city=data['city'],
            address=data['address'],
            email=data['email'],
            phone_code=data['phone_code'],
            phone_number=data['phone_number'],
            description=data['description'],
            use_titular_contact=data.get('use_titular_contact', True),
            contact_email=data.get('contact_email', ''),
            contact_phone=data.get('contact_phone', ''),
            contact_landline=data.get('contact_landline', ''),
            accepted_terms=data.get('accepted_terms', False),
            submitted_ip=get_client_ip(self.request),
        )

        if data.get('identity_document'):
            record.identity_document = data['identity_document']

        if data.get('legal_existence_document'):
            record.legal_existence_document = data['legal_existence_document']

        record.full_clean(exclude=['radicado', 'received_on', 'due_on'])
        record.save()

        return record

    # ------------------------------------------------------------------
    def _send_acknowledgement(self, record):
        """
        El acuse con el radicado y la fecha limite.

        Se manda **con la fecha de vencimiento dentro** a proposito: es el
        plazo que la ley le da al titular, y decirselo es la diferencia entre
        un acuse de recibo y un compromiso comprobable.
        """
        subject = _('We received your request %(radicado)s') % {
            'radicado': record.radicado}

        body = _(
            'We received your request.\n\n'
            'Reference: %(radicado)s\n'
            'Type: %(kind)s\n'
            'Received on: %(received)s\n'
            'We will answer by: %(due)s\n\n'
            'Quote the reference if you need to ask about it.\n'
        ) % {
            'radicado': record.radicado,
            'kind': record.get_request_type_display(),
            'received': record.received_on,
            'due': record.due_on,
        }

        try:
            send_mail(
                subject=str(subject),
                message=str(body),
                from_email=None,
                recipient_list=[record.reply_to],
                fail_silently=False,
            )
        except Exception:
            # Que no salga el correo no puede deshacer la radicacion: la
            # solicitud ya esta presentada y el plazo ya corre. Se registra y
            # el radicado se enseña en pantalla de todas formas.
            logger.exception(
                'Could not send the acknowledgement for %s', record.radicado)

    def _notify_the_team(self, record):
        recipients = getattr(settings, 'PQRS_NOTIFICATION_RECIPIENTS', None)

        if not recipients:
            return

        try:
            send_mail(
                subject=str(_('New PQRS: %(radicado)s') % {
                    'radicado': record.radicado}),
                message=str(_(
                    '%(kind)s from %(name)s.\nDue by %(due)s.\n'
                ) % {
                    'kind': record.get_request_type_display(),
                    'name': record.display_name,
                    'due': record.due_on,
                }),
                from_email=None,
                recipient_list=list(recipients),
                fail_silently=True,
            )
        except Exception:
            logger.exception('Could not notify the team about a new PQRS')


class PQRSReceiptView(DetailView):
    """
    El comprobante. Publico, y sin datos personales dentro.

    Enseña el radicado y las fechas: lo justo para que el titular sepa que su
    solicitud entro y hasta cuando hay para contestarle. No enseña el nombre,
    ni el documento, ni la descripcion, porque la URL lleva el radicado y un
    radicado circula por correo, por WhatsApp y por captura de pantalla.
    """

    model = PQRSRequest
    slug_field = 'radicado'
    slug_url_kwarg = 'radicado'
    context_object_name = 'pqrs'
    template_name = 'pqrs/receipt.html'


class PQRSLandingView(TemplateView):
    template_name = 'pqrs/landing.html'
