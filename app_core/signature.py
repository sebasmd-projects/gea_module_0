import datetime
SOFTWARE_SIGNATURE = {
    "authors": [
        {
            "name": "Juan Sebastián Morales Delgado",
            "role": "Arquitectura, Backend, Frontend, Sistemas"
        },
        {
            "name": "Carlos Andrés Morales Valencia",
            "role": "Imagen y Diseño"
        }
    ],
    "copyright": f"© 2024–{datetime.datetime.now().year}",
    "rights": "Todos los derechos reservados",
    "ownership": "No existe cesión de derechos sin contrato escrito",
    "origin": "Aporte en industria bajo acuerdo verbal societario",
    "verification": "GitHub commits y control de versiones",
    "repositories": {
        "Site Propensiones Abogados": "https://github.com/sebasmd-projects/pag_propensionesabogados",
        "GEA Module 0": "https://github.com/sebasmd-projects/gea_module_0",
        "Fundación Attlas": "https://github.com/sebasmd-projects/pag_attlas_insolvency_react",
        "Pre-release GEA antes Atlas": "https://github.com/sebasmd-projects/atlas_propensiones.git"
    },
    "disclaimer": "El software se proporciona 'tal cual', sin garantías de ningún tipo."
}

def get_software_signature():
    print(SOFTWARE_SIGNATURE)
    return SOFTWARE_SIGNATURE

if __name__ == "__main__":
    get_software_signature()