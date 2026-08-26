# apps/project/specific/internal/code_gen/management/commands/generate_certification_key.py

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        'Genera el par de claves Ed25519 con el que se firma el registro de '
        'certificacion. La clave privada va en la variable de entorno '
        'CERTIFICATION_SIGNING_KEY; la publica se publica sola.'
    )

    def handle(self, *args, **options):
        private_key = Ed25519PrivateKey.generate()

        private_raw = private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )

        public_raw = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

        private_b64 = base64.b64encode(private_raw).decode('ascii')
        public_b64 = base64.b64encode(public_raw).decode('ascii')

        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING(
            'Clave de firma del registro de certificacion'
        ))
        self.stdout.write('')
        self.stdout.write('Anade esta linea a tu .env (y NO la compartas):')
        self.stdout.write('')
        self.stdout.write(
            self.style.WARNING(f'CERTIFICATION_SIGNING_KEY={private_b64}')
        )
        self.stdout.write('')
        self.stdout.write('Clave publica (se publica sola, es informativa):')
        self.stdout.write(self.style.SUCCESS(public_b64))
        self.stdout.write('')
        self.stdout.write(
            'Cambiar esta clave invalida la firma de los registros ya '
            'descargados por terceros: los hashes siguen siendo correctos, '
            'pero el sello dejaria de verificar. Rotala solo si se ha '
            'comprometido, y conserva la clave anterior publicada.'
        )
        self.stdout.write('')
