# GEA

## Dependencias

### Terceros

- **auditlog**: Permite llevar un registro de auditoría de los cambios en los modelos, especialmente útil para rastrear accesos y modificaciones en los registros de usuario.
- **axes**: Protege la aplicación contra ataques de fuerza bruta bloqueando los intentos de inicio de sesión fallidos repetidos.
- **corsheaders**: Middleware para manejar CORS en Django, necesario para permitir solicitudes desde diferentes orígenes.
- **django_filters**: Filtros avanzados para Django REST Framework, facilitando la creación de endpoints con parámetros de búsqueda.
- **django_otp**: Proporciona soporte para autenticación de un solo uso (OTP) en Django, base para 2FA.
- **django_otp.plugins.otp_email**: Plugin de OTP que envía códigos a través de correo electrónico.
- **django_otp.plugins.otp_static**: Plugin de OTP para códigos estáticos, usado como respaldo para otros métodos OTP.
- **django_otp.plugins.otp_totp**: Plugin de OTP basado en tiempo (TOTP), popular para 2FA.
- **django_recaptcha**: Implementa Google reCAPTCHA en formularios de Django para verificar que los envíos no sean de bots.
- **drf_yasg**: Generador de documentación Swagger para APIs construidas con Django REST Framework, lo que facilita la creación de documentación interactiva para tus endpoints.
- **honeypot**: Añade campos invisibles a los formularios para atrapar bots y reducir el spam en los formularios de contacto.
- **import_export**: Facilita la importación y exportación de datos en formatos como CSV y Excel desde el admin de Django. Puede ser útil para manejar grandes volúmenes de datos de clientes.
- **parler**: Proporciona funcionalidad de internacionalización para modelos Django, permitiendo el manejo de contenido en varios idiomas.
- **rest_framework**: Conjunto de herramientas para construir APIs RESTful en Django. Es fundamental para construir endpoints.
- **rest_framework.authtoken**: Permite la autenticación basada en tokens, útil para proporcionar acceso a la API mediante tokens.
- **rest_framework_simplejwt**: Proporciona autenticación basada en JSON Web Tokens (JWT), una forma segura de autenticación sin estado para APIs RESTful.
- **rosetta**: Herramienta para la traducción fácil de archivos `.po` en Django, facilita la traducción del contenido dentro de la aplicación.
- **two_factor**: Implementa autenticación de dos factores (2FA) utilizando `django_otp`.
- **two_factor.plugins.email**: Plugin de autenticación por correo electrónico para 2FA.

## Estructura DevOps
