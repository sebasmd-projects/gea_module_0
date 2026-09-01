# apps/project/specific/documents/video_masonry/tests.py
"""
Galeria multimedia: quien la ve, quien se descarga y que queda registrado.

Sin pruebas hasta ahora. Tres cosas que importan aqui:

* **Quien entra.** Las tres vistas van con ``BuyerRequiredMixin``: es material
  comercial, no publico. Y las tres crean filas con ``request.user``, asi que
  si el mixin dejara pasar a un anonimo no seria solo una fuga -- reventaria
  al intentar guardar el registro.
* **La descarga no pasa por ``MEDIA_URL``.** Va por una vista que comprueba
  antes, igual que los PDF de certificacion (invariante 13). Un enlace directo
  al fichero se saltaria tanto el control como el recuento.
* **Cada descarga y cada vista quedan anotadas**, en dos sitios a la vez: el
  registro linea a linea y el contador agregado por (usuario, activo). Es lo
  que permite saber quien tiene que material, que en un sitio de activos
  historicos no es una metrica de producto sino una traza.

    manage.py test apps.project.specific.documents.video_masonry \\
        --settings=app_core.settings_test
"""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.project.common.users.models import UserModel

from .models import MediaAsset, MediaAssetInteraction, MediaAssetUserStats

PASSWORD = 'pw-for-tests-123'


class GalleryFixtureMixin:

    @classmethod
    def setUpTestData(cls):
        types = UserModel.UserTypeChoices

        cls.buyer = cls._user('buyer_one', types.BUYER)
        cls.holder = cls._user('holder_one', types.HOLDER)
        cls.staff = cls._user('staff_one', types.HOLDER, is_staff=True)

    @classmethod
    def _user(cls, username, user_type, **extra):
        return UserModel.objects.create_user(
            username=username, email=f'{username}@example.com',
            password=PASSWORD, user_type=user_type, **extra
        )

    def login(self, user):
        self.assertTrue(
            self.client.login(username=user.username, password=PASSWORD))

    def make_asset(self, name='foto.jpg', content=b'contenido-de-prueba'):
        asset = MediaAsset(caption='una foto')
        asset.file.save(name, SimpleUploadedFile(name, content), save=False)
        asset.save()

        return asset


class TestWhoCanSeeTheGallery(GalleryFixtureMixin, TestCase):
    """Material comercial: no es publico."""

    def setUp(self):
        self.url = reverse('video_masonry:gallery')

    def test_a_buyer_gets_in(self):
        self.login(self.buyer)

        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_a_holder_is_sent_away(self):
        self.login(self.holder)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('core:index'))

    def test_staff_gets_in_even_being_a_holder(self):
        self.login(self.staff)

        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_anonymous_is_sent_to_the_login(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)


class TestDownloading(GalleryFixtureMixin, TestCase):

    def setUp(self):
        self.asset = self.make_asset()
        self.url = reverse(
            'video_masonry:download', kwargs={'pk': self.asset.pk})

    def test_a_buyer_gets_the_file(self):
        self.login(self.buyer)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            b''.join(response.streaming_content), b'contenido-de-prueba')

    def test_it_comes_as_an_attachment(self):
        self.login(self.buyer)

        response = self.client.get(self.url)

        self.assertIn('attachment', response['Content-Disposition'])

    def test_a_holder_does_not(self):
        """
        Y lo que importa: sin quedar registrado a su nombre tampoco.
        """
        self.login(self.holder)

        self.client.get(self.url)

        self.assertEqual(MediaAssetInteraction.objects.count(), 0)

    def test_anonymous_does_not(self):
        self.client.get(self.url)

        self.assertEqual(MediaAssetInteraction.objects.count(), 0)

    def test_an_unknown_asset_is_a_404(self):
        self.login(self.buyer)

        response = self.client.get(
            reverse('video_masonry:download', kwargs={'pk': 999999}))

        self.assertEqual(response.status_code, 404)


class TestEveryDownloadIsRecorded(GalleryFixtureMixin, TestCase):
    """
    En un sitio de activos historicos, saber quien tiene que material no es
    una metrica de producto: es una traza.
    """

    def setUp(self):
        self.asset = self.make_asset()
        self.url = reverse(
            'video_masonry:download', kwargs={'pk': self.asset.pk})

        self.login(self.buyer)

    def test_it_leaves_a_line_with_who_and_what(self):
        self.client.get(self.url)

        entry = MediaAssetInteraction.objects.get()

        self.assertEqual(entry.user, self.buyer)
        self.assertEqual(entry.asset, self.asset)
        self.assertEqual(
            entry.action, MediaAssetInteraction.Action.DOWNLOAD)

    def test_it_also_bumps_the_counter(self):
        self.client.get(self.url)
        self.client.get(self.url)

        stats = MediaAssetUserStats.objects.get(
            user=self.buyer, asset=self.asset)

        self.assertEqual(stats.downloads_count, 2)
        self.assertIsNotNone(stats.last_downloaded_at)

    def test_the_lines_pile_up_while_the_counter_is_one_row(self):
        """
        Los dos registros dicen cosas distintas y por eso estan los dos: el
        detalle dice **cuando** fue cada una, el agregado dice cuantas van sin
        tener que contarlas.
        """
        for _ in range(3):
            self.client.get(self.url)

        self.assertEqual(MediaAssetInteraction.objects.count(), 3)
        self.assertEqual(MediaAssetUserStats.objects.count(), 1)

    def test_two_people_have_their_own_counter(self):
        self.client.get(self.url)

        other = self._user('buyer_two', UserModel.UserTypeChoices.BUYER)
        self.client.logout()
        self.login(other)
        self.client.get(self.url)

        self.assertEqual(MediaAssetUserStats.objects.count(), 2)
        self.assertEqual(
            MediaAssetUserStats.objects.get(user=self.buyer).downloads_count, 1)


class TestTrackingAView(GalleryFixtureMixin, TestCase):

    def setUp(self):
        self.asset = self.make_asset()
        self.url = reverse('video_masonry:track')

        self.login(self.buyer)

    def test_it_records_the_view(self):
        response = self.client.post(self.url, {'asset_id': self.asset.pk})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            MediaAssetInteraction.objects.get().action,
            MediaAssetInteraction.Action.VIEW,
        )

    def test_it_bumps_the_view_counter(self):
        self.client.post(self.url, {'asset_id': self.asset.pk})

        stats = MediaAssetUserStats.objects.get()

        self.assertEqual(stats.views_count, 1)
        self.assertEqual(stats.downloads_count, 0)

    def test_a_get_is_refused(self):
        """Contabilizar es un efecto: no puede colgarse de una URL."""
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 405)

    def test_a_bad_asset_id_is_a_400_not_a_crash(self):
        response = self.client.post(self.url, {'asset_id': 'no-es-un-numero'})

        self.assertEqual(response.status_code, 400)

    def test_an_unknown_asset_is_a_404(self):
        response = self.client.post(self.url, {'asset_id': 999999})

        self.assertEqual(response.status_code, 404)

    def test_a_holder_cannot_track_anything(self):
        self.client.logout()
        self.login(self.holder)

        self.client.post(self.url, {'asset_id': self.asset.pk})

        self.assertEqual(MediaAssetInteraction.objects.count(), 0)


class TestTheMediaAsset(GalleryFixtureMixin, TestCase):
    """El tipo y el tamano se derivan al guardar, no se piden."""

    def test_an_image_is_recognised(self):
        asset = self.make_asset('foto.jpg')

        self.assertEqual(asset.media_type, MediaAsset.MediaType.IMAGE)

    def test_a_video_is_recognised(self):
        asset = self.make_asset('clip.mp4')

        self.assertEqual(asset.media_type, MediaAsset.MediaType.VIDEO)

    def test_the_extension_is_not_case_sensitive(self):
        asset = self.make_asset('FOTO.JPG')

        self.assertEqual(asset.media_type, MediaAsset.MediaType.IMAGE)

    def test_the_size_is_recorded(self):
        asset = self.make_asset(content=b'x' * 1234)

        self.assertEqual(asset.size_bytes, 1234)

    def test_an_unknown_extension_is_refused(self):
        """
        La lista es de extensiones permitidas, no de prohibidas: lo que no se
        reconoce no entra. Un `.php` o un `.svg` en una carpeta que el
        servidor web sirve es un problema distinto y peor.
        """
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            self.make_asset('programa.php')

    def test_the_gallery_paginates(self):
        for index in range(20):
            self.make_asset(f'foto{index}.jpg')

        self.login(self.buyer)
        response = self.client.get(reverse('video_masonry:gallery'))

        self.assertEqual(len(response.context['items']), 15)
        self.assertTrue(response.context['has_next'])
        self.assertFalse(response.context['has_prev'])

    def test_a_nonsense_page_number_does_not_break_it(self):
        self.make_asset()
        self.login(self.buyer)

        for value in ('cero', '-3', '0'):
            with self.subTest(page=value):
                response = self.client.get(
                    reverse('video_masonry:gallery'), {'page': value})

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context['page'], 1)
