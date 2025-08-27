Modelos Involucrados:

    AssetModel
    AssetCategoryModel
    AssetLocationModel
    LocationModel
    
Flujo:

Inicio de Sesión del Tenedor:

El tenedor inicia sesión en el sistema utilizando sus credenciales.
Acceso a la Página de Registro de Activos:

Navega al formulario para registrar un nuevo activo.
Completar el Formulario de Registro:

Llena los datos del activo, incluyendo:
Nombre en español e inglés.
Categoría (puede seleccionar una existente o crear una nueva mediante un modal).
Imagen del activo (opcional).
Tipo de cantidad.
Observaciones (opcional).
Asignación de Ubicaciones al Activo:

Añade una o más ubicaciones donde el activo está disponible, especificando:
Ubicación (puede seleccionar una existente o crear una nueva mediante un modal).
Cantidad disponible en esa ubicación.
Guardar el Activo:

Envía el formulario.
El sistema valida los datos y crea el nuevo AssetModel junto con las relaciones en AssetLocationModel.
Confirmación:

El tenedor recibe una confirmación de que el activo ha sido registrado exitosamente.
